"""Modul 08 - OSS Data Pipeline: sumber -> Parquet (lapisan raw) -> DuckDB (staging view -> mart table).

Setiap lapisan bisa diperiksa sendiri; mart dibangun ulang penuh dari Parquet sehingga hasilnya selalu bisa direproduksi.
"""
from __future__ import annotations

import time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "sql"


def write_parquet(tables: dict[str, list[dict]], out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, rows in tables.items():
        pq.write_table(pa.Table.from_pylist(rows), out / f"{name}.parquet", compression="zstd")
        sizes[name] = len(rows)
    return sizes


def run_models(db: Path, parquet: Path) -> list[tuple[str, float]]:
    con = duckdb.connect(str(db))
    timings = []
    for layer in ("staging", "marts"):
        for f in sorted((SQL / layer).glob("*.sql")):
            t0 = time.perf_counter()
            con.execute(f.read_text(encoding="utf-8").replace("{parquet}", parquet.as_posix()))
            timings.append((f"{layer}/{f.name}", time.perf_counter() - t0))
    con.close()
    return timings


def build(out: Path = ROOT / "data", hard: bool = True) -> dict:
    """Dataset bawaan memakai mode sulit (alarm hilang, jam tidak sinkron, gangguan bersamaan): lebih mirip NMS nyata."""
    import json

    from oss import correlate, faults, inventory
    raw = out / "raw"
    inv = inventory.build()
    gen = faults.generate(inv, hard=hard)
    cor = correlate.correlate(gen["alarms"], inv)
    ev = correlate.evaluate(gen["alarms"], gen["scenarios"], cor["incidents"])
    inc_rows = [{k: v for k, v in i.items() if k != "alarm_ids"} for i in cor["incidents"]]
    links = [{"incident_id": i["incident_id"], "alarm_id": a} for i in cor["incidents"] for a in i["alarm_ids"]]
    scen = [{k: v for k, v in s.items()} for s in gen["scenarios"]]
    tables = {**inv, "alarms": gen["alarms"], "scenarios": scen, "incidents": inc_rows, "incident_alarms": links,
              "impacts": gen["impacts"]}
    sizes = write_parquet(tables, raw)
    from oss import performance
    kpi = performance.generate(inv, gen["impacts"])
    pq.write_table(kpi, raw / "kpi_hourly.parquet", compression="zstd")
    sizes["kpi_hourly"] = kpi.num_rows
    from oss import services
    svc = services.build(inv, gen["impacts"], services.backhaul_peak_mbps(kpi, inv))
    sizes.update(write_parquet(svc, raw))
    timings = run_models(out / "oss.duckdb", raw)
    ev["kpi_detection"] = evaluate_kpi(out / "oss.duckdb", gen["impacts"])
    (out / "evaluation.json").write_text(json.dumps(ev, indent=2, default=str), encoding="utf-8")
    return {"raw": sizes, "models": timings, "evaluation": ev}


def evaluate_kpi(db: Path, impacts: list[dict], min_hours: int = 3) -> dict:
    """Detektor sel tidur vs dampak sebenarnya. Kebenaran: sel tidur >= min_hours jam penuh (lebih pendek tidak terdeteksi)."""
    from datetime import timedelta
    con = duckdb.connect(str(db), read_only=True)
    found = con.execute("SELECT cell_id, started_at, ended_at, has_alarm FROM mart_sleeping_cells").fetchall()
    con.close()
    sleeping = [i for i in impacts if i["kind"] == "sleeping"]
    # recall diukur pada sel tidur >= 4 jam (yang lebih pendek mungkin tidak punya 3 jam PENUH); precision diukur terhadap
    # SEMUA sel tidur sungguhan, termasuk yang pendek (versi awal tidak, dan salah menghitung 13 temuan benar sebagai salah)
    truth = [i for i in sleeping if i["end"] - i["start"] >= timedelta(hours=min_hours + 1)]
    hit = lambda f, t: f[0] == t["object"] and f[1] < t["end"] and f[2] > t["start"]          # noqa: E731
    tp_found = [f for f in found if any(hit(f, t) for t in sleeping)]
    detected = [t for t in truth if any(hit(f, t) for f in found)]
    silent = [t for t in truth if t["scenario_type"] == "silent_sleeping"]
    silent_ok = [t for t in silent if any(hit(f, t) and not f[3] for f in found)]
    return {"candidates": len(found), "precision": round(len(tp_found) / max(len(found), 1), 4),
            "recall": round(len(detected) / max(len(truth), 1), 4), "truth_sleeping_ge_4h": len(truth),
            "silent_truth": len(silent), "silent_detected_as_silent": len(silent_ok)}
