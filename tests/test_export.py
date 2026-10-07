"""Modul 09: ekspor dashboard ringkas, konsisten dengan mart, dan pohon insiden yang tersambung."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oss import export as E, pipeline as P  # noqa: E402


def test_dashboard_export(tmp_path):
    P.build(tmp_path)
    res = E.export(tmp_path / "oss.duckdb", tmp_path / "dashboard.json")
    assert res["bytes"] < 400_000                                               # halaman tetap ringan
    d = json.loads((tmp_path / "dashboard.json").read_text())
    assert d["synthetic"] is True and d["inventory"]["sites"] == 2137
    assert len(d["network_daily"]) == 7 and len(d["top_incidents"]) == 15
    w = [i["weighted_impact"] for i in d["top_incidents"]]
    assert w == sorted(w, reverse=True)                                         # diurutkan menurut dampak pelanggan
    for inc in d["top_incidents"]:
        ids = {s["site_id"] for s in inc["sites"]}
        assert inc["top_site"] in ids
        # setiap site korban tersambung ke site teratas lewat induk transmisinya (pohon utuh untuk ditampilkan)
        top = next(s for s in inc["sites"] if s["site_id"] == inc["top_site"])
        parent = {s["site_id"]: s["parent"] for s in inc["sites"]}
        for s in inc["sites"]:
            node, seen = s["site_id"], 0
            while node != inc["top_site"] and node in parent and seen < 20:
                node, seen = parent[node], seen + 1
            assert node == inc["top_site"] or s["site_id"] == top["parent"]
        assert sum(m["n"] for m in inc["alarm_mix"]) == inc["alarm_count"]
