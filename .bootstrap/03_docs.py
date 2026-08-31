from __future__ import annotations

import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(content).lstrip("\n").rstrip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: str, value: object) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


# Correct two subtle state-machine edges in the generated simulation source.
simulation = ROOT / "src/service_ops_lab/simulation.py"
text = simulation.read_text(encoding="utf-8")
text = text.replace(
    'wait = (assignment.job.start_slot or assignment.job.arrival_slot) - assignment.job.arrival_slot',
    'wait = (assignment.job.start_slot if assignment.job.start_slot is not None else assignment.job.arrival_slot) - assignment.job.arrival_slot',
)
text = text.replace(
    'if (assignment.job.start_slot or absolute_slot) <= assignment.job.due_slot:',
    'if (assignment.job.start_slot if assignment.job.start_slot is not None else absolute_slot) <= assignment.job.due_slot:',
)
old = '''                unit = available_unit(equipment_units, job.equipment, absolute_slot)
                if unit is None or unit.unit_id in busy_equipment:
                    continue
'''
new = '''                unit = next(
                    (
                        candidate
                        for candidate in sorted(equipment_units, key=lambda item: item.unit_id)
                        if candidate.equipment_type == job.equipment
                        and candidate.down_until_slot <= absolute_slot
                        and candidate.unit_id not in busy_equipment
                    ),
                    None,
                )
                if unit is None:
                    continue
'''
if old not in text:
    raise SystemExit("expected equipment assignment block not found")
text = text.replace(old, new)
simulation.write_text(text, encoding="utf-8", newline="\n")

write("pyproject.toml", '''
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "service-operations-decision-lab"
version = "0.1.0"
description = "Synthetic integrated decision laboratory for demand, queueing, workforce, maintenance, inventory, quality and service risk."
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}
authors = [{name = "JINGJAYHUANG"}]
keywords = ["service-operations", "queueing", "forecasting", "workforce", "inventory", "maintenance", "quality", "simulation"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Scientific/Engineering :: Information Analysis",
]

[project.scripts]
sodl = "service_ops_lab.cli:main"

[project.urls]
Repository = "https://github.com/JINGJAYHUANG/service-operations-decision-lab"
Issues = "https://github.com/JINGJAYHUANG/service-operations-decision-lab/issues"

[tool.setuptools]
package-dir = {"" = "src"}
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
service_ops_lab = ["data/*.json"]
''')

write("MANIFEST.in", '''
include README.md LICENSE SECURITY.md CHANGELOG.md
recursive-include src/service_ops_lab/data *.json
recursive-include examples *.json *.csv *.md *.html
recursive-include schemas *.json
recursive-include docs *.md
''')

write(".gitignore", '''
__pycache__/
*.py[cod]
.venv/
venv/
build/
dist/
*.egg-info/
.pytest_cache/
.coverage
out/
.DS_Store
''')

write("LICENSE", '''
MIT License

Copyright (c) 2026 JINGJAYHUANG

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
''')

write("CITATION.cff", '''
cff-version: 1.2.0
message: "If this synthetic service-operations laboratory supports your work, cite the repository."
title: "Service Operations Decision Lab"
type: software
authors:
  - family-names: "Huang"
    given-names: "Jingjie"
repository-code: "https://github.com/JINGJAYHUANG/service-operations-decision-lab"
url: "https://github.com/JINGJAYHUANG/service-operations-decision-lab"
version: "0.1.0"
date-released: "2026-08-31"
license: MIT
''')

write("README.md", '''
# Service Operations Decision Lab

[![CI](https://github.com/JINGJAYHUANG/service-operations-decision-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/JINGJAYHUANG/service-operations-decision-lab/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/JINGJAYHUANG/service-operations-decision-lab)](https://github.com/JINGJAYHUANG/service-operations-decision-lab/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%E2%80%933.13-blue.svg)](pyproject.toml)

A fully synthetic, evidence-first laboratory for making **integrated service-operations decisions** across demand forecasting, appointments and walk-ins, queueing, workforce flexibility, equipment reliability, spare-parts inventory, first-time-right quality, revisits, service-level constraints and tail risk.

The package searches a finite, transparent policy grid and reports whether a policy is feasible, least-violating, or dominated. It does **not** claim to solve a real business, recover a proprietary course case, or prove global optimality.

**Status:** `v0.1.0` · synthetic reference implementation · production assumptions not certified.

[中文说明](docs/README.zh-CN.md) · [Architecture](docs/architecture.md) · [Methodology](docs/methodology.md) · [Threat model](docs/threat-model.md)

## Why this project exists

Service operations are often analyzed in disconnected spreadsheets:

```text
forecast demand
staff the schedule
manage the queue
order parts
maintain equipment
inspect quality
explain customer outcomes
```

Each local decision changes the others. More inventory can reduce stockouts but increase working capital. More overtime can reduce waiting but increase fatigue and cost. Deferred maintenance can create short-term capacity and long-tail failure risk. Faster service can reduce the queue while lowering first-time-right performance and generating revisits.

This project therefore evaluates one policy through a shared operating model:

```text
synthetic demand history
        ↓
rolling-origin model selection
        ↓
common random arrivals and service requirements
        ↓
appointments + walk-ins + no-shows + abandonment
        ↓
skill-constrained staff + flex + overtime
        ↓
equipment preventive maintenance + random failures
        ↓
lead-time inventory + reorder policy + stockout blocking
        ↓
quality program + first-time-right + synthetic revisits
        ↓
service, waiting, fairness, reliability, inventory and cost metrics
        ↓
expected value + worst case + weighted CVaR + Pareto frontier
```

## Five-minute start

The runtime uses only the Python standard library.

```bash
python -m pip install --no-deps -e .

sodl validate --case examples/cases/northstar-service-hub.json
sodl optimize \
  --case examples/cases/northstar-service-hub.json \
  --output-dir out/decision
sodl audit --directory out/decision
```

For a fast smoke test:

```bash
sodl self-test --output-dir out/self-test
```

## The synthetic operating system

The public case contains:

| Surface | Synthetic fixture |
|---|---:|
| Planning horizon | 21 operating days |
| Demand history | 56 days |
| Service types | 3 |
| Staff members | 5 |
| Equipment types | 2 |
| Spare-parts SKUs | 4 |
| Probability-weighted scenarios | 5 |
| Deterministic stress cases | 8 |
| Candidate operating policies | 288 |
| Simulation replications | 2 per scenario and policy |

The fictional service types are `preventive-care`, `diagnostic-repair`, and `urgent-restoration`. They are generic operating archetypes, not customer records or descriptions of a real company.

## Seven policy levers

The finite policy grid varies:

1. demand buffer;
2. flexible staff activation;
3. overtime slots;
4. inventory cover days;
5. preventive-maintenance interval;
6. quality-program level;
7. queue priority rule (`fifo`, `sla`, or `shortest`).

The complete grid is intentionally enumerable:

```text
3 × 2 × 2 × 2 × 2 × 2 × 3 = 288 policies
```

A finite search supports auditability. It is not a mathematical proof that no better policy exists outside the declared grid.

## Nonanticipative scenario evaluation

One policy is selected before the future scenario is known, then replayed unchanged across:

- baseline;
- demand surge;
- slow service;
- supply disruption;
- compound downside.

The planner never creates a different hindsight-perfect policy for each scenario.

## Hard targets

A policy may be required to satisfy:

- expected completion;
- worst-scenario completion;
- expected SLA attainment;
- first-time-right quality;
- maximum abandonment;
- maximum stockout blocking;
- maximum P90 wait;
- service-type completion floors.

If no policy passes every target, the engine returns `least-violating-no-feasible-policy`. It does not silently delete a constraint or label the result optimal.

## Forecasting discipline

Four transparent models compete through rolling-origin validation:

- seasonal naive;
- seven-day moving average;
- damped trend;
- weekday profile.

Selection uses WAPE plus a bias penalty. The chosen model also carries MAE, bias and residual standard deviation. Forecast selection is performed once from the pre-horizon synthetic history; operating policies do not receive future observations.

## Queueing and workforce

The discrete-time simulation includes:

- scheduled and walk-in arrivals;
- synthetic no-shows;
- service-specific patience and abandonment;
- service-level due times;
- skill-constrained staff;
- absences;
- optional flexible generalist capacity;
- overtime;
- FIFO, SLA-first and shortest-processing-time dispatch;
- full-duration staff and equipment reservation.

Finite-horizon WIP and Little's Law diagnostics are labeled as diagnostics, not steady-state queueing certification.

## Reliability, inventory and quality

Equipment units have preventive-maintenance intervals, maintenance downtime, failure probabilities and repair durations. Inventory uses lead times, pack sizes, reorder points and policy-dependent cover days. A job cannot start without required parts.

Completed jobs pass through a first-time-right model. Quality-program investment can improve FTR; failures create synthetic revisits inside the horizon. This makes quality a flow variable rather than a decorative KPI.

## Risk and selection

For every policy, the planner calculates:

- expected metrics;
- worst modeled metrics;
- expected service-type completion;
- worst service-type completion;
- probability-weighted upper-tail CVaR cost;
- normalized constraint violation;
- a Pareto frontier over cost, worst completion, P90 wait and FTR.

Eight deterministic stress cases then challenge the selected policy. Stress cases are sensitivity tests, not probability forecasts.

## Conservation laws

Every simulation enforces:

```text
generated jobs = completed + abandoned + ending backlog
opening inventory + receipts = consumption + ending inventory
```

A run that violates either identity raises an error rather than producing a report.

## Outputs

`optimize` writes:

```text
plan.json
stress.json
explanation.json
forecast.json
decision-report.md
decision-lab.html
policy-catalog.csv
scenario-results.csv
stress-results.csv
artifact-manifest.json
```

The static HTML uses no JavaScript or remote runtime asset. CSV values beginning with spreadsheet formula prefixes are neutralized.

## Public boundary

The repository contains no original coursework, instructor material, real company, customer, worker, demand, queue, quality, maintenance, inventory, financial or scheduling record. All values were created for this public reference implementation.

The project does not make claims about:

- a real service business;
- real customer satisfaction;
- real staffing requirements;
- real equipment reliability;
- real demand or cost;
- causal improvement;
- production fitness;
- global optimality.

See [public-boundary.md](docs/public-boundary.md) and [limitations.md](docs/limitations.md).

## Verification

```bash
PYTHONPATH=src python tools/release_check.py
```

The release gate compiles source, validates the case, runs the test suite, checks deterministic generated artifacts, audits the static HTML, verifies schemas, documentation, workflows, version synchronization, origin disclosure and the public boundary.

## License

MIT. See [LICENSE](LICENSE).
''')

write("docs/README.zh-CN.md", '''
# 服务运营决策实验室｜中文说明

这是一个全合成、可运行、可审计的服务运营决策实验室。它把需求预测、预约与到店、排队、人员技能、弹性用工、加班、设备维护、备件库存、首次解决率、重访返工、服务水平和尾部风险放进同一套模型。

它不是旧课程案例的公开版，也不包含真实企业、顾客、员工、成本或运营记录。

## 核心决策

系统不是分别回答“需要多少人”“应该备多少货”，而是联合回答：

> 在需求、服务时间、缺勤、设备故障、备件提前期和质量均不确定时，哪一套人员、库存、维护、质量与排队策略，能够在可接受成本下满足声明的服务约束？

## 三种结果

- `feasible-selected`：在288个公开候选策略中找到满足全部硬约束的方案；
- `least-violating-no-feasible-policy`：没有方案全部达标，系统明确选择约束缺口最小者；
- 失败：模型守恒、数据合同或生成物完整性被破坏，停止出报告。

## 为什么不能只看平均值

系统同时报告：

- 期望完成率；
- 最差情景完成率；
- 各服务类型完成率；
- SLA；
- 首次解决率；
- 放弃率；
- 缺件阻断率；
- P90等待；
- 期望成本；
- 上尾CVaR成本；
- 八组压力测试。

平均表现良好但某类服务持续被挤压，不会被包装为整体优秀。

## 运行

```bash
python -m pip install --no-deps -e .

sodl validate --case examples/cases/northstar-service-hub.json
sodl optimize \
  --case examples/cases/northstar-service-hub.json \
  --output-dir out/decision
```

## 公共边界

仓库明确排除：原课程文本、真实公司名称、真实顾客或员工、个人资料、真实需求和成本、真实排班、真实设备故障、真实库存、真实质量表现以及任何企业改善比例。

测试通过只能证明这套合成软件按定义运行，不能证明真实企业使用后一定改善，也不能替代现场数据校准、劳动规则、客户承诺和管理判断。
''')

write("docs/architecture.md", '''
# Architecture

```text
case contract
    ├── history and services
    ├── staff and skills
    ├── equipment and reliability
    ├── inventory and lead times
    ├── scenarios and targets
    └── finite policy grid
            ↓
rolling-origin forecasting
            ↓
common-random-number scenario simulation
    ├── arrivals / appointments / no-shows
    ├── queue / abandonment / SLA
    ├── staff / flex / overtime
    ├── maintenance / failure / repair
    ├── parts / reorder / stockout
    └── FTR / quality / revisit
            ↓
policy aggregation
    ├── expected metrics
    ├── worst metrics
    ├── CVaR
    ├── hard constraints
    └── Pareto frontier
            ↓
selected policy + stress envelope + explanation
            ↓
JSON / CSV / Markdown / static HTML / SHA-256 manifest
```

The simulation accepts one policy and one scenario. Optimization owns the Cartesian policy grid and replays each policy across the same scenario definitions and replication seeds. Reporting is downstream and cannot change a decision.
''')

write("docs/methodology.md", '''
# Methodology

## Decision first

The model begins with a declared decision horizon, operating resources, service types, hard targets and policy levers. It does not begin by choosing a favorite scheduling rule and then designing metrics that make it look good.

## Forecast before policy replay

Forecast models are selected with rolling-origin backtests on pre-horizon observations. Scenario multipliers then represent uncertainty around the forecast. Future scenario identity is never used to choose a different policy.

## Common random numbers

Policies evaluated within the same scenario and replication use stable random seeds derived from case, scenario and replication identifiers. This reduces comparison noise without implying that the synthetic random process is true for a real operation.

## Feasible first

The selection hierarchy is:

1. satisfy declared hard constraints;
2. minimize expected cost plus a CVaR penalty;
3. use waiting time and policy ID as deterministic tie-breakers.

If the feasible set is empty, normalized violation is minimized before the risk-adjusted objective. The output remains explicitly infeasible.

## Human intervention

The model should diagnose trade-offs, binding constraints and stress sensitivity. A manager still decides whether overtime, flex staffing, inventory, due-date changes or service segmentation are acceptable. Mathematical feasibility is not organizational authority.
''')

write("docs/forecasting.md", '''
# Forecasting

The public reference includes four intentionally transparent models. Rolling-origin validation starts after 21 observations and scores every one-step forecast with WAPE, MAE, bias and residual standard deviation.

Selection loss is:

```text
WAPE + 0.20 × absolute normalized bias
```

The residual standard deviation constructs illustrative P80 and P95 paths. These paths are not calibrated prediction intervals for a real operation.

A production adaptation should add:

- explicit calendar and event effects;
- forecast horizon-specific validation;
- interval coverage tests;
- drift detection;
- a policy for missing and revised observations;
- rolling out-of-sample monitoring.
''')

write("docs/queueing-and-workforce.md", '''
# Queueing and workforce

Jobs arrive into a finite-horizon discrete-time queue. Appointment share, no-shows, walk-in arrival time, service duration, patience, SLA and service priority are service-specific.

Staff are eligible only when:

- present;
- skilled for the service;
- not already assigned;
- able to finish the job inside their daily and overtime availability.

Equipment is reserved for the complete service duration. Flexible capacity is a synthetic generalist activated only when buffered expected workload exceeds a threshold.

Priority rules are visible and deterministic:

- FIFO;
- earliest SLA due time;
- shortest processing time.

Service-type metrics prevent aggregate performance from hiding systematic degradation in urgent or complex work.
''')

write("docs/inventory-maintenance-quality.md", '''
# Inventory, maintenance and quality

## Inventory

Each SKU has initial stock, reorder point, lead time, pack size, purchase cost, order cost and daily holding cost. Policy-level cover days change the order-up-to target. Supply disruption shifts lead time. Jobs remain blocked when required parts are unavailable.

## Maintenance

Each equipment unit tracks preventive maintenance, downtime, stochastic failure and repair. Shorter PM intervals consume planned capacity but can reduce exposure to accumulated operating risk in richer future models. The current failure probability is synthetic and memoryless between PM events.

## Quality

First-time-right is service-specific and modified by scenario quality drift and the selected quality-program level. A quality failure can generate a synthetic revisit after a service-specific delay. This links quality to future demand, workload and cost.

Presence of a quality program is not evidence of causal real-world improvement. Production use requires measurement-system validation, case-mix controls and outcome review.
''')

write("docs/risk-and-selection.md", '''
# Risk and selection

Expected value alone can hide a brittle operating policy. The planner therefore reports worst modeled metrics and probability-weighted upper-tail CVaR cost.

For costs \(C_s\) and scenario probabilities \(p_s\), CVaR at level \(\alpha\) averages the worst \(1-\alpha\) probability mass. It is calculated from the finite declared scenario distribution, not an estimated real loss distribution.

The Pareto frontier considers:

- lower expected cost;
- higher worst completion;
- lower expected P90 wait;
- higher expected FTR.

A frontier point is non-dominated only within the evaluated finite grid. It is not globally optimal.
''')

write("docs/conservation-and-diagnostics.md", '''
# Conservation and diagnostics

## Job flow

```text
generated primary jobs + generated revisits
= completed + abandoned + ending backlog
```

No-show appointments are recorded before a job enters the service queue and therefore are not included in generated queue jobs.

## Inventory

For every SKU:

```text
opening + receipts = consumption + ending
```

Shortage units are diagnostic unmet requirements, not negative inventory.

## WIP and Little's Law

The report includes average ending backlog, throughput per day and a queue-wait-based implied WIP. Because the run is finite, starts empty and may end with backlog, these values are diagnostics—not proof of steady-state Little's Law equality.
''')

write("docs/interpreting-results.md", '''
# Interpreting results

Read results in this order:

1. selection status;
2. hard-constraint violations;
3. service-type completion floors;
4. worst scenario;
5. stress envelope;
6. queue, inventory, reliability and quality traces;
7. expected cost and CVaR;
8. Pareto alternatives.

Do not lead with the objective value. A low-cost policy can be unacceptable if it creates abandonment, service inequity, stockouts or fragile downside performance.

Recommended language:

> Within the declared synthetic policy grid and scenario set, this policy met the stated constraints and had the lowest risk-adjusted objective among feasible candidates.

Avoid:

> The model proved the optimal staffing and inventory policy for the business.
''')

write("docs/threat-model.md", '''
# Threat model

## Protected decisions

- service commitments;
- staffing and overtime;
- queue priority;
- maintenance timing;
- inventory orders;
- quality investment;
- claims about customer and financial outcomes.

## Threats and controls

| Threat | Control |
|---|---|
| Proprietary coursework leakage | complete synthetic reconstruction and public audit |
| Personal/customer/employee data exposure | synthetic-only case contract and pattern scan |
| Hindsight policy selection | one policy replayed across all future scenarios |
| Mean-performance masking | worst metrics, service-type floors and stress cases |
| False optimality | finite-grid and no-global-optimality labels |
| Broken simulation accounting | job-flow and inventory conservation checks |
| Spreadsheet injection | CSV formula-prefix neutralization |
| Unsafe generated HTML | escaping, no scripts and no remote runtime assets |
| Generated-output tampering | deterministic rebuild and SHA-256 manifest |
| Stale assumptions | absolute as-of date and required recalibration guidance |

## Residual risk

The software cannot establish that its synthetic distributions, cost weights, SLA targets or quality relationships correspond to a real operation. A user can also supply misleading inputs. Production use requires owned data, legal and labor review, operational calibration and human approval.
''')

write("docs/data-dictionary.md", '''
# Data dictionary

## Case

- `history`: daily service demand before the planning horizon.
- `service_types`: skill, equipment, parts, duration, SLA, patience, no-show and FTR contracts.
- `staff`: skills, daily slots, absence probability and synthetic slot cost.
- `equipment`: units, PM, failure, repair and synthetic cost.
- `inventory`: stock, reorder point, lead time, pack size and synthetic cost.
- `scenarios`: probability-weighted demand, time, absence, failure, lead-time and quality shifts.
- `policy_grid`: exact policy choices the optimizer may enumerate.
- `targets`: hard aggregate and service-type constraints.
- `stress_cases`: deterministic overrides applied after selection.

## Result

- `expected_metrics`: probability-weighted scenario metrics.
- `worst_metrics`: minimum benefit or maximum burden across scenarios.
- `violation_score`: sum of target-relative hard-constraint gaps.
- `objective`: expected cost plus risk-aversion times CVaR cost.
- `pareto_frontier`: non-dominated candidates inside the finite grid.
''')

write("docs/public-boundary.md", '''
# Public boundary

The original academic experience is represented only at the level of broad operations topics. This repository does not reproduce the old case, course prompt, solution, business identity, narrative, tables, instructor language or claimed performance improvement.

All public values, names, dates and relationships are newly generated synthetic fixtures.

Excluded:

- real company, customer or employee records;
- personal identifiers or recommendation letters;
- course files or copyrighted case text;
- real demand, queue, service-time, quality or satisfaction data;
- real equipment, maintenance or inventory records;
- real wages, revenue, cost or profit;
- production recommendations.
''')

write("docs/limitations.md", '''
# Limitations

The current model is a transparent educational and engineering reference. It does not include:

- customer classes, geography or travel routing;
- labor law, breaks, shift preferences or fatigue dynamics;
- sequence-dependent setups;
- a calibrated survival model for equipment;
- multi-echelon inventory;
- appointment rescheduling or overbooking optimization;
- causal quality estimation;
- a formal MIP or global optimization bound;
- real-time recourse after observing demand;
- production data calibration.

The software can validate its own deterministic behavior and accounting identities. It cannot validate real-world assumptions that have not been supplied and independently reviewed.
''')

write("SECURITY.md", '''
# Security policy

Report software vulnerabilities through GitHub private vulnerability reporting when available. Do not attach production schedules, employee data, customer records, credentials, course materials or private business files to a public report.

The package performs local JSON and file processing. It has no runtime dependency and no network connector. It does not execute target-project code or control an external system.

In scope:

- path traversal or unsafe output handling;
- CSV or HTML injection defects;
- public-boundary scanner bypass;
- manifest verification errors;
- policy selection or conservation defects that contradict documented behavior.
''')

write("CONTRIBUTING.md", '''
# Contributing

Use synthetic or clearly licensed public data. Do not submit a course case, customer record, employee schedule, private operational report or unsupported improvement claim.

Before opening a pull request:

```bash
PYTHONPATH=src python tools/release_check.py
```

Changes to simulation semantics require:

- a positive test;
- a failure or boundary test;
- conservation checks where applicable;
- documentation of the affected decision;
- regenerated committed artifacts.

Do not weaken a hard target, public boundary or test merely to obtain a feasible result.
''')

write("CODE_OF_CONDUCT.md", '''
# Code of Conduct

Discuss models, evidence and implementation professionally. Harassment, doxxing, credential disclosure, publication of private operational data and unsupported accusations about real organizations are not accepted.
''')

write("CHANGELOG.md", '''
# Changelog

## [0.1.0] — 2026-08-31

- Added a fully synthetic 21-day integrated service-operations case.
- Added four rolling-origin forecasting models.
- Added appointments, walk-ins, no-shows, queueing, abandonment, SLA and skill-based staffing.
- Added flexible capacity, overtime, equipment PM/failure/repair and lead-time spare-parts inventory.
- Added first-time-right quality and revisit generation.
- Added a 288-policy nonanticipative search across five probability-weighted scenarios.
- Added hard service targets, weighted CVaR and Pareto-frontier analysis.
- Added eight deterministic stress cases, explanations, static HTML, CSV and SHA-256 artifacts.
- Added conservation tests, public-boundary checks, Python 3.11–3.13 CI and reproducible release engineering.
''')

write("ROADMAP.md", '''
# Roadmap

## 0.2 — calibration and rolling control

- rolling-horizon replanning with frozen commitments;
- demand interval calibration and drift alarms;
- empirical service-time and patience distributions;
- posterior equipment reliability updates;
- first-time-right measurement-system validation;
- historical replay with explicit train/test separation.

## 0.3 — richer operational decisions

- appointment overbooking and protected urgent capacity;
- multi-skill shift construction with breaks and labor constraints;
- multi-echelon inventory and supplier choice;
- customer classes and fairness constraints;
- sequence-dependent setups and travel routing;
- optional LP/MIP backend with termination status, bound and optimality gap.

## Research

- value of information and adaptive recourse;
- distributionally robust scenarios;
- causal quality interventions;
- human schedule edits with feasibility diagnostics;
- signed run provenance and cross-platform deterministic builds.

No roadmap item changes the synthetic default or authorizes publication of proprietary coursework or personal operational data.
''')

write("DEVELOPMENT_DISCLOSURE.md", '''
# Development disclosure

This repository was reconstructed as an original public implementation from broad service-operations themes. AI-assisted drafting and coding were used, but claims are limited to repository-visible source, tests and generated artifacts.

The project does not reproduce the original academic case or represent a real consulting engagement. Every public operational observation is synthetic.
''')

write("AGENTS.md", '''
# Repository instructions

Preserve these invariants:

1. every case remains synthetic by default;
2. one policy is replayed across future scenarios;
3. infeasibility remains visible;
4. job and inventory conservation must hold;
5. reports never claim global optimality or production fitness;
6. course material, personal data and private business records remain excluded;
7. generated artifacts are rebuilt rather than hand-edited.

Run `PYTHONPATH=src python tools/release_check.py` before completion.
''')

write_json("ORIGIN_MANIFEST.json", {
    "schema_version": 1,
    "project": "service-operations-decision-lab",
    "version": "0.1.0",
    "assets": {
        "source_code": "original implementation",
        "documentation": "original documentation",
        "case_data": "deterministic synthetic fixture",
        "generated_reports": "derived from synthetic fixture",
        "academic_experience": "broad topic inspiration only; no course text, data or solution reproduced",
    },
    "excluded": [
        "course prompt or case text",
        "instructor materials",
        "real company identity",
        "real customer or employee records",
        "personal contact information",
        "real demand, quality, maintenance, inventory, staffing or financial data",
        "unsupported real-world improvement claims",
    ],
})
print("P041 documentation, governance and public-boundary files written")
