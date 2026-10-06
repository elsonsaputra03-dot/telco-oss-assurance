"""Modul 01 - Network Inventory & topologi transmisi (deterministik, biji tetap).

Masukan : reference/kalimantan_sites.json (site & sel sintetis yang SAMA dengan Network KPI Monitor)
Keluaran: sites, network_elements, cells, links

Topologi per cluster (pola jaringan seluler umum):
  CORE-<branch> --fiber--> PoP (1 per cluster) --fiber--> HUB --microwave--> site --microwave--> site ...
- PoP  : site urban terdekat dengan titik tengah cluster
- HUB  : dipilih menyebar (farthest-point sampling), kira-kira 1 per 15 site, terhubung ke PoP lewat pohon fiber
- site : disambung ke node terdekat yang sudah tersambung dan kedalamannya < MAX_MW_HOPS (rantai microwave)
Hasilnya pohon: setiap site punya tepat satu jalur ke core, jadi "siapa yang ikut terputus" bisa dihitung pasti.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "reference" / "kalimantan_sites.json"
SEED = 6102026
SITES_PER_HUB = 10
MAX_MW_HOPS = 3
HOP_PENALTY = 1.0
RAN_NE = {"2G": "BTS", "4G": "eNodeB", "5G": "gNodeB"}
TECH_CODE = {"2G": "G", "4G": "L", "5G": "N"}


def km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def load_sites(path: Path = REF) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["sites"]


def _pick_hubs(members: list[dict], pop: dict, n: int) -> list[dict]:
    hubs, cand = [pop], [s for s in members if s is not pop and s["site_type"] == "Macro"]
    while len(hubs) < n and cand:
        far = max(cand, key=lambda s: min(km(s, h) for h in hubs))
        hubs.append(far)
        cand.remove(far)
    return hubs


def build(seed: int = SEED, ref: Path = REF) -> dict[str, list[dict]]:
    rnd = random.Random(seed)
    raw = load_sites(ref)
    sites, nes, cells, links = [], [], [], []
    by_cluster: dict[str, list[dict]] = {}
    for s in sorted(raw, key=lambda x: x["site_id"]):
        by_cluster.setdefault(s["cluster"], []).append(s)

    role: dict[str, str] = {}
    parent: dict[str, tuple[str, str, float]] = {}      # site -> (node induk, jenis link, jarak km)
    depth: dict[str, int] = {}
    for branch in sorted({s["branch"] for s in raw}):
        nes.append({"ne_id": f"CORE-{branch.replace(' ', '_')}", "site_id": None, "ne_type": "CoreRouter", "tech": "IP",
                    "vendor": "Generic", "branch": branch, "layer": "core"})
    for cluster, members in sorted(by_cluster.items()):
        branch = members[0]["branch"]
        cy = sum(s["lat"] for s in members) / len(members)
        cx = sum(s["lon"] for s in members) / len(members)
        centre = {"lat": cy, "lon": cx}
        pool = [s for s in members if s["urban"]] or members
        pop = min(pool, key=lambda s: km(s, centre))
        hubs = _pick_hubs(members, pop, max(1, round(len(members) / SITES_PER_HUB)))
        core = f"CORE-{branch.replace(' ', '_')}"
        role[pop["site_id"]] = "pop"
        parent[pop["site_id"]] = (core, "fiber", 0.0)
        depth[pop["site_id"]] = 0
        # pohon fiber antar-hub (Prim dari PoP)
        connected = [pop]
        rest = [h for h in hubs if h is not pop]
        while rest:
            h, p = min(((h, p) for h in rest for p in connected), key=lambda hp: km(*hp))
            role[h["site_id"]] = "hub"
            parent[h["site_id"]] = (p["site_id"], "fiber", km(h, p))
            depth[h["site_id"]] = 0
            connected.append(h)
            rest.remove(h)
        # rantai microwave: site terdekat ke jaringan disambung lebih dulu
        tree = list(connected)
        others = sorted((s for s in members if s["site_id"] not in role), key=lambda s: min(km(s, h) for h in hubs))
        for s in others:
            ok = [n for n in tree if depth[n["site_id"]] < MAX_MW_HOPS]
            # penalti per hop: menyambung ke ujung rantai hanya dipilih bila hub/site dangkal jauh lebih jauh
            p = min(ok, key=lambda n: km(s, n) * (1 + HOP_PENALTY * depth[n["site_id"]]))
            role[s["site_id"]] = "leaf"
            parent[s["site_id"]] = (p["site_id"], "microwave", km(s, p))
            depth[s["site_id"]] = depth[p["site_id"]] + 1
            tree.append(s)

    for s in sorted(raw, key=lambda x: x["site_id"]):
        sid = s["site_id"]
        hub = sid
        while role.get(hub) == "leaf":
            hub = parent[hub][0]
        sites.append({"site_id": sid, "lat": s["lat"], "lon": s["lon"], "kab_code": s["kab_code"], "kab": s["kab"],
                      "branch": s["branch"], "cluster": s["cluster"], "vendor": s["vendor"], "urban": s["urban"],
                      "site_type": s["site_type"], "tx_role": role[sid], "tx_hub": hub, "mw_hops": depth[sid]})
        nes.append({"ne_id": f"{sid}-CSR", "site_id": sid, "ne_type": "CellSiteRouter", "tech": "IP", "vendor": "Generic",
                    "branch": s["branch"], "layer": "transport"})
        for tech in sorted({c[0] for c in s["cells"]}):
            ne_id = f"{sid}-{TECH_CODE[tech]}"
            nes.append({"ne_id": ne_id, "site_id": sid, "ne_type": RAN_NE[tech], "tech": tech, "vendor": s["vendor"],
                        "branch": s["branch"], "layer": "ran"})
            for t, band, sector, ci in s["cells"]:
                if t == tech:
                    cells.append({"cell_id": f"{ne_id}-{band}-{sector}", "ne_id": ne_id, "site_id": sid, "tech": tech,
                                  "band": band, "sector": sector, "ci": ci})
        p, kind, dist = parent[sid]
        links.append({"link_id": f"TX-{sid}", "a_end": p, "b_end": sid, "link_type": kind,
                      "capacity_mbps": 10000 if kind == "fiber" else rnd.choice([400, 600, 1000]),
                      "length_km": round(dist, 2)})
    return {"sites": sites, "network_elements": nes, "cells": cells, "links": links}


def path_to_core(sites: list[dict], links: list[dict], site_id: str) -> list[str]:
    """Jalur dari site ke core router (dipakai korelasi: link mana yang mungkin memutus site ini)."""
    up = {l["b_end"]: l["a_end"] for l in links}
    path, node = [site_id], site_id
    while node in up:
        node = up[node]
        path.append(node)
    return path
