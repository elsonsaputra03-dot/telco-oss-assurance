-- Modul 07: hasil simulasi provisioning
CREATE OR REPLACE TABLE mart_order_funnel AS
SELECT step, count(DISTINCT order_id) AS orders FROM stg_order_events GROUP BY step
ORDER BY CASE step WHEN 'RECEIVED' THEN 1 WHEN 'FEASIBILITY_OK' THEN 2 WHEN 'REJECTED' THEN 2 WHEN 'RESOURCE_RESERVED' THEN 3
              WHEN 'CONFIG_SENT' THEN 4 WHEN 'VALIDATION_FAILED' THEN 5 WHEN 'RETRY' THEN 5 WHEN 'VALIDATED' THEN 6
              WHEN 'ACTIVATED' THEN 7 ELSE 8 END;

CREATE OR REPLACE TABLE mart_order_summary AS
SELECT product, status, fail_reason, count(*) AS orders,
       round(median(date_diff('minute', received_at, completed_at)) / 60.0, 1) AS median_hours
FROM stg_orders GROUP BY ALL ORDER BY product, orders DESC;

-- Link yang paling sering menolak order: kandidat upgrade kapasitas
CREATE OR REPLACE TABLE mart_capacity_bottlenecks AS
SELECT o.bottleneck_link AS link_id, l.link_type, l.a_end, l.b_end, c.capacity_mbps, c.used_mbps, c.util_pct,
       count(*) AS rejected_orders, sum(o.bandwidth_mbps) AS rejected_mbps
FROM stg_orders o JOIN stg_links l ON l.link_id = o.bottleneck_link JOIN stg_link_capacity c USING (link_id)
WHERE o.status = 'REJECTED' GROUP BY ALL ORDER BY rejected_orders DESC;
