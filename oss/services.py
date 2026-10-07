"""Modul 06 & 07 - Layanan pelanggan korporat dan SIMULASI alur provisioning.

Layanan menumpang di cell-site router sebuah site; jalurnya ke core = jalur transmisi site itu (modul 01). Kapasitas tiap
link dipakai oleh backhaul seluler (puncak trafik site-site di belakangnya, dari counter KPI modul 04) ditambah bandwidth
layanan korporat yang sudah aktif. Order baru layak hanya bila SEMUA link di jalurnya masih punya ruang.

Modul 07 adalah SIMULASI alur kerja (bukan replika sistem provisioning operator tertentu).
"""
from __future__ import annotations

import random
from datetime import timedelta

from oss.faults import DAYS, START

SECTORS = ["Bank", "Pemerintah", "Tambang", "Perkebunan", "Ritel", "Rumah sakit", "Pendidikan", "Logistik"]
SLA = {"Gold": 99.9, "Silver": 99.5, "Bronze": 99.0}
PRODUCTS = {"Enterprise Internet": (20, 300), "IP VPN": (10, 100), "Dedicated Backhaul": (100, 500)}
PRODUCT_WEIGHT = [5, 4, 1]                                  # layanan korporat kebanyakan berkapasitas kecil
MW_STEPS = [400, 600, 1000, 2000, 5000]                     # microwave (2000+ = E-band); radio jarang < 400 Mbps
FIBER_STEPS = [1000, 10000, 20000, 40000, 100000]
# Dimensioning: kapasitas standar terkecil >= 2,5 x puncak backhaul (ruang untuk layanan korporat & pertumbuhan); 3% link
# sengaja pas-pasan (>= 1,1 x), seperti link yang terlambat di-upgrade. Kalibrasi: 1,6x dengan 10% link pas-pasan menolak
# 49% order (jalur ke core rata-rata ~8 link, hampir selalu melewati link pas-pasan); 2,5x dengan 3% menolak sekitar 22%.
MARGIN, TIGHT_MARGIN, TIGHT_SHARE = 2.5, 1.1, 0.03


def backhaul_peak_mbps(kpi_table, inv) -> dict[str, float]:
    """Puncak trafik backhaul per site (Mbps) = maksimum per jam dari Σ volume semua sel site itu."""
    import duckdb
    import pyarrow as pa
    con = duckdb.connect()
    con.register("k", kpi_table)
    con.register("c", pa.Table.from_pylist([{"cell_id": c["cell_id"], "site_id": c["site_id"]} for c in inv["cells"]]))
    rows = con.execute("""SELECT site_id, max(mb) * 8 / 3600 FROM
                          (SELECT c.site_id, k.ts, sum(k.dl_volume_mb) AS mb FROM k JOIN c USING (cell_id) GROUP BY ALL)
                          GROUP BY site_id""").fetchall()
    con.close()
    return {s: float(v) for s, v in rows}


class Network:
    def __init__(self, inv: dict, backhaul: dict[str, float], seed: int = 0):
        self.up = {l["b_end"]: l["a_end"] for l in inv["links"]}
        self.link_of = {l["b_end"]: l for l in inv["links"]}
        self.used = {l["link_id"]: 0.0 for l in inv["links"]}
        for sid, mbps in backhaul.items():                  # setiap link membawa puncak trafik semua site di belakangnya
            for link in self.path_links(sid):
                self.used[link["link_id"]] += mbps
        rr = random.Random(seed)
        self.capacity = {}
        for l in inv["links"]:
            steps = FIBER_STEPS if l["link_type"] == "fiber" else MW_STEPS
            need = self.used[l["link_id"]] * (TIGHT_MARGIN if rr.random() < TIGHT_SHARE else MARGIN)
            self.capacity[l["link_id"]] = float(next((c for c in steps if c >= need), steps[-1]))

    def path_links(self, sid: str) -> list[dict]:
        out, node = [], sid
        while node in self.link_of:
            out.append(self.link_of[node])
            node = self.up[node]
        return out

    def bottleneck(self, sid: str, mbps: float):
        """(link pertama yang tidak cukup atau None, sisa kapasitas terkecil di jalur)."""
        worst = None
        for l in self.path_links(sid):
            free = self.capacity[l["link_id"]] - self.used[l["link_id"]]
            if worst is None or free < worst[1]:
                worst = (l["link_id"], free)
        return (worst[0] if worst and worst[1] < mbps else None), (worst[1] if worst else 0)

    def reserve(self, sid: str, mbps: float, sign: int = 1) -> None:
        for l in self.path_links(sid):
            self.used[l["link_id"]] += sign * mbps


def site_down_at(down: dict[str, list], sid: str, t) -> bool:
    return any(s <= t < e for s, e in down.get(sid, []))


def build(inv: dict, impacts: list[dict], backhaul: dict[str, float], seed: int = 5102026,
          existing: int = 350, orders: int = 500) -> dict:
    r = random.Random(seed)
    net = Network(inv, backhaul, seed)
    down: dict[str, list] = {}
    for i in impacts:
        if i["level"] == "site":
            down.setdefault(i["object"], []).append((i["start"], i["end"]))
    sites = inv["sites"]
    weight = [4 if s["urban"] else 1 for s in sites]
    customers = [{"customer_id": f"CUST-{i:04d}", "sector": r.choice(SECTORS)} for i in range(1, 141)]

    def new_service(n, t_active):
        cust = r.choice(customers)
        product = r.choices(list(PRODUCTS), weights=PRODUCT_WEIGHT)[0]
        lo, hi = PRODUCTS[product]
        tier = r.choices(list(SLA), weights=[2, 5, 3])[0]
        return {"service_id": f"SVC-{n:05d}", "customer_id": cust["customer_id"], "sector": cust["sector"], "product": product,
                "site_id": r.choices(sites, weights=weight)[0]["site_id"], "bandwidth_mbps": r.randrange(lo, hi + 1, 10),
                "sla_tier": tier, "sla_pct": SLA[tier], "activated_at": t_active}

    services, n = [], 0
    while len(services) < existing and n < existing * 20:   # layanan aktif sebelum minggu simulasi (dibatasi)
        n += 1
        svc = new_service(n, START - timedelta(days=r.randint(30, 900)))
        if net.bottleneck(svc["site_id"], svc["bandwidth_mbps"])[0] is None:
            net.reserve(svc["site_id"], svc["bandwidth_mbps"])
            services.append(svc)

    order_rows, events = [], []
    times = sorted(START + timedelta(seconds=r.randint(0, DAYS * 86400 - 12 * 3600)) for _ in range(orders))
    for k, t0 in enumerate(times, 1):
        n += 1
        svc = new_service(n, None)
        oid = f"ORD-{k:05d}"

        def ev(step, ts, note=""):
            events.append({"order_id": oid, "step": step, "at": ts, "note": note})

        t = t0
        ev("RECEIVED", t)
        status, reason, bottleneck = "ACTIVATED", "", ""
        t += timedelta(minutes=r.randint(10, 240))
        link, free = net.bottleneck(svc["site_id"], svc["bandwidth_mbps"])
        if link:
            status, reason, bottleneck = "REJECTED", "INSUFFICIENT_CAPACITY", link
            ev("REJECTED", t, f"{link}: sisa {max(free, 0):.0f} Mbps, diminta {svc['bandwidth_mbps']} Mbps")
        else:
            ev("FEASIBILITY_OK", t)
            t += timedelta(minutes=r.randint(5, 60)); net.reserve(svc["site_id"], svc["bandwidth_mbps"]); ev("RESOURCE_RESERVED", t)
            t += timedelta(minutes=r.randint(30, 600)); ev("CONFIG_SENT", t)
            for attempt in range(1, 4):
                t += timedelta(minutes=r.randint(5, 45))
                reason = "CONFIG_TIMEOUT" if r.random() < 0.04 else "SITE_DOWN" if site_down_at(down, svc["site_id"], t) else ""
                if not reason:
                    ev("VALIDATED", t); t += timedelta(minutes=r.randint(1, 15)); ev("ACTIVATED", t)
                    svc["activated_at"] = t; services.append(svc)
                    break
                ev("VALIDATION_FAILED", t, reason)
                if attempt == 3:
                    status = "FAILED"; ev("RELEASED", t + timedelta(minutes=1), "reservasi dilepas")
                    net.reserve(svc["site_id"], svc["bandwidth_mbps"], -1)
                    break
                t += timedelta(hours=r.randint(1, 4)); ev("RETRY", t)
        order_rows.append({"order_id": oid, "service_id": svc["service_id"], "customer_id": svc["customer_id"],
                           "product": svc["product"], "site_id": svc["site_id"], "bandwidth_mbps": svc["bandwidth_mbps"],
                           "sla_tier": svc["sla_tier"], "received_at": t0, "completed_at": t, "status": status,
                           "fail_reason": reason if status != "ACTIVATED" else "", "bottleneck_link": bottleneck})
    capacity = [{"link_id": lid, "capacity_mbps": net.capacity[lid], "used_mbps": round(net.used[lid], 1)} for lid in net.capacity]
    return {"services": services, "orders": order_rows, "order_events": events, "link_capacity": capacity}
