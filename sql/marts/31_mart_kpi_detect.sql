-- Modul 04: deteksi dari KPI, termasuk masalah yang TIDAK memunculkan alarm.

-- Pola normal per sel per jam-dalam-hari: median 7 hari (median tahan terhadap hari yang terganggu)
CREATE OR REPLACE TABLE kpi_baseline AS
SELECT cell_id, hour(ts) AS hod, median(dl_volume_mb) AS base_mb
FROM stg_kpi_hourly GROUP BY ALL;

-- Sel tidur: sel AVAILABLE (>= 3500 detik dari 3600) tetapi trafiknya < 5% dari pola normal jam yang sama, minimal 3 jam
-- berturut-turut. Gaps-and-islands: nomor baris berurutan dikurangi jam -> konstan di dalam satu rentang berturut-turut.
CREATE OR REPLACE TABLE mart_sleeping_cells AS
WITH flagged AS (
    SELECT k.cell_id, k.site_id, k.tech, k.branch, k.ts
    FROM stg_kpi_hourly k JOIN kpi_baseline b ON b.cell_id = k.cell_id AND b.hod = hour(k.ts)
    WHERE k.avail_s >= 3500 AND b.base_mb >= 5 AND k.dl_volume_mb < 0.05 * b.base_mb
), islands AS (
    SELECT *, date_diff('hour', TIMESTAMP '2000-01-01', ts) - row_number() OVER (PARTITION BY cell_id ORDER BY ts) AS grp
    FROM flagged
), runs AS (
    SELECT cell_id, any_value(site_id) AS site_id, any_value(tech) AS tech, any_value(branch) AS branch,
           min(ts) AS started_at, max(ts) + INTERVAL 1 HOUR AS ended_at, count(*) AS hours
    FROM islands GROUP BY cell_id, grp HAVING count(*) >= 3
)
SELECT r.*,
       -- ada alarm yang MENJELASKAN sel tidur (sleeping / degradasi / VSWR) pada sel ini? jika tidak: masalah SENYAP.
       -- Alarm sel mati karena site terputus tidak dihitung: itu menjelaskan sel tidak available, bukan sel available
       -- tanpa trafik (versi awal ikut menghitungnya dan salah melabeli 2 dari 30 sel tidur senyap).
       EXISTS (SELECT 1 FROM stg_alarms a WHERE a.object = r.cell_id AND a.symptom IN ('cell_sleep', 'cell_degrade', 'vswr')
               AND a.raised_at < r.ended_at + INTERVAL 30 MINUTE AND a.cleared_at > r.started_at - INTERVAL 30 MINUTE) AS has_alarm
FROM runs r ORDER BY started_at;

-- Kongesti: utilisasi PRB > 85% minimal 3 jam dalam sehari (tidak memunculkan alarm, hanya terlihat dari KPI)
CREATE OR REPLACE TABLE mart_congestion AS
SELECT cell_id, any_value(site_id) AS site_id, any_value(tech) AS tech, any_value(branch) AS branch, ts::DATE AS day,
       count(*) FILTER (WHERE prb_used_pct > 85) AS hours_congested,
       round(max(prb_used_pct), 1) AS prb_peak_pct,
       round(sum(dl_volume_mb) * 8 / nullif(sum(dl_active_s), 0), 2) AS user_thr_mbps
FROM stg_kpi_hourly GROUP BY cell_id, ts::DATE
HAVING count(*) FILTER (WHERE prb_used_pct > 85) >= 3 ORDER BY hours_congested DESC;
