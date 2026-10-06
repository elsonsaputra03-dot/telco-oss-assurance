-- Modul 05: KPI harian di setiap level dalam SATU tabel (GROUPING SETS). KPI = Σ pembilang / Σ penyebut pada level itu,
-- bukan rata-rata dari rata-rata.
CREATE OR REPLACE TABLE mart_kpi_daily AS
SELECT
    CASE WHEN grouping(cell_id) = 0 THEN 'cell' WHEN grouping(site_id) = 0 THEN 'site' WHEN grouping(cluster) = 0 THEN 'cluster'
         WHEN grouping(branch) = 0 THEN 'branch' ELSE 'network' END AS level,
    coalesce(cell_id, site_id, cluster, branch, 'KALIMANTAN') AS object, branch, cluster, site_id, tech,
    ts::DATE AS day,
    round(100 * sum(avail_s) / (count(*) * 3600.0), 3)                AS availability_pct,
    round(sum(dl_volume_mb) * 8 / nullif(sum(dl_active_s), 0), 2)       AS user_thr_mbps,
    round(100 * sum(rrc_succ) / nullif(sum(rrc_att), 0), 2)             AS accessibility_pct,
    round(100 * sum(erab_drop) / nullif(sum(erab_rel), 0), 3)           AS drop_rate_pct,
    round(sum(lat_ms_sum) / nullif(sum(lat_n), 0), 1)                   AS latency_ms,
    round(100 * sum(pkt_lost) / nullif(sum(pkt_total), 0), 3)           AS packet_loss_pct,
    round(avg(prb_used_pct), 1)                                          AS prb_util_pct,
    round(sum(dl_volume_mb) / 1024, 1)                                   AS traffic_gb,
    max(users_max)                                                       AS users_peak
FROM stg_kpi_hourly
GROUP BY GROUPING SETS ((ts::DATE, tech), (branch, ts::DATE, tech), (branch, cluster, ts::DATE, tech),
                        (branch, cluster, site_id, ts::DATE, tech), (branch, cluster, site_id, cell_id, ts::DATE, tech));

-- Ringkasan jaringan per hari (semua teknologi digabung) untuk header dashboard
CREATE OR REPLACE TABLE mart_network_daily AS
SELECT ts::DATE AS day,
       round(100 * sum(avail_s) / (count(*) * 3600.0), 3) AS availability_pct,
       round(sum(dl_volume_mb) * 8 / nullif(sum(dl_active_s), 0), 2) AS user_thr_mbps,
       round(sum(lat_ms_sum) / nullif(sum(lat_n), 0), 1) AS latency_ms,
       round(100 * sum(pkt_lost) / nullif(sum(pkt_total), 0), 3) AS packet_loss_pct,
       round(sum(dl_volume_mb) / 1048576, 2) AS traffic_tb
FROM stg_kpi_hourly GROUP BY ALL ORDER BY day;
