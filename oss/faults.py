"""Modul 02 - Fault management: katalog alarm per vendor + generator skenario gangguan berlabel (7 hari).

Nama alarm mengikuti penamaan yang lazim di referensi publik (dokumen dan forum telco); yang tidak ditemukan diberi nama
generik dan ditandai name_source='generic'. Semua kejadian SINTETIS.

Setiap alarm membawa label kebenaran (scenario_id, scenario_type, is_root) yang TIDAK dipakai korelator; label hanya untuk
mengukur akurasi korelasi (modul 03).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from oss import inventory as I

# (nama, severity, alarm_type, name_source) per gejala per vendor. ZTE = ZTE, EID = Ericsson.
CATALOG = {
    "ZTE": {
        "ne_down":      ("Link between OMM and NE broken", "Critical", "communication", "public"),
        "ran_down":     ("eNodeB is out of service", "Critical", "communication", "public"),
        "cell_down":    ("Cell shutdown alarm", "Critical", "quality_of_service", "public"),
        "cell_sleep":   ("Cell sleeping alarm", "Major", "quality_of_service", "public"),
        "cell_degrade": ("Cell performance deterioration alarm", "Major", "quality_of_service", "public"),
        "mains":        ("Embedded power DC Loop Broken", "Major", "equipment", "public"),
        "battery":      ("Embedded power Bat Loop Broken", "Critical", "equipment", "public"),
        "link_fault":   ("Transmission Link Fault", "Critical", "communication", "generic"),
        "vswr":         ("RF Unit VSWR Abnormal", "Major", "equipment", "generic"),
        "board_link":   ("Board communication link interrupted", "Major", "equipment", "public"),
        "door":         ("Cabinet Door Open", "Warning", "environment", "generic"),
        "temperature":  ("Cabinet Temperature High", "Minor", "environment", "generic"),
    },
    "EID": {
        "ne_down":      ("Heartbeat Failure", "Critical", "communication", "public"),
        "ran_down":     ("Service Unavailable", "Critical", "communication", "generic"),
        "cell_down":    ("Cell Unavailable", "Critical", "quality_of_service", "generic"),
        "cell_sleep":   ("Cell Sleeping Detected", "Major", "quality_of_service", "generic"),
        "cell_degrade": ("Cell Capability Degraded", "Major", "quality_of_service", "generic"),
        "mains":        ("Mains Power Failure", "Major", "equipment", "generic"),
        "battery":      ("Battery Backup Exhausted", "Critical", "equipment", "generic"),
        "link_fault":   ("Link Failure", "Critical", "communication", "public"),
        "vswr":         ("TX Antenna VSWR Limits Exceeded", "Major", "equipment", "public"),
        "board_link":   ("VSWR/Output Power Supervision Lost", "Minor", "equipment", "public"),
        "door":         ("RBS Door Open", "Warning", "environment", "public"),
        "temperature":  ("Cabinet Temperature High", "Minor", "environment", "generic"),
    },
}
CORE_LINK_ALARM = ("Interface Down", "Critical", "communication", "generic")
START = datetime(2026, 9, 28, 0, 0, 0)
DAYS = 7
MIX = {"transport_cut": 40, "power_outage": 30, "vswr": 60, "cell_sleeping": 80, "link_flapping": 15, "environment": 200,
       "noise": 1500}


class Gen:
    def __init__(self, inv: dict, seed: int):
        self.r = random.Random(seed)
        self.inv = inv
        self.sites = {s["site_id"]: s for s in inv["sites"]}
        self.ran = {}
        for ne in inv["network_elements"]:
            if ne["layer"] == "ran":
                self.ran.setdefault(ne["site_id"], []).append(ne)
        self.cells = {}
        for c in inv["cells"]:
            self.cells.setdefault(c["site_id"], []).append(c)
        self.children = {}
        for l in inv["links"]:
            self.children.setdefault(l["a_end"], []).append(l["b_end"])
        self.alarms: list[dict] = []
        self.truth: list[dict] = []
        self.impacts: list[dict] = []          # dampak SEBENARNYA (tidak ikut hilang saat alarm hilang): dasar KPI
        self.n = 0

    def downstream(self, site_id: str) -> list[str]:
        out, stack = [], [site_id]
        while stack:
            x = stack.pop()
            out.append(x)
            stack += self.children.get(x, [])
        return out

    def t(self) -> datetime:
        return START + timedelta(seconds=self.r.randint(0, DAYS * 86400 - 6 * 3600))

    def alarm(self, sid, ne_id, sym, raised, cleared, scen, root=False, obj=None, vendor=None):
        vendor = vendor or self.sites[sid]["vendor"]
        name, sev, typ, src = CORE_LINK_ALARM if sym == "core_link" else CATALOG[vendor][sym]
        self.n += 1
        self.alarms.append({"alarm_id": f"ALM{self.n:07d}", "ne_id": ne_id, "site_id": sid, "vendor": vendor,
                            "symptom": sym, "alarm_name": name, "severity": sev, "alarm_type": typ, "name_source": src,
                            "object": obj or ne_id, "raised_at": raised, "cleared_at": cleared,
                            "scenario_id": scen["scenario_id"], "scenario_type": scen["type"], "is_root": root})

    def impact(self, level, obj, kind, t0, t1, scen):
        self.impacts.append({"level": level, "object": obj, "kind": kind, "start": t0, "end": t1,
                             "scenario_id": scen["scenario_id"], "scenario_type": scen["type"]})

    def site_down(self, sid, t0, t1, scen):
        """Semua yang terlihat OSS saat site terputus: NE tidak terjangkau, RAN out of service, sel mati."""
        self.impact("site", sid, "outage", t0, t1, scen)
        j = lambda: timedelta(seconds=self.r.randint(5, 90))                    # noqa: E731
        k = lambda: timedelta(seconds=self.r.randint(10, 240))                  # noqa: E731
        self.alarm(sid, f"{sid}-CSR", "ne_down", t0 + j(), t1 + k(), scen)
        for ne in self.ran.get(sid, []):
            self.alarm(sid, ne["ne_id"], "ran_down", t0 + j(), t1 + k(), scen)
        for c in self.cells.get(sid, []):
            if self.r.random() < 0.85:                                           # tidak semua sel sempat lapor
                self.alarm(sid, c["ne_id"], "cell_down", t0 + j(), t1 + k(), scen, obj=c["cell_id"])

    def scenario(self, typ: str) -> dict:
        s = {"scenario_id": f"SC{len(self.truth) + 1:05d}", "type": typ}
        self.truth.append(s)
        return s

    def transport_cut(self):
        link = self.r.choice([l for l in self.inv["links"] if not l["a_end"].startswith("CORE-")])
        scen = self.scenario("transport_cut")
        t0 = self.t(); t1 = t0 + timedelta(minutes=self.r.randint(20, 360))
        a = link["a_end"]
        # ujung atas yang masih hidup melaporkan link putus: inilah satu-satunya alarm di sisi akar
        self.alarm(a, f"{a}-CSR", "link_fault", t0 + timedelta(seconds=self.r.randint(0, 20)), t1, scen, root=True,
                   obj=link["link_id"])
        for sid in self.downstream(link["b_end"]):
            self.site_down(sid, t0, t1, scen)
        scen.update(root_type="transport_link", root_object=link["link_id"], start=t0, end=t1)

    def power_outage(self):
        # sengaja sering memilih site relay: padamnya relay juga memutus site di belakangnya
        relays = [s for s in self.sites if self.children.get(s)]
        sid = self.r.choice(relays) if self.r.random() < 0.6 else self.r.choice(list(self.sites))
        scen = self.scenario("power_outage")
        t0 = self.t(); backup = timedelta(minutes=self.r.randint(30, 240)); t1 = t0 + backup + timedelta(minutes=self.r.randint(20, 300))
        self.alarm(sid, f"{sid}-CSR", "mains", t0, t1, scen, root=True, obj=sid)
        self.alarm(sid, f"{sid}-CSR", "battery", t0 + backup - timedelta(minutes=5), t1, scen)
        for d in self.downstream(sid):
            self.site_down(d, t0 + backup, t1, scen)
        scen.update(root_type="power", root_object=sid, start=t0, end=t1)

    def vswr(self):
        sid = self.r.choice(list(self.cells))
        c = self.r.choice(self.cells[sid]); scen = self.scenario("vswr")
        t0 = self.t(); t1 = t0 + timedelta(hours=self.r.randint(2, 48))
        self.alarm(sid, c["ne_id"], "vswr", t0, t1, scen, root=True, obj=c["cell_id"])
        self.impact("cell", c["cell_id"], "rf", t0, t1, scen)
        if self.r.random() < 0.7:
            self.alarm(sid, c["ne_id"], "cell_degrade", t0 + timedelta(minutes=self.r.randint(1, 15)), t1, scen, obj=c["cell_id"])
        scen.update(root_type="rf", root_object=c["cell_id"], start=t0, end=t1)

    def cell_sleeping(self):
        sid = self.r.choice(list(self.cells)); c = self.r.choice(self.cells[sid]); scen = self.scenario("cell_sleeping")
        t0 = self.t(); t1 = t0 + timedelta(minutes=self.r.randint(15, 600))
        self.alarm(sid, c["ne_id"], "cell_sleep", t0, t1, scen, root=True, obj=c["cell_id"])
        self.impact("cell", c["cell_id"], "sleeping", t0, t1, scen)
        scen.update(root_type="cell", root_object=c["cell_id"], start=t0, end=t1)

    def silent_sleeping(self):
        """Sel 'tidur' TANPA alarm: tampak available, tetapi tidak membawa trafik. Hanya terlihat dari KPI (mode sulit)."""
        sid = self.r.choice(list(self.cells)); c = self.r.choice([x for x in self.cells[sid] if x["tech"] == "4G"] or self.cells[sid])
        scen = self.scenario("silent_sleeping")
        t0 = self.t(); t1 = t0 + timedelta(hours=self.r.randint(4, 30))
        self.impact("cell", c["cell_id"], "sleeping", t0, t1, scen)
        scen.update(root_type="cell", root_object=c["cell_id"], start=t0, end=t1)

    def link_flapping(self):
        """Microwave terganggu cuaca: link putus-sambung berkali-kali dalam ~1 jam; satu gangguan, banyak alarm."""
        link = self.r.choice([l for l in self.inv["links"] if l["link_type"] == "microwave"])
        scen = self.scenario("link_flapping"); t = self.t(); t_start = t
        for _ in range(self.r.randint(4, 9)):
            down = timedelta(seconds=self.r.randint(40, 300))
            self.alarm(link["a_end"], f"{link['a_end']}-CSR", "link_fault", t, t + down, scen, root=True, obj=link["link_id"])
            for sid in self.downstream(link["b_end"]):
                self.site_down(sid, t, t + down, scen)
            t += down + timedelta(seconds=self.r.randint(60, 600))
        scen.update(root_type="transport_link", root_object=link["link_id"], start=t_start, end=t)

    def environment(self):
        sid = self.r.choice(list(self.sites)); scen = self.scenario("environment"); t0 = self.t()
        sym = self.r.choice(["door", "temperature"])
        self.alarm(sid, f"{sid}-CSR", sym, t0, t0 + timedelta(minutes=self.r.randint(5, 120)), scen, root=True, obj=sid)
        scen.update(root_type="environment", root_object=sid, start=t0, end=t0)

    def noise(self):
        sid = self.r.choice(list(self.cells)); c = self.r.choice(self.cells[sid]); scen = self.scenario("noise"); t0 = self.t()
        self.alarm(sid, c["ne_id"], "board_link", t0, t0 + timedelta(seconds=self.r.randint(10, 900)), scen, root=True, obj=c["cell_id"])
        scen.update(root_type="noise", root_object=c["cell_id"], start=t0, end=t0)


def concurrent_cut(g: "Gen") -> None:
    """Dua gangguan transmisi berbeda di subtree yang sama dengan selang < 10 menit (mode sulit)."""
    deep = [l for l in g.inv["links"] if len(g.downstream(l["b_end"])) >= 6 and not l["a_end"].startswith("CORE-")]
    outer = g.r.choice(deep)
    inner_sites = [x for x in g.downstream(outer["b_end"])[1:] if g.children.get(x)]
    if not inner_sites:
        return
    pick = g.r.choice(inner_sites)
    inner = next(l for l in g.inv["links"] if l["b_end"] == pick)
    t0 = g.t()
    for link, start in ((inner, t0), (outer, t0 + timedelta(minutes=g.r.randint(2, 9)))):
        scen = g.scenario("concurrent_cut"); t1 = start + timedelta(minutes=g.r.randint(30, 240))
        g.alarm(link["a_end"], f"{link['a_end']}-CSR", "link_fault", start, t1, scen, root=True, obj=link["link_id"])
        victims = g.downstream(link["b_end"])
        if link is outer:      # site di bawah gangguan dalam sudah mati lebih dulu; yang baru mati hanya sisanya
            victims = [v for v in victims if v not in set(g.downstream(inner["b_end"]))]
        for sid in victims:
            g.site_down(sid, start, t1, scen)
        scen.update(root_type="transport_link", root_object=link["link_id"], start=start, end=t1)


def degrade(g: "Gen", r: random.Random) -> None:
    """Mode sulit: alarm hilang dan jam NE tidak sinkron, seperti di NMS sungguhan."""
    skew = {sid: timedelta(seconds=r.randint(-180, 180)) for sid in g.sites}
    kept = []
    for a in g.alarms:
        if a["symptom"] == "link_fault" and a["scenario_type"] in ("transport_cut", "concurrent_cut") and r.random() < 0.3:
            continue
        if a["symptom"] == "mains" and r.random() < 0.3:
            continue
        if a["symptom"] == "ne_down" and r.random() < 0.1:
            continue
        sk = skew[a["site_id"]]
        a["raised_at"] += sk; a["cleared_at"] += sk
        kept.append(a)
    g.alarms = kept


def generate(inv: dict | None = None, seed: int = 28092026, mix: dict | None = None, hard: bool = False) -> dict:
    g = Gen(inv or I.build(), seed)
    for typ, n in (mix or MIX).items():
        for _ in range(n):
            getattr(g, typ)()
    if hard:
        for _ in range(20):
            concurrent_cut(g)
        for _ in range(30):
            g.silent_sleeping()
        degrade(g, random.Random(seed + 1))
        live = {a["scenario_id"] for a in g.alarms} | {i["scenario_id"] for i in g.impacts if i["scenario_type"] == "silent_sleeping"}
        g.truth = [s for s in g.truth if s["scenario_id"] in live]
    g.alarms.sort(key=lambda a: (a["raised_at"], a["alarm_id"]))
    for a in g.alarms:
        if a["cleared_at"] <= a["raised_at"]:
            a["cleared_at"] = a["raised_at"] + timedelta(seconds=30)
    return {"alarms": g.alarms, "scenarios": g.truth, "impacts": g.impacts}
