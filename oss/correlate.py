"""Modul 03 - Korelasi alarm berbasis topologi + waktu. TIDAK memakai label kebenaran (scenario_*/is_root).

1. Episode: alarm yang sama pada objek yang sama dengan jeda < FLAP_GAP digabung (link flapping -> satu episode)
2. Site mati = episode 'ne_down' pada cell-site router. Untuk tiap episode, naik di pohon transmisi selama induknya juga
   mati pada waktu yang tumpang tindih -> site teratas yang mati. Site di bawahnya hanya korban.
3. Penyebab di site teratas: alarm catu daya di site itu -> power; alarm link dari ujung atas -> transport_link;
   tanpa keduanya -> transport_link 'inferred'.
4. Alarm lokal: VSWR (+ degradasi sel yang sama), sel sleeping, lingkungan, sisanya berdiri sendiri.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

FLAP_GAP = timedelta(minutes=15)
POWER_LOOKBACK = timedelta(hours=6)
LINK_WINDOW = timedelta(minutes=10)
LOCAL_WINDOW = timedelta(minutes=30)
CAUSAL_SLACK = timedelta(minutes=4)      # selisih jam antar-NE yang masih ditoleransi
HIDDEN = {"scenario_id", "scenario_type", "is_root"}


def episodes(alarms: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for a in alarms:
        by[(a["object"], a["symptom"], a["ne_id"])].append(a)
    out = []
    for (obj, sym, ne), items in by.items():
        items.sort(key=lambda a: a["raised_at"])
        cur = None
        for a in items:
            if cur and a["raised_at"] - cur["end"] <= FLAP_GAP:
                cur["end"] = max(cur["end"], a["cleared_at"]); cur["alarm_ids"].append(a["alarm_id"])
            else:
                cur = {"object": obj, "symptom": sym, "ne_id": ne, "site_id": a["site_id"], "start": a["raised_at"],
                       "end": a["cleared_at"], "alarm_ids": [a["alarm_id"]]}
                out.append(cur)
    return out


def overlap(a, b, slack=timedelta(0)) -> bool:
    return a["start"] <= b["end"] + slack and b["start"] <= a["end"] + slack


def correlate(alarms: list[dict], inv: dict) -> dict:
    alarms = [{k: v for k, v in a.items() if k not in HIDDEN} for a in alarms]          # korelator buta label
    up = {l["b_end"]: l["a_end"] for l in inv["links"]}
    link_of = {l["b_end"]: l["link_id"] for l in inv["links"]}
    eps = episodes(alarms)
    by_sym = defaultdict(list)
    for e in eps:
        by_sym[e["symptom"]].append(e)
    # Site mati: bukti APA PUN di site itu (NE tak terjangkau, RAN out of service, sel mati), digabung per site.
    # Versi awal hanya memakai 'ne_down'; bila alarm itu hilang di site relay, rantai ke atas terputus dan korban di
    # belakangnya dikira insiden terpisah (ditemukan oleh mode sulit: 12 dari 40 transmisi putus terpecah).
    raw_down = defaultdict(list)
    for sym in ("ne_down", "ran_down", "cell_down"):
        for e in by_sym[sym]:
            raw_down[e["site_id"]].append(e)
    down = defaultdict(list)
    for sid, lst in raw_down.items():
        cur = None
        for e in sorted(lst, key=lambda e: e["start"]):
            if cur and e["start"] - cur["end"] <= FLAP_GAP:
                cur["end"] = max(cur["end"], e["end"])
            else:
                cur = {"site_id": sid, "start": e["start"], "end": e["end"]}
                down[sid].append(cur)

    def top_site(sid, ep):
        cur, cur_ep = sid, ep
        while up.get(cur) in down:
            parent = up[cur]
            # induk hanya penyebab bila matinya TIDAK lebih lambat dari anaknya (toleransi selisih jam antar-NE);
            # tanpa syarat ini dua gangguan bertingkat yang berselang beberapa menit tergabung menjadi satu
            hit = [p for p in down[parent] if overlap(p, cur_ep, LINK_WINDOW) and p["start"] <= cur_ep["start"] + CAUSAL_SLACK]
            if not hit:
                break
            cur, cur_ep = parent, min(hit, key=lambda p: p["start"])
        return cur, cur_ep

    incidents, used = [], set()
    groups = defaultdict(list)                                  # (site teratas, episode teratas) -> episode korban
    for sid, lst in down.items():
        for e in lst:
            top, tep = top_site(sid, e)
            groups[(top, id(tep))].append(e)
    tops = {}
    for (top, _), members in groups.items():
        tops_eps = [m for m in members if m["site_id"] == top]
        tep = min(tops_eps or members, key=lambda m: m["start"])
        tops.setdefault(top, []).append((tep, members))

    def collect(site_ids, start, end, syms):
        ids = []
        for sym in syms:
            for e in by_sym[sym]:
                if e["site_id"] in site_ids and overlap(e, {"start": start, "end": end}, LINK_WINDOW):
                    ids += e["alarm_ids"]
        return ids

    for top, entries in tops.items():
        for tep, members in entries:
            sites = {m["site_id"] for m in members}
            start = min(m["start"] for m in members); end = max(m["end"] for m in members)
            ids = collect(sites, start, end, ["ne_down", "ran_down", "cell_down"])
            power = [e for e in by_sym["mains"] + by_sym["battery"]
                     if e["site_id"] == top and start - POWER_LOOKBACK <= e["start"] <= start + LINK_WINDOW]
            link = [e for e in by_sym["link_fault"] if e["object"] == link_of.get(top) and overlap(e, tep, LINK_WINDOW)]
            if power:
                rtype, robj, how = "power", top, "power alarm at top site"
                ids += [i for e in power for i in e["alarm_ids"]]
                start = min(start, min(e["start"] for e in power))
            else:
                rtype, robj = "transport_link", link_of.get(top)
                how = "link alarm at upstream end" if link else "inferred from topology"
                ids += [i for e in link for i in e["alarm_ids"]]
            ids = [i for i in dict.fromkeys(ids) if i not in used]
            used.update(ids)
            if ids:
                incidents.append({"root_type": rtype, "root_object": robj, "evidence": how, "top_site": top,
                                  "start": start, "end": end, "sites_affected": len(sites), "alarm_ids": ids})

    # alarm lokal
    rest = [e for e in eps if not set(e["alarm_ids"]) & used]
    vswr = [e for e in rest if e["symptom"] == "vswr"]
    for e in vswr:
        ids = list(e["alarm_ids"])
        for d in rest:
            if d["symptom"] == "cell_degrade" and d["object"] == e["object"] and abs(d["start"] - e["start"]) <= LOCAL_WINDOW:
                ids += d["alarm_ids"]
        ids = [i for i in ids if i not in used]; used.update(ids)
        incidents.append({"root_type": "rf", "root_object": e["object"], "evidence": "VSWR on cell", "top_site": e["site_id"],
                          "start": e["start"], "end": e["end"], "sites_affected": 0, "alarm_ids": ids})
    kind = {"cell_sleep": "cell", "cell_degrade": "cell", "door": "environment", "temperature": "environment",
            "board_link": "noise", "mains": "power", "battery": "power", "link_fault": "transport_link"}
    for e in rest:
        ids = [i for i in e["alarm_ids"] if i not in used]
        if not ids:
            continue
        used.update(ids)
        incidents.append({"root_type": kind.get(e["symptom"], "other"), "root_object": e["object"], "evidence": "standalone",
                          "top_site": e["site_id"], "start": e["start"], "end": e["end"], "sites_affected": 0, "alarm_ids": ids})
    incidents.sort(key=lambda i: i["start"])
    for n, inc in enumerate(incidents, 1):
        inc["incident_id"] = f"INC{n:05d}"; inc["alarm_count"] = len(inc["alarm_ids"])
    return {"incidents": incidents, "episodes": len(eps)}


def evaluate(alarms: list[dict], scenarios: list[dict], incidents: list[dict]) -> dict:
    """Bandingkan dengan label: skenario benar bila alarm-nya mayoritas di SATU insiden yang akar & objeknya cocok."""
    inc_of = {aid: inc for inc in incidents for aid in inc["alarm_ids"]}
    by_scen = defaultdict(list)
    for a in alarms:
        by_scen[a["scenario_id"]].append(a["alarm_id"])
    per_type = defaultdict(lambda: {"scenarios": 0, "correct": 0, "split": 0, "merged": 0})
    scen_type = {}
    for a in alarms:
        scen_type[a["alarm_id"]] = a["scenario_id"]
    for s in scenarios:
        ids = by_scen[s["scenario_id"]]
        if not ids:                       # skenario tanpa alarm (sel tidur senyap) dinilai oleh detektor KPI, bukan di sini
            continue
        incs = defaultdict(int)
        for i in ids:
            incs[inc_of[i]["incident_id"]] += 1
        main_id = max(incs, key=incs.get)
        main = next(inc_of[i] for i in ids if inc_of[i]["incident_id"] == main_id)
        t = per_type[s["type"]]
        t["scenarios"] += 1
        t["correct"] += int(main["root_type"] == s["root_type"] and main["root_object"] == s["root_object"])
        t["split"] += int(len(incs) > 1)
        t["merged"] += int(len({scen_type[i] for i in main["alarm_ids"]}) > 1)
    total = sum(t["scenarios"] for t in per_type.values())
    correct = sum(t["correct"] for t in per_type.values())
    return {"alarms": len(alarms), "incidents": len(incidents), "compression": round(len(alarms) / max(len(incidents), 1), 2),
            "root_cause_accuracy": round(correct / total, 4), "per_type": {k: dict(v) for k, v in sorted(per_type.items())}}
