"""Modul 06 & 07: kapasitas link tidak pernah terlampaui, downtime layanan konsisten dengan KPI dan insiden, alur order valid."""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oss import inventory as I, pipeline as P, services as S  # noqa: E402


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    P.build(out)
    c = duckdb.connect(str(out / "oss.duckdb"), read_only=True)
    yield c
    c.close()


def test_capacity_never_exceeded(con):
    assert con.execute("SELECT count(*) FROM stg_link_capacity WHERE used_mbps > capacity_mbps + 0.01").fetchone()[0] == 0


def test_rejections_name_a_full_link_on_the_path(con):
    rows = con.execute("""SELECT o.order_id FROM stg_orders o
        WHERE o.status = 'REJECTED' AND o.bottleneck_link NOT IN
              (SELECT p.link_id FROM mart_site_path sp JOIN stg_links p ON p.b_end = sp.node WHERE sp.site_id = o.site_id)""").fetchall()
    assert rows == []                                                          # link penolak memang ada di jalur site itu
    share = con.execute("SELECT avg((status = 'REJECTED')::INT) FROM stg_orders").fetchone()[0]
    assert 0.1 < share < 0.35                                                   # dikalibrasi, bukan hampir semua ditolak


def test_order_workflow_is_ordered(con):
    bad = con.execute("""SELECT order_id FROM stg_order_events WHERE step = 'ACTIVATED' AND order_id NOT IN
                         (SELECT order_id FROM stg_order_events WHERE step = 'VALIDATED')""").fetchall()
    assert bad == []
    seq = con.execute("""SELECT count(*) FROM (SELECT order_id,
                             min(at) FILTER (WHERE step = 'RECEIVED') r, min(at) m,
                             max(at) FILTER (WHERE step = 'VALIDATED') v, max(at) FILTER (WHERE step = 'ACTIVATED') a
                         FROM stg_order_events GROUP BY order_id) WHERE r > m OR a < v""").fetchone()[0]
    assert seq == 0                                                            # waktu langkah tidak mundur


def test_service_downtime_is_measured_and_attributed(con):
    down, unattr = con.execute("SELECT sum(down_min), sum(unattributed_min) FROM mart_service_sla").fetchone()
    assert down > 0 and unattr / down < 0.01                                   # >99% downtime terlacak ke insiden korelasi
    # cek silang satu layanan: downtime = Σ (3600 - avail) dari counter KPI site-nya
    sid, svc_site, act, d = con.execute("""SELECT service_id, site_id, activated_at, down_min FROM mart_service_sla
                                         JOIN stg_services USING (service_id, site_id) WHERE down_min > 60 LIMIT 1""").fetchone()
    raw = con.execute("""SELECT round(sum(3600 - a) / 60.0) FROM (SELECT ts, avg(avail_s) a FROM stg_kpi_hourly WHERE site_id = ?
                         AND ts >= date_trunc('hour', ?::TIMESTAMP) GROUP BY ts)""", [svc_site, act]).fetchone()[0]
    assert raw == d


def test_sla_uses_monthly_budget(con):
    rows = con.execute("SELECT DISTINCT sla_tier, sla_budget_month_min FROM mart_service_sla ORDER BY 1").fetchall()
    assert rows == [("Bronze", 432.0), ("Gold", 43.2), ("Silver", 216.0)]
    assert con.execute("SELECT count(*) FROM mart_service_sla WHERE sla_breached <> (down_min > sla_budget_month_min)").fetchone()[0] == 0


def test_dimensioning_rule():
    inv = I.build()
    net = S.Network(inv, {s["site_id"]: 30.0 for s in inv["sites"]}, seed=1)
    for l in inv["links"]:
        cap, used = net.capacity[l["link_id"]], net.used[l["link_id"]]
        steps = S.FIBER_STEPS if l["link_type"] == "fiber" else S.MW_STEPS
        assert cap in steps and (cap >= used * S.TIGHT_MARGIN or cap == steps[-1])
