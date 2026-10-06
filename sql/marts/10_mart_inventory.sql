-- Ringkasan inventory per branch, vendor, teknologi
CREATE OR REPLACE TABLE mart_inventory_summary AS
SELECT s.branch, s.vendor, ne.tech,
       count(DISTINCT s.site_id) AS sites, count(DISTINCT ne.ne_id) AS network_elements, count(c.cell_id) AS cells
FROM stg_sites s
JOIN stg_network_elements ne ON ne.site_id = s.site_id AND ne.layer = 'ran'
LEFT JOIN stg_cells c ON c.ne_id = ne.ne_id
GROUP BY ALL ORDER BY s.branch, ne.tech;

-- Jalur setiap site ke core (recursive CTE). Dasar korelasi alarm: putusnya satu link memutus semua site di bawahnya.
CREATE OR REPLACE TABLE mart_site_path AS
WITH RECURSIVE up(site_id, node, hop) AS (
    SELECT site_id, site_id, 0 FROM stg_sites
    UNION ALL
    SELECT up.site_id, l.a_end, up.hop + 1 FROM up JOIN stg_links l ON l.b_end = up.node
)
SELECT site_id, node, hop FROM up;

-- Dampak per link: berapa site & sel ikut terputus bila link ini putus (ukuran "blast radius")
CREATE OR REPLACE TABLE mart_link_impact AS
SELECT l.link_id, l.a_end, l.b_end, l.link_type, l.length_km,
       count(DISTINCT p.site_id) AS sites_downstream,
       (SELECT count(*) FROM stg_cells c WHERE c.site_id IN (SELECT p2.site_id FROM mart_site_path p2 WHERE p2.node = l.b_end)) AS cells_downstream
FROM stg_links l JOIN mart_site_path p ON p.node = l.b_end
GROUP BY ALL ORDER BY sites_downstream DESC;
