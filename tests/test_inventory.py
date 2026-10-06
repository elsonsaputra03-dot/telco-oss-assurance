"""Modul 01 & 08: integritas inventory, sifat pohon topologi, determinisme, dan konsistensi mart DuckDB."""
import collections
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oss import inventory as I, pipeline as P  # noqa: E402


@pytest.fixture(scope="module")
def inv():
    return I.build()


@pytest.fixture(scope="module")
def db(tmp_path_factory, inv):
    out = tmp_path_factory.mktemp("data")
    P.write_parquet(inv, out / "raw")
    P.run_models(out / "oss.duckdb", out / "raw")
    con = duckdb.connect(str(out / "oss.duckdb"), read_only=True)
    yield con
    con.close()


def test_same_network_as_kpi_monitor(inv):
    ref = I.load_sites()
    assert len(inv["sites"]) == len(ref) == 2137
    assert len(inv["cells"]) == sum(len(s["cells"]) for s in ref)


def test_referential_integrity(inv):
    sites = {s["site_id"] for s in inv["sites"]}
    nes = {n["ne_id"]: n for n in inv["network_elements"]}
    assert len(nes) == len(inv["network_elements"])                          # ne_id unik
    assert all(c["ne_id"] in nes and c["site_id"] in sites for c in inv["cells"])
    assert all(nes[c["ne_id"]]["tech"] == c["tech"] for c in inv["cells"])   # sel 4G di eNodeB, dst.
    assert all(n["site_id"] in sites for n in nes.values() if n["layer"] != "core")
    nodes = sites | {n for n in nes if n.startswith("CORE-")}
    assert all(l["a_end"] in nodes and l["b_end"] in sites for l in inv["links"])


def test_topology_is_a_tree_reaching_core(inv):
    up = collections.Counter(l["b_end"] for l in inv["links"])
    assert set(up.values()) == {1}                                            # tepat satu uplink per site
    for s in inv["sites"]:
        path = I.path_to_core(inv["sites"], inv["links"], s["site_id"])
        assert path[-1].startswith("CORE-") and len(path) == len(set(path))   # sampai core, tanpa siklus


def test_transmission_design_rules(inv):
    sites = inv["sites"]
    n = len(sites)
    hops = collections.Counter(s["mw_hops"] for s in sites)
    assert max(hops) <= I.MAX_MW_HOPS
    assert hops[1] / n > hops[3] / n                                          # rantai pendek lebih banyak dari panjang
    roles = collections.Counter(s["tx_role"] for s in sites)
    assert roles["pop"] == len({s["cluster"] for s in sites})                 # satu PoP per cluster
    kinds = {l["b_end"]: l["link_type"] for l in inv["links"]}
    assert all(kinds[s["site_id"]] == ("microwave" if s["tx_role"] == "leaf" else "fiber") for s in sites)
    assert all(l["length_km"] < 60 for l in inv["links"] if l["link_type"] == "microwave")


def test_deterministic(inv):
    again = I.build()
    assert again == inv


def test_marts_match_python(inv, db):
    s = inv["sites"][123]
    path = I.path_to_core(inv["sites"], inv["links"], s["site_id"])
    sql_path = [r[0] for r in db.execute("SELECT node FROM mart_site_path WHERE site_id = ? ORDER BY hop", [s["site_id"]]).fetchall()]
    assert sql_path == path
    # blast radius link PoP = seluruh site cluster-nya
    pop = next(x for x in inv["sites"] if x["tx_role"] == "pop")
    n = db.execute("SELECT sites_downstream FROM mart_link_impact WHERE b_end = ?", [pop["site_id"]]).fetchone()[0]
    assert n == sum(1 for x in inv["sites"] if x["cluster"] == pop["cluster"])
    total = db.execute("SELECT sum(cells) FROM mart_inventory_summary").fetchone()[0]
    assert total == len(inv["cells"])
