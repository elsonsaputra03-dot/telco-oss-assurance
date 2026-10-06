"""python -m oss build   -> bangun ulang data sintetis, Parquet, dan model DuckDB di data/"""
import sys

from oss import pipeline


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "build":
        print(__doc__)
        return 2
    res = pipeline.build()
    for k, v in res["raw"].items():
        print(f"raw/{k:18s} {v:>8,} baris")
    for k, t in res["models"]:
        print(f"{k:34s} {t * 1000:7.0f} ms")
    ev = res["evaluation"]
    print(f"korelasi: {ev['alarms']:,} alarm -> {ev['incidents']:,} insiden; akurasi akar masalah per skenario:")
    for k, v in ev["per_type"].items():
        print(f"  {k:15s} {v['correct']:4d}/{v['scenarios']:<4d} benar, {v['split']} terpecah, {v['merged']} tercampur")
    return 0


if __name__ == "__main__":
    sys.exit(main())
