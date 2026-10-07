-- Modul 06: dampak ke pelanggan. Downtime DIUKUR dari KPI (detik sel tidak available di site layanan), lalu
-- DIATRIBUSIKAN ke insiden hasil korelasi (modul 03) yang mencakup site itu pada jam yang sama.

-- Availability per site per jam: rata-rata detik available sel-sel site itu
CREATE OR REPLACE TABLE site_hourly_avail AS
SELECT site_id, ts, avg(avail_s) AS avail_s FROM stg_kpi_hourly GROUP BY ALL;

-- Site yang tercakup setiap insiden jaringan (dari alarm anggotanya)
CREATE OR REPLACE TABLE incident_sites AS
SELECT DISTINCT i.incident_id, i.root_type, i.root_object, a.site_id, i.started_at, i.ended_at
FROM stg_incidents i JOIN stg_incident_alarms ia USING (incident_id) JOIN stg_alarms a USING (alarm_id)
WHERE i.root_type IN ('transport_link', 'power');

-- Jam layanan terputus (sebagian atau penuh), dengan insiden penyebabnya bila ada
CREATE OR REPLACE TABLE service_outage_hours AS
SELECT s.service_id, h.ts, (3600 - h.avail_s) / 60.0 AS down_min,
       arg_min(x.incident_id, x.started_at) AS incident_id
FROM stg_services s
JOIN site_hourly_avail h ON h.site_id = s.site_id AND h.avail_s < 3600 AND h.ts >= date_trunc('hour', s.activated_at)
LEFT JOIN incident_sites x ON x.site_id = s.site_id
     AND x.started_at < h.ts + INTERVAL 1 HOUR AND x.ended_at + INTERVAL 15 MINUTE > h.ts
GROUP BY ALL;

-- SLA per layanan untuk minggu ini (layanan baru dihitung sejak jam aktivasi)
CREATE OR REPLACE TABLE mart_service_sla AS
WITH w AS (SELECT min(ts) AS t0, max(ts) + INTERVAL 1 HOUR AS t1 FROM stg_kpi_hourly),
svc AS (
    SELECT s.*, st.branch, date_diff('second', greatest(date_trunc('hour', s.activated_at), w.t0), w.t1) / 60.0 AS active_min
    FROM stg_services s CROSS JOIN w JOIN stg_sites st ON st.site_id = s.site_id WHERE s.activated_at < w.t1
),
dn AS (
    SELECT service_id, sum(down_min) AS down_min, count(DISTINCT incident_id) AS incidents,
           string_agg(DISTINCT incident_id, ', ') AS incident_ids,
           coalesce(sum(down_min) FILTER (WHERE incident_id IS NULL), 0) AS unattributed_min
    FROM service_outage_hours GROUP BY service_id
)
SELECT svc.service_id, customer_id, sector, product, site_id, branch, bandwidth_mbps, sla_tier, sla_pct,
       round(active_min) AS active_min, round(coalesce(dn.down_min, 0)) AS down_min,
       round(100 * (1 - coalesce(dn.down_min, 0) / active_min), 3) AS availability_pct,
       coalesce(dn.incidents, 0) AS incidents, dn.incident_ids, round(coalesce(dn.unattributed_min, 0)) AS unattributed_min
FROM svc LEFT JOIN dn USING (service_id);
-- SLA kontrak dihitung per BULAN (30 hari). Data hanya 7 hari, jadi yang dinilai: berapa persen jatah downtime sebulan
-- yang sudah habis minggu ini; "breached" = downtime minggu ini saja sudah melampaui jatah sebulan. (Versi awal menilai
-- 99,9% terhadap jendela 7 hari, yaitu jatah 10 menit, sehingga hampir semua layanan yang tersentuh gangguan "melanggar".)
ALTER TABLE mart_service_sla ADD COLUMN sla_budget_month_min DOUBLE;
ALTER TABLE mart_service_sla ADD COLUMN budget_used_pct DOUBLE;
ALTER TABLE mart_service_sla ADD COLUMN sla_breached BOOLEAN;
UPDATE mart_service_sla SET sla_budget_month_min = round((100 - sla_pct) / 100 * 43200, 1);
UPDATE mart_service_sla SET budget_used_pct = round(100 * down_min / sla_budget_month_min, 1),
                            sla_breached = down_min > sla_budget_month_min;

-- Insiden diurutkan menurut dampak ke pelanggan (bukan jumlah alarm): Gold dihitung 3x, Silver 2x, Bronze 1x
CREATE OR REPLACE TABLE mart_incident_customer_impact AS
SELECT o.incident_id, any_value(x.root_type) AS root_type, any_value(x.root_object) AS root_object,
       count(DISTINCT o.service_id) AS services, count(DISTINCT s.customer_id) AS customers,
       count(DISTINCT o.service_id) FILTER (WHERE s.sla_tier = 'Gold') AS gold_services,
       round(sum(o.down_min)) AS service_down_min,
       round(sum(o.down_min * CASE s.sla_tier WHEN 'Gold' THEN 3 WHEN 'Silver' THEN 2 ELSE 1 END)) AS weighted_impact
FROM service_outage_hours o JOIN stg_services s USING (service_id)
JOIN (SELECT DISTINCT incident_id, root_type, root_object FROM incident_sites) x USING (incident_id)
GROUP BY o.incident_id ORDER BY weighted_impact DESC;
