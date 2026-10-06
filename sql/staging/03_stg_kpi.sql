-- Counter PM per sel per jam, diperkaya hierarki inventory (untuk drill-down)
CREATE OR REPLACE VIEW stg_kpi_hourly AS
SELECT k.*, c.ne_id, c.site_id, c.tech, s.branch, s.cluster, s.vendor
FROM read_parquet('{parquet}/kpi_hourly.parquet') k
JOIN stg_cells c USING (cell_id)
JOIN stg_sites s ON s.site_id = c.site_id;
