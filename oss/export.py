"""Modul 09 (data) - ekspor ringkas dari DuckDB ke published/dashboard.json untuk halaman dashboard statis di portofolio.

Hanya agregat dan daftar teratas (bukan 5 juta baris counter), supaya halaman tetap ringan. Semua data sintetis.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
TOP_INCIDENTS = 15


def rows(con, sql, params=None):
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        out.append({c: (v.isoformat(sep=" ", timespec="minutes") if isinstance(v, datetime) else
                        v.isoformat() if isinstance(v, date) else round(v, 3) if isinstance(v, float) else v)
                    for c, v in zip(cols, r)})
    return out


def one(con, sql):
    return rows(con, sql)[0]


def export(db: Path = ROOT / "data" / "oss.duckdb", out: Path = ROOT / "published" / "dashboard.json") -> dict:
    con = duckdb.connect(str(db), read_only=True)
    ev = json.loads((db.parent / "evaluation.json").read_text(encoding="utf-8"))
    d: dict = {"generated_at": datetime.now().isoformat(timespec="minutes"), "synthetic": True}

    d["inventory"] = one(con, """SELECT (SELECT count(*) FROM stg_sites) sites, (SELECT count(*) FROM stg_network_elements) nes,
        (SELECT count(*) FROM stg_cells) cells, (SELECT count(*) FROM stg_links WHERE link_type='microwave') mw_links,
        (SELECT count(*) FROM stg_links WHERE link_type='fiber') fiber_links""")
    d["inventory_by_branch"] = rows(con, """SELECT branch, any_value(vendor) vendor, count(DISTINCT site_id) FILTER (WHERE true) sites,
        sum(cells) cells FROM (SELECT s.branch, s.vendor, s.site_id, (SELECT count(*) FROM stg_cells c WHERE c.site_id=s.site_id) cells
        FROM stg_sites s) GROUP BY branch ORDER BY sites DESC""")
    d["network_daily"] = rows(con, "SELECT * FROM mart_network_daily ORDER BY day")
    d["kpi_branch_week"] = rows(con, """SELECT branch, round(100*sum(avail_s)/(count(*)*3600.0),3) availability_pct,
        round(sum(dl_volume_mb)*8/nullif(sum(dl_active_s),0),2) user_thr_mbps, round(100*sum(rrc_succ)/nullif(sum(rrc_att),0),2) accessibility_pct,
        round(100*sum(erab_drop)/nullif(sum(erab_rel),0),3) drop_rate_pct, round(sum(lat_ms_sum)/nullif(sum(lat_n),0),1) latency_ms,
        round(100*sum(pkt_lost)/nullif(sum(pkt_total),0),3) packet_loss_pct, round(sum(dl_volume_mb)/1048576,1) traffic_tb
        FROM stg_kpi_hourly GROUP BY branch ORDER BY availability_pct""")

    # alarm -> insiden
    d["alarms"] = one(con, """SELECT count(*) alarms, count(*) FILTER (WHERE severity='Critical') critical,
        (SELECT count(*) FROM stg_incidents) incidents,
        (SELECT count(*) FROM stg_incidents WHERE root_type IN ('transport_link','power')) network_incidents FROM stg_alarms""")
    d["alarm_names"] = rows(con, """SELECT vendor, alarm_name, severity, any_value(name_source) name_source, count(*) n
        FROM stg_alarms GROUP BY ALL ORDER BY n DESC LIMIT 14""")
    d["correlation_summary"] = rows(con, "SELECT * FROM mart_correlation_summary")
    d["accuracy"] = {k: v for k, v in ev["per_type"].items() if k not in ("noise", "environment")}
    d["kpi_detection"] = ev.get("kpi_detection", {})

    # insiden teratas menurut dampak pelanggan, dengan pohon site (induk transmisi) untuk visual korelasi
    top = rows(con, f"""SELECT c.*, n.evidence, n.top_site, n.branch, n.cluster, n.vendor, n.started_at, n.ended_at, n.minutes,
        n.sites_affected, n.alarm_count FROM mart_incident_customer_impact c JOIN mart_network_incidents n USING (incident_id)
        ORDER BY weighted_impact DESC LIMIT {TOP_INCIDENTS}""")
    for inc in top:
        inc["sites"] = rows(con, """WITH s AS (SELECT DISTINCT site_id FROM incident_sites WHERE incident_id = ?)
            SELECT s.site_id, st.lat, st.lon, l.a_end AS parent, l.link_type,
                   (SELECT count(*) FROM stg_incident_alarms ia JOIN stg_alarms a USING (alarm_id)
                    WHERE ia.incident_id = ? AND a.site_id = s.site_id) alarms,
                   (SELECT count(*) FROM stg_services v WHERE v.site_id = s.site_id) services
            FROM s JOIN stg_sites st USING (site_id) JOIN stg_links l ON l.b_end = s.site_id ORDER BY s.site_id""",
            [inc["incident_id"], inc["incident_id"]])
        inc["alarm_mix"] = rows(con, """SELECT a.alarm_name, a.severity, count(*) n FROM stg_incident_alarms ia JOIN stg_alarms a USING (alarm_id)
            WHERE ia.incident_id = ? GROUP BY ALL ORDER BY n DESC""", [inc["incident_id"]])
    d["top_incidents"] = top

    d["sleeping_cells"] = rows(con, """SELECT cell_id, site_id, tech, branch, started_at, ended_at, hours, has_alarm
        FROM mart_sleeping_cells ORDER BY has_alarm, hours DESC""")
    d["congestion"] = one(con, "SELECT count(*) cell_days, count(DISTINCT cell_id) cells FROM mart_congestion")
    d["congestion_top"] = rows(con, """SELECT cell_id, branch, count(*) AS n_days, max(hours_congested) max_hours, max(prb_peak_pct) prb_peak
        FROM mart_congestion GROUP BY ALL ORDER BY n_days DESC, max_hours DESC LIMIT 10""")

    d["sla_by_tier"] = rows(con, """SELECT sla_tier, any_value(sla_pct) sla_pct, any_value(sla_budget_month_min) budget_min, count(*) services,
        count(*) FILTER (WHERE down_min > 0) affected, count(*) FILTER (WHERE budget_used_pct >= 50) half_used,
        count(*) FILTER (WHERE sla_breached) breached, round(sum(down_min)) down_min FROM mart_service_sla GROUP BY 1
        ORDER BY CASE sla_tier WHEN 'Gold' THEN 1 WHEN 'Silver' THEN 2 ELSE 3 END""")
    d["sla_worst"] = rows(con, """SELECT service_id, customer_id, sector, product, branch, sla_tier, down_min, budget_used_pct, incident_ids
        FROM mart_service_sla WHERE down_min > 0 ORDER BY budget_used_pct DESC LIMIT 15""")
    d["sla_attribution"] = one(con, "SELECT round(sum(down_min)) down_min, round(sum(unattributed_min)) unattributed_min FROM mart_service_sla")

    d["order_funnel"] = rows(con, "SELECT * FROM mart_order_funnel")
    d["order_summary"] = rows(con, """SELECT status, coalesce(nullif(fail_reason,''),'-') reason, count(*) orders,
        round(median(date_diff('minute', received_at, completed_at))/60.0,1) median_hours FROM stg_orders GROUP BY ALL ORDER BY orders DESC""")
    d["bottlenecks"] = rows(con, "SELECT * FROM mart_capacity_bottlenecks LIMIT 10")
    con.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"file": str(out), "bytes": out.stat().st_size}
