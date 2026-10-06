-- Staging: tipe data rapi + kunci yang konsisten, satu view per tabel mentah (Parquet)
CREATE OR REPLACE VIEW stg_sites AS
SELECT site_id, lat, lon, kab_code, kab, branch, cluster, vendor, urban, site_type, tx_role, tx_hub, mw_hops::INTEGER AS mw_hops
FROM read_parquet('{parquet}/sites.parquet');

CREATE OR REPLACE VIEW stg_network_elements AS
SELECT ne_id, site_id, ne_type, tech, vendor, branch, layer FROM read_parquet('{parquet}/network_elements.parquet');

CREATE OR REPLACE VIEW stg_cells AS
SELECT cell_id, ne_id, site_id, tech, band, sector::INTEGER AS sector, ci FROM read_parquet('{parquet}/cells.parquet');

CREATE OR REPLACE VIEW stg_links AS
SELECT link_id, a_end, b_end, link_type, capacity_mbps::INTEGER AS capacity_mbps, length_km
FROM read_parquet('{parquet}/links.parquet');
