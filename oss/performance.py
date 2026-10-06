"""Modul 04 - Performance management: counter PM per sel per jam selama 7 hari (sintetis, ~5,1 juta baris).

Counter, bukan KPI jadi (seperti file PM dari OMC): KPI dihitung belakangan sebagai Σ pembilang ÷ Σ penyebut di level
mana pun (modul 05). Gangguan diambil dari DAMPAK SEBENARNYA (faults.generate()['impacts']), bukan dari alarm, sehingga
site yang alarmnya hilang tetap terlihat mati di KPI, dan sel yang 'tidur' tanpa alarm tetap terlihat dari trafiknya.

Counter per sel-jam:
  avail_s            detik sel tersedia (0..3600)
  dl_volume_mb       volume data downlink
  dl_active_s        detik ada data yang dikirim (throughput user = volume*8 / active_s)
  rrc_att / rrc_succ upaya & sukses koneksi (accessibility)
  erab_rel / erab_drop  pelepasan bearer total & abnormal (drop rate)
  lat_ms_sum / lat_n    latensi (rata-rata)
  pkt_total / pkt_lost  paket (packet loss)
  prb_used_pct       utilisasi PRB rata-rata (%)
  users_max          user aktif maksimum
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pyarrow as pa

from oss.faults import DAYS, START

HOURS = DAYS * 24
# pola harian trafik (relatif), puncak malam hari
DIURNAL = np.array([.35, .25, .18, .15, .15, .2, .35, .55, .7, .75, .78, .8, .82, .8, .78, .8, .85, .92, 1, 1, .98, .9, .72, .52],
                   dtype=np.float32)
TECH_BASE = {"2G": (60, 1.5), "4G": (1800, 22.0), "5G": (5200, 110.0)}     # (MB/jam saat puncak, Mbps per user)


def generate(inv: dict, impacts: list[dict], seed: int = 4102026) -> pa.Table:
    rng = np.random.default_rng(seed)
    cells = inv["cells"]
    n = len(cells)
    site_urban = {s["site_id"]: s["urban"] for s in inv["sites"]}
    idx = {c["cell_id"]: i for i, c in enumerate(cells)}
    by_site: dict[str, list[int]] = {}
    for i, c in enumerate(cells):
        by_site.setdefault(c["site_id"], []).append(i)

    tech = np.array([c["tech"] for c in cells])
    peak_mb = np.array([TECH_BASE[t][0] for t in tech], dtype=np.float32)
    rate = np.array([TECH_BASE[t][1] for t in tech], dtype=np.float32)
    urban = np.array([site_urban[c["site_id"]] for c in cells])
    load = rng.lognormal(0, .45, n).astype(np.float32) * np.where(urban, 1.5, .7).astype(np.float32)
    hours = np.arange(HOURS)
    day = hours // 24
    weekend = np.isin(day % 7, [5, 6])                                   # 28 Sep 2026 adalah Senin
    shape = DIURNAL[hours % 24] * np.where(weekend, .9, 1).astype(np.float32)
    noise = rng.lognormal(0, .12, (n, HOURS)).astype(np.float32)
    demand = (peak_mb[:, None] * load[:, None] * shape[None, :] * noise)  # MB yang ingin dikirim jam itu

    avail = np.full((n, HOURS), 3600, dtype=np.float32)
    rf_factor = np.ones((n, HOURS), dtype=np.float32)                    # <1 bila RF terganggu (VSWR)
    sleep = np.zeros((n, HOURS), dtype=bool)

    def hour_overlap(t0, t1):
        a = max(0.0, (t0 - START).total_seconds()); b = min(HOURS * 3600.0, (t1 - START).total_seconds())
        out = []
        h = int(a // 3600)
        while h < HOURS and h * 3600 < b:
            ov = min(b, (h + 1) * 3600) - max(a, h * 3600)
            if ov > 0:
                out.append((h, ov))
            h += 1
        return out

    for imp in impacts:
        if imp["level"] == "site":
            rows = by_site.get(imp["object"], [])
            for h, ov in hour_overlap(imp["start"], imp["end"]):
                avail[rows, h] = np.maximum(0, avail[rows, h] - ov)
        elif imp["object"] in idx:
            i = idx[imp["object"]]
            for h, ov in hour_overlap(imp["start"], imp["end"]):
                if imp["kind"] == "rf":
                    rf_factor[i, h] = min(rf_factor[i, h], .35)
                elif imp["kind"] == "sleeping" and ov >= 1800:
                    sleep[i, h] = True

    frac = avail / 3600.0
    served = np.where(sleep, demand * .01, demand * frac)                 # sel tidur: available tetapi hampir tanpa trafik
    users = np.maximum(0, np.round(served / (peak_mb[:, None] * .02) + rng.poisson(1, (n, HOURS)))).astype(np.int32)
    thr = rate[:, None] * rf_factor * rng.lognormal(0, .15, (n, HOURS)).astype(np.float32)   # Mbps per user
    prb = np.clip(served / np.maximum(peak_mb[:, None] * 2.6, 1) * 100 * (2 - rf_factor), 0, 100)
    thr = thr * np.where(prb > 85, .55, 1)                                # kongesti menurunkan throughput user
    active = np.where(served > 0, served * 8 / np.maximum(thr, .1), 0)
    active = np.minimum(active, avail)
    att = np.round(users * rng.uniform(8, 14, (n, HOURS))).astype(np.int64)
    acc_fail = np.clip(.004 + (1 - rf_factor) * .05 + (prb > 85) * .02, 0, 1)
    succ = np.round(att * (1 - acc_fail)).astype(np.int64)
    rel = np.round(succ * .95).astype(np.int64)
    drop = np.round(rel * np.clip(.003 + (1 - rf_factor) * .04 + (frac < 1) * (1 - frac) * .3, 0, 1)).astype(np.int64)
    lat = np.clip(18 + (prb / 100) ** 3 * 60 + (1 - rf_factor) * 40 + rng.normal(0, 2, (n, HOURS)), 5, None)
    pkt = np.round(served * 750).astype(np.int64)                          # ~750 paket per MB
    loss = np.round(pkt * np.clip(.0015 + (1 - rf_factor) * .03 + (prb > 90) * .006, 0, 1)).astype(np.int64)
    lat_n = np.where(served > 0, 100, 0)

    ts = np.array([np.datetime64(START + timedelta(hours=int(h))) for h in hours], dtype="datetime64[us]")
    cell_ids = pa.array([c["cell_id"] for c in cells]).dictionary_encode()
    take = np.repeat(np.arange(n), HOURS)
    return pa.table({
        "cell_id": cell_ids.take(pa.array(take)),
        "ts": pa.array(np.tile(ts, n)),
        "avail_s": avail.ravel().round().astype(np.int32),
        "dl_volume_mb": served.ravel().round(2),
        "dl_active_s": active.ravel().round().astype(np.int32),
        "rrc_att": att.ravel(), "rrc_succ": succ.ravel(),
        "erab_rel": rel.ravel(), "erab_drop": drop.ravel(),
        "lat_ms_sum": (lat * lat_n).ravel().round(1), "lat_n": lat_n.ravel().astype(np.int32),
        "pkt_total": pkt.ravel(), "pkt_lost": loss.ravel(),
        "prb_used_pct": prb.ravel().round(1).astype(np.float32),
        "users_max": users.ravel(),
    })
