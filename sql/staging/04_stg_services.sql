-- Layanan korporat dan simulasi provisioning
CREATE OR REPLACE VIEW stg_services AS
SELECT service_id, customer_id, sector, product, site_id, bandwidth_mbps::INTEGER AS bandwidth_mbps, sla_tier, sla_pct,
       activated_at::TIMESTAMP AS activated_at
FROM read_parquet('{parquet}/services.parquet');

CREATE OR REPLACE VIEW stg_orders AS
SELECT order_id, service_id, customer_id, product, site_id, bandwidth_mbps::INTEGER AS bandwidth_mbps, sla_tier,
       received_at::TIMESTAMP AS received_at, completed_at::TIMESTAMP AS completed_at, status, fail_reason, bottleneck_link
FROM read_parquet('{parquet}/orders.parquet');

CREATE OR REPLACE VIEW stg_order_events AS
SELECT order_id, step, at::TIMESTAMP AS at, note FROM read_parquet('{parquet}/order_events.parquet');

CREATE OR REPLACE VIEW stg_link_capacity AS
SELECT link_id, capacity_mbps, used_mbps, round(100 * used_mbps / capacity_mbps, 1) AS util_pct
FROM read_parquet('{parquet}/link_capacity.parquet');
