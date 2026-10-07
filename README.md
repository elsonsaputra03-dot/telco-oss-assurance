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
| 02 | Fault management: alarm catalog per vendor and a labelled fault-scenario generator | ✅ v0.2 |
| 03 | Alarm correlation: topology- and time-based root cause, accuracy measured against the labels | ✅ v0.2 |
| 04 | Performance management: PM counters per cell per hour, KPI-only detection (sleeping cells, congestion) | ✅ v0.3 |
| 05 | Network KPI: drill-down network ► branch ► cluster ► site ► cell | ✅ v0.3 |
| 06 | Service impact: enterprise services on the network, downtime measured from KPIs, attributed to incidents, monthly SLA budget | ✅ v0.4 |
| 07 | Provisioning **simulation**: order ► feasibility ► reserve ► configure ► validate ► activate, capacity-aware | ✅ v0.4 |
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

## 02 Fault management

Seven days of alarms from labelled scenarios on the same network: transmission cuts, power outages (often at relay sites,
which also cut off the sites behind them), VSWR, sleeping cells, flapping microwave links, environment alarms and random
noise. The network has two vendors, ZTE and Ericsson (EID), each with its own alarm names and severities.

Alarm names follow naming found in **public references** (vendor alarm lists shared on document sites and telecom forums);
where no public name was found, a generic name is used and marked `name_source = generic`. All events are synthetic.

Every alarm carries the scenario it came from (`scenario_id`, `is_root`). The correlator never reads these columns; a test
scrambles them and checks that the result is unchanged. They are only used to measure accuracy.

## 03 Alarm correlation

Topology and time, the way a NOC engineer reads an alarm storm:

1. Merge repeats of the same alarm on the same object less than 15 minutes apart (flapping becomes one episode).
2. A site is down if **any** evidence says so (NE unreachable, RAN out of service, cells down).
3. Climb the transmission tree while the parent site is also down **and went down no later than the child** (4 minutes of
   clock-skew tolerance). The topmost down site is where the fault is; the sites below it are victims.
4. At the topmost site: a power alarm means **power**; a link alarm from the upstream end means **transport link**; neither
   means transport link **inferred from topology**.
5. Local alarms (VSWR with the cell degradation it causes, sleeping cells, environment) become their own incidents.

### Accuracy

Measured against the labels: a scenario counts as correct when most of its alarms land in one incident whose root type and
root object match.

| Scenario | Clean data | Hard data |
|---|---|---|
| Transmission cut | 40 / 40 | 40 / 40 |
| Power outage | 30 / 30 | 29 / 30 |
| Flapping link | 15 / 15 | 15 / 15 |
| Two cuts in the same subtree minutes apart | n/a | **27 / 38** |
| **All network faults** | **100%** | **90.2%** |

*Hard data* imitates a real NMS: 30% of upstream link alarms and 30% of mains alarms missing, 10% of NE-unreachable alarms
lost, up to ±3 minutes of clock skew per site, and 20 pairs of nested cuts a few minutes apart. On hard data 21,881 alarms
become 2,000 incidents; for transmission cuts with a reported link alarm, about 215 alarms collapse into one incident.

What the hard data found (both fixed, with regression tests):
- Using only the NE-unreachable alarm as outage evidence broke the climb whenever that alarm was lost at a relay site:
  12 of 40 cuts split into several incidents, and 85% were correct. Using any outage evidence brought it to 40 / 40.
- Ignoring the order of events merged nested cuts: a parent that went down after its child cannot have caused the child's
  outage. Requiring that order raised nested cuts from 47% to 71%.

**Known limit:** two nested cuts a few minutes apart, with clock skew of the same size, remain ambiguous (27 / 38). Telling
them apart needs more evidence than alarms alone, for example the timing of KPI drops (module 04).

## 04 Performance management

PM counters per cell per hour for the same seven days: 30,435 cells × 168 hours = **5.1 million rows** (generated with numpy in
about 2 seconds, 95 MB of Parquet). Like the files an OMC exports, these are counters, not finished KPIs: available seconds,
downlink volume and active time, RRC attempts and successes, E-RAB releases and drops, latency, packets and losses, PRB
utilisation, peak users.

The counters come from the **true impact** of each fault, not from the alarms. So a site whose outage alarm was lost still
shows zero availability, and a cell that stops carrying traffic without raising any alarm still shows up in its traffic.

Network level over the week (hard data): availability 99.15%, user throughput 17 Mbps, accessibility 99%, drop rate 0.3%,
latency 28 ms, packet loss 0.3%, about 4 PB of traffic (roughly 280 GB per site per day).

### Detection from KPIs alone

- **Sleeping cells**: available (≥ 3,500 of 3,600 seconds) but carrying less than 5% of that cell's normal traffic for the
  same hour of day (7-day median), for at least 3 consecutive hours (gaps-and-islands in SQL). Each finding is labelled
  `has_alarm` or silent. The hard data includes **30 sleeping cells that raise no alarm at all**.
- **Congestion**: PRB utilisation above 85% for at least 3 hours in a day. About 7% of cells hit this at least once in the week.

| Sleeping-cell detector (hard data) | Result |
|---|---|
| Precision (findings that are real sleeping cells) | 92 / 92 |
| Recall (sleeping episodes of 4 hours or more) | 79 / 79 |
| Silent sleeping cells found and labelled silent | **30 / 30** |

What checking the first result found:
- My evaluation first counted only sleeping episodes of 4+ hours as truth, so 13 correct findings of shorter episodes looked
  like false positives (precision 86%). Precision is now measured against all real sleeping cells.
- Two silent cells were labelled "has alarm" because a site-outage alarm on the same cell overlapped in time. An outage
  alarm explains a cell that is unavailable, not an available cell with no traffic, so only sleeping, degradation and VSWR
  alarms now count.
- The first PRB scale marked 26% of cells as congested, far more than a real network; it was recalibrated to about 7%.

## 05 Network KPI

`mart_kpi_daily` holds every level in one table using `GROUPING SETS`: network, branch, cluster, site and cell, per day and
technology (243,000 rows). Every KPI is a **ratio of sums** at its own level (for example availability = Σ available
seconds ÷ Σ seconds), never an average of averages; a test recomputes a branch KPI from the raw counters and expects the
same value.

## 06 Service impact

739 synthetic enterprise services (Enterprise Internet, IP VPN, Dedicated Backhaul; Gold 99.9%, Silver 99.5%, Bronze 99.0%)
ride on cell-site routers, so each service follows its site's transmission path to core.

- **Downtime is measured, not assumed**: per service, the unavailable seconds of its site in the hourly KPI counters
  (module 04). A test recomputes one service's downtime from the raw counters and expects the same value.
- **Attributed to correlated incidents** (module 03): an outage hour is linked to the network incident that covers the
  site at that time. Over 99.9% of service downtime is attributed; the rest stays visible as `unattributed_min`.
- **Incidents ranked by customer impact**, not by alarm count: service-minutes down, weighted 3/2/1 for Gold/Silver/Bronze.
  The top incident is a microwave link cut affecting 34 services, 6 of them Gold.
- **SLA against the monthly budget** (30 days: Gold 43 min, Silver 216 min, Bronze 432 min), because seven days of data
  cannot judge a monthly SLA. The first version judged 99.9% over a 7-day window, a 10-minute allowance, so almost every
  touched service "breached". Now `budget_used_pct` shows how much of the month this week consumed, and `sla_breached`
  means this week alone exceeded the month.

Result on the hard data: 51 of 146 Gold services were hit and **all 51** used up their monthly budget in this week, while
3 of 71 hit Bronze services did. Transmission outages last 20 minutes to 6 hours and every service has a single path, so
99.9% is not reachable without path redundancy, which is the design conclusion a real network would draw too.

## 07 Provisioning (simulation)

A **simulated** workflow, not a copy of any operator's provisioning system. 500 orders arrive over the week:
`RECEIVED ► FEASIBILITY_OK | REJECTED ► RESOURCE_RESERVED ► CONFIG_SENT ► VALIDATED ► ACTIVATED`, with up to three
validation attempts (config timeout, or the site being down at that moment per the true fault impacts) before the
reservation is released.

Feasibility checks **every link on the path to core**: link load = peak cellular backhaul of all sites behind it (from the
KPI counters) plus active enterprise services. Links are dimensioned to the smallest standard capacity at least 2.5x their
peak backhaul; 3% are deliberately tight (1.1x), like links waiting for an upgrade. A rejected order names the bottleneck
link, and `mart_capacity_bottlenecks` lists the links that rejected the most orders, i.e. upgrade candidates.

Calibration: 1.6x with 10% tight links rejected 49% of orders, because the average path has about 8 links and almost always
crosses a tight one; 2.5x with 3% rejects 22% (111 of 500). Tests check that no link is ever above capacity and that every
rejection names a link on that site's path.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m oss build          # data/raw/*.parquet, data/oss.duckdb, data/evaluation.json
.venv/bin/pytest -q
```

## License

MIT. Geography from public sources; all network data is synthetic.
