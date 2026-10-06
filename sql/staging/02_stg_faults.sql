-- Staging fault management. Kolom label (scenario_*, is_root) hanya untuk evaluasi; korelator tidak memakainya.
CREATE OR REPLACE VIEW stg_alarms AS
SELECT alarm_id, ne_id, site_id, vendor, symptom, alarm_name, severity, alarm_type, name_source, object,
       raised_at::TIMESTAMP AS raised_at, cleared_at::TIMESTAMP AS cleared_at,
       date_diff('second', raised_at::TIMESTAMP, cleared_at::TIMESTAMP) AS duration_s,
       scenario_id, scenario_type, is_root
FROM read_parquet('{parquet}/alarms.parquet');

CREATE OR REPLACE VIEW stg_incidents AS
SELECT incident_id, root_type, root_object, evidence, top_site, start::TIMESTAMP AS started_at, "end"::TIMESTAMP AS ended_at,
       sites_affected::INTEGER AS sites_affected, alarm_count::INTEGER AS alarm_count
FROM read_parquet('{parquet}/incidents.parquet');

CREATE OR REPLACE VIEW stg_incident_alarms AS SELECT incident_id, alarm_id FROM read_parquet('{parquet}/incident_alarms.parquet');
