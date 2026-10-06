# Telco OSS Assurance Platform (synthetic)

An end-to-end OSS (Operations Support Systems) platform for a mobile network, built on **synthetic data**: the same 2,137
synthetic sites and 30,435 cells used by my [Network KPI Monitor](https://elsonsaputra03-dot.github.io/indo-realtime-monitor/network.html),
placed on public Kalimantan geography. No operator or vendor data is used.

```
Inventory & topology ──► Alarms / KPIs / config changes / orders ──► Parquet (raw) ──► DuckDB (staging ► marts) ──► dashboard
```

## Modules

| # | Module | Status |
|---|---|---|
| 01 | Network inventory: sites, network elements, cells, transmission topology | ✅ v0.1 |
| 02 | Fault management: alarm generator with labelled fault scenarios | planned |
| 03 | Alarm correlation: topology- and time-based root cause, accuracy measured against the labels | planned |
| 04 | Performance management: KPIs that react to the injected faults | planned |
| 05 | Network KPI: drill-down region ► site ► NE ► cell | planned |
| 06 | Service impact: customer services mapped onto the network | planned |
| 07 | Provisioning **simulation**: order ► reserve ► configure ► validate ► activate | planned |
| 08 | OSS data pipeline: Parquet ► DuckDB staging views ► mart tables | ✅ v0.1 |
| 09 | Operational dashboard | planned |

## 01 Inventory and transmission topology

| Table | Rows | Content |
|---|---|---|
| `sites` | 2,137 | location, regency, branch, cluster, vendor (ZTE / EID), site type, transmission role |
| `network_elements` | 6,457 | core routers (per branch), cell-site routers, BTS (2G), eNodeB (4G), gNodeB (5G) |
| `cells` | 30,435 | cell per NE, band, sector |
| `links` | 2,137 | one uplink per site: fiber (PoP and hubs) or microwave |

Topology per cluster, following common mobile backhaul design:
`CORE --fiber--> PoP --fiber--> HUB --microwave--> site --microwave--> site`. The PoP is the urban site closest to the
cluster centre; hubs are spread out (farthest-point sampling, about one per 10 sites); every other site joins the nearest
connected node with a **per-hop penalty**, so short chains are preferred. A plain nearest-node rule put 66% of sites at the
maximum of 3 microwave hops; with the penalty the split is about 40% one hop, 31% two hops and 20% three hops, with a median
microwave length of 7 km.

Because the topology is a tree, `mart_site_path` (recursive SQL) gives every site's path to core and `mart_link_impact`
the blast radius of every link: for example one PoP fiber carries 322 sites and 4,554 cells. Module 03 builds on this.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m oss build          # data/raw/*.parquet and data/oss.duckdb
.venv/bin/pytest -q
```

## License

MIT. Geography from public sources; all network data is synthetic.
