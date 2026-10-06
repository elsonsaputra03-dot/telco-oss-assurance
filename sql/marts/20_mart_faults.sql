-- Ringkasan alarm per hari, vendor, severity, nama alarm
CREATE OR REPLACE TABLE mart_alarm_daily AS
SELECT raised_at::DATE AS day, vendor, severity, alarm_name, count(*) AS alarms, round(avg(duration_s) / 60, 1) AS avg_minutes
FROM stg_alarms GROUP BY ALL ORDER BY day, alarms DESC;

-- Insiden gangguan jaringan (transmisi & catu daya) dengan dampak: inilah daftar kerja NOC setelah korelasi
CREATE OR REPLACE TABLE mart_network_incidents AS
SELECT i.incident_id, i.root_type, i.root_object, i.evidence, i.top_site, s.branch, s.cluster, s.vendor,
       i.started_at, i.ended_at, round(date_diff('second', i.started_at, i.ended_at) / 60.0) AS minutes,
       i.sites_affected, i.alarm_count,
       (SELECT count(*) FROM stg_incident_alarms ia JOIN stg_alarms a USING (alarm_id)
        WHERE ia.incident_id = i.incident_id AND a.symptom = 'cell_down') AS cell_alarms
FROM stg_incidents i LEFT JOIN stg_sites s ON s.site_id = i.top_site
WHERE i.root_type IN ('transport_link', 'power')
ORDER BY i.alarm_count DESC;

-- Kompresi alarm -> insiden per jenis akar masalah
CREATE OR REPLACE TABLE mart_correlation_summary AS
SELECT root_type, evidence, count(*) AS incidents, sum(alarm_count) AS alarms,
       round(sum(alarm_count) / count(*), 1) AS alarms_per_incident
FROM stg_incidents GROUP BY ALL ORDER BY alarms DESC;
