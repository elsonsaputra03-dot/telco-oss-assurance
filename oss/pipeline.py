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
    tables = {**inv, "alarms": gen["alarms"], "scenarios": scen, "incidents": inc_rows, "incident_alarms": links}
    sizes = write_parquet(tables, raw)
    (out / "evaluation.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
    timings = run_models(out / "oss.duckdb", raw)
    return {"raw": sizes, "models": timings, "evaluation": ev}
