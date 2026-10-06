"""Modul 04 & 05: counter PM mengikuti dampak sebenarnya, KPI = Σ/Σ di setiap level, dan detektor sel tidur yang terukur."""
import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oss import pipeline as P  # noqa: E402


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    res = P.build(out)
    con = duckdb.connect(str(out / "oss.duckdb"), read_only=True)
    yield res, con, json.loads((out / "evaluation.json").read_text())
    con.close()


def test_kpi_rows_and_counter_sanity(built):
    res, con, _ = built
    assert res["raw"]["kpi_hourly"] == 30435 * 168
    bad = con.execute("""SELECT count(*) FROM stg_kpi_hourly WHERE avail_s NOT BETWEEN 0 AND 3600 OR rrc_succ > rrc_att
                         OR erab_drop > erab_rel OR pkt_lost > pkt_total OR dl_active_s > avail_s""").fetchone()[0]
    assert bad == 0


def test_full_outage_hours_have_zero_availability(built):
    _, con, _ = built
    n, avail = con.execute("""
        SELECT count(*), max(k.avail_s) FROM stg_kpi_hourly k
        JOIN (SELECT DISTINCT site_id, raised_at, cleared_at FROM stg_alarms
              WHERE symptom = 'ne_down' AND cleared_at - raised_at > INTERVAL 3 HOUR LIMIT 50) a
          ON a.site_id = k.site_id AND k.ts >= a.raised_at + INTERVAL 30 MINUTE AND k.ts + INTERVAL 1 HOUR <= a.cleared_at - INTERVAL 30 MINUTE
    """).fetchone()
    assert n > 100 and avail == 0                                               # jam di tengah gangguan: sel tidak available


def test_ratio_of_sums_matches_raw_counters(built):
    _, con, _ = built
    mart = con.execute("SELECT availability_pct, user_thr_mbps FROM mart_kpi_daily WHERE level = 'branch' AND object = 'TARAKAN' "
                       "AND tech = '4G' AND day = DATE '2026-09-30'").fetchone()
    raw = con.execute("""SELECT round(100 * sum(avail_s) / (count(*) * 3600.0), 3), round(sum(dl_volume_mb) * 8 / sum(dl_active_s), 2)
                         FROM stg_kpi_hourly WHERE branch = 'TARAKAN' AND tech = '4G' AND ts::DATE = DATE '2026-09-30'""").fetchone()
    assert mart == raw
    levels = dict(con.execute("SELECT level, count(DISTINCT object) FROM mart_kpi_daily GROUP BY level").fetchall())
    assert levels["network"] == 1 and levels["branch"] == 7 and levels["cell"] == 30435


def test_network_kpis_are_plausible(built):
    _, con, _ = built
    avail, thr, lat, loss = con.execute("SELECT avg(availability_pct), avg(user_thr_mbps), avg(latency_ms), avg(packet_loss_pct) "
                                        "FROM mart_network_daily").fetchone()
    assert 97 < avail < 99.9 and 10 < thr < 40 and 15 < lat < 50 and loss < 1
    share = con.execute("SELECT count(DISTINCT cell_id) / 30435 FROM mart_congestion").fetchone()[0]
    assert 0.02 < share < 0.12                                                  # kongesti: beberapa persen sel, bukan seperempat


def test_sleeping_cell_detector(built):
    _, _, ev = built
    k = ev["kpi_detection"]
    assert k["precision"] >= 0.95 and k["recall"] >= 0.95
    assert k["silent_detected_as_silent"] == k["silent_truth"] == 30            # sel tidur tanpa alarm hanya terlihat dari KPI
