from __future__ import annotations

import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(content).lstrip("\n").rstrip() + "\n", encoding="utf-8", newline="\n")


write("src/service_ops_lab/simulation.py", '''
from __future__ import annotations

import copy
import hashlib
import math
import random
from collections import defaultdict
from typing import Any

from .forecasting import forecast_case
from .inventory import InventoryState
from .models import ActiveJob, Job, Policy
from .reliability import available_unit, begin_day, build_units, maybe_fail, summary as reliability_summary
from .util import percentile


def _seed(*parts: object) -> int:
    material = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _poisson(lam: float, rng: random.Random) -> int:
    if lam <= 0:
        return 0
    if lam > 24:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit = math.exp(-lam)
    product = 1.0
    count = 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def _duration_slots(mean_minutes: float, cv: float, slot_minutes: int, multiplier: float, rng: random.Random) -> int:
    variance = math.log(1.0 + cv * cv)
    sigma = math.sqrt(variance)
    mu = math.log(max(1.0, mean_minutes * multiplier)) - variance / 2.0
    minutes = rng.lognormvariate(mu, sigma)
    return max(1, int(math.ceil(minutes / slot_minutes)))


def _policy(value: Policy | dict[str, Any]) -> Policy:
    if isinstance(value, Policy):
        return value
    return Policy(
        demand_buffer=float(value["demand_buffer"]),
        flex_staff=int(value["flex_staff"]),
        overtime_slots=int(value["overtime_slots"]),
        inventory_cover_days=int(value["inventory_cover_days"]),
        pm_interval_days=int(value["pm_interval_days"]),
        quality_level=int(value["quality_level"]),
        priority_rule=str(value["priority_rule"]),
    )


def _priority(job: Job, rule: str, service_catalog: dict[str, dict[str, Any]]) -> tuple[Any, ...]:
    service_priority = -int(service_catalog[job.service_id]["priority"])
    if rule == "sla":
        return (job.due_slot, service_priority, job.arrival_slot, job.job_id)
    if rule == "shortest":
        return (job.duration_slots, job.due_slot, service_priority, job.job_id)
    return (job.arrival_slot, service_priority, job.due_slot, job.job_id)


def _merge_scenario(scenario: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(scenario)
    for key, value in (overrides or {}).items():
        merged[key] = value
    merged.setdefault("urgent_mix_multiplier", 1.0)
    return merged


def simulate_policy(
    case: dict[str, Any],
    policy_value: Policy | dict[str, Any],
    scenario: dict[str, Any],
    *,
    replication: int = 0,
    overrides: dict[str, Any] | None = None,
    forecast: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = _policy(policy_value)
    scenario = _merge_scenario(scenario, overrides)
    forecast = forecast or forecast_case(case)
    horizon_days = int(case["horizon"]["days"])
    base_slots = int(case["horizon"]["slots_per_day"])
    slot_minutes = int(case["horizon"]["slot_minutes"])
    day_slots = base_slots + policy.overtime_slots
    services = {item["id"]: item for item in case["service_types"]}
    staff_catalog = {item["id"]: item for item in case["staff"]}
    equipment_catalog = {item["id"]: item for item in case["equipment"]}
    inventory_items = copy.deepcopy(case["inventory"])
    for item in inventory_items:
        item["lead_time_days"] = max(0, int(item["lead_time_days"]) + int(scenario.get("lead_time_shift", 0)))
    inventory = InventoryState(inventory_items, policy.inventory_cover_days)
    equipment_units = build_units(case["equipment"])
    rng = random.Random(_seed(case["case_id"], scenario["id"], replication, "operations"))

    arrivals_by_slot: dict[int, list[Job]] = defaultdict(list)
    pending_revisits: dict[int, list[Job]] = defaultdict(list)
    waiting: list[Job] = []
    active: list[ActiveJob] = []
    completed: list[Job] = []
    abandoned: list[Job] = []
    no_shows = 0
    generated_primary = 0
    generated_revisits = 0
    jobs_stockout_blocked: set[str] = set()
    sla_met = 0
    first_time_right = 0
    total_wait_slots: list[int] = []
    staff_busy_slots: dict[str, int] = defaultdict(int)
    equipment_busy_slots: dict[str, int] = defaultdict(int)
    daily_trace: list[dict[str, Any]] = []
    service_generated: dict[str, int] = defaultdict(int)
    service_completed: dict[str, int] = defaultdict(int)
    service_abandoned: dict[str, int] = defaultdict(int)
    service_backlog: dict[str, int] = defaultdict(int)
    quality_failures = 0

    expected_daily_parts: dict[str, float] = defaultdict(float)
    for service_id, service in services.items():
        mean_demand = sum(forecast["services"][service_id]["point_forecast"]) / horizon_days
        for sku, quantity in service["parts"].items():
            expected_daily_parts[sku] += mean_demand * quantity * (1.0 + policy.demand_buffer)

    def create_jobs(day: int) -> None:
        nonlocal no_shows, generated_primary
        for service_id, service in services.items():
            point = float(forecast["services"][service_id]["point_forecast"][day])
            multiplier = float(scenario.get("demand_multiplier", 1.0))
            if service_id == "urgent-restoration":
                multiplier *= float(scenario.get("urgent_mix_multiplier", 1.0))
            count = _poisson(point * multiplier, rng)
            for sequence in range(count):
                appointment = rng.random() < float(service["appointment_share"])
                if appointment and rng.random() < float(service["no_show_rate"]):
                    no_shows += 1
                    continue
                local_slot = (
                    int(round((sequence + 1) * (base_slots - 2) / (count + 1)))
                    if appointment and count > 0
                    else rng.randrange(0, max(1, base_slots - 2))
                )
                arrival_slot = day * day_slots + min(base_slots - 1, max(0, local_slot))
                duration = _duration_slots(
                    float(service["mean_minutes"]),
                    float(service["duration_cv"]),
                    slot_minutes,
                    float(scenario.get("service_time_multiplier", 1.0)),
                    rng,
                )
                patience = max(1, int(math.ceil(float(service["patience_minutes"]) / slot_minutes)))
                sla = max(1, int(math.ceil(float(service["sla_minutes"]) / slot_minutes)))
                job = Job(
                    job_id=f"{scenario['id']}-r{replication}-d{day}-{service_id}-{sequence}",
                    service_id=service_id,
                    arrival_slot=arrival_slot,
                    patience_slots=patience,
                    due_slot=arrival_slot + sla,
                    duration_slots=duration,
                    skill=service["skill"],
                    equipment=service["equipment"],
                    parts={key: int(value) for key, value in service["parts"].items()},
                )
                arrivals_by_slot[arrival_slot].append(job)
                generated_primary += 1
                service_generated[service_id] += 1

    for day in range(horizon_days):
        create_jobs(day)

    base_labor_cost = 0.0
    flex_cost = 0.0
    overtime_cost = 0.0
    operating_staff_slots = 0
    absent_staff_days = 0

    for day in range(horizon_days):
        inventory.begin_day(day)
        inventory.reorder(day, expected_daily_parts)
        begin_day(equipment_units, equipment_catalog, day, day_slots, policy.pm_interval_days)
        for revisit in pending_revisits.pop(day, []):
            arrivals_by_slot[revisit.arrival_slot].append(revisit)

        absent: set[str] = set()
        for person in case["staff"]:
            probability = min(0.95, float(person["absence_probability"]) * float(scenario.get("absence_multiplier", 1.0)))
            if rng.random() < probability:
                absent.add(person["id"])
                absent_staff_days += 1
            else:
                operating_staff_slots += int(person["daily_slots"]) + policy.overtime_slots
                base_labor_cost += int(person["daily_slots"]) * float(person["cost_per_slot"])
                overtime_cost += policy.overtime_slots * float(case["economics"]["overtime_cost_per_slot"])

        flex_active = False
        if policy.flex_staff:
            forecast_work = sum(
                forecast["services"][service_id]["point_forecast"][day]
                * services[service_id]["mean_minutes"]
                / slot_minutes
                for service_id in services
            ) * (1.0 + policy.demand_buffer)
            regular_capacity = sum(
                int(person["daily_slots"])
                for person in case["staff"]
                if person["id"] not in absent
            )
            flex_active = forecast_work > regular_capacity * 0.66
            if flex_active:
                operating_staff_slots += base_slots
                flex_cost += base_slots * float(case["economics"]["flex_staff_cost_per_slot"])

        start_completed = len(completed)
        start_abandoned = len(abandoned)
        start_waiting = len(waiting)
        start_stockout = len(jobs_stockout_blocked)
        for local_slot in range(day_slots):
            absolute_slot = day * day_slots + local_slot
            waiting.extend(arrivals_by_slot.pop(absolute_slot, []))

            next_active: list[ActiveJob] = []
            for assignment in active:
                assignment.remaining_slots -= 1
                staff_busy_slots[assignment.staff_id] += 1
                equipment_busy_slots[assignment.equipment_id] += 1
                if assignment.remaining_slots <= 0:
                    assignment.job.completion_slot = absolute_slot + 1
                    completed.append(assignment.job)
                    service_completed[assignment.job.service_id] += 1
                    wait = (assignment.job.start_slot or assignment.job.arrival_slot) - assignment.job.arrival_slot
                    total_wait_slots.append(max(0, wait))
                    if (assignment.job.start_slot or absolute_slot) <= assignment.job.due_slot:
                        sla_met += 1
                    service = services[assignment.job.service_id]
                    ftr = min(0.995, max(0.05, float(service["base_ftr"]) + 0.045 * policy.quality_level + float(scenario.get("quality_shift", 0))))
                    if rng.random() < ftr:
                        first_time_right += 1
                    else:
                        quality_failures += 1
                        revisit_day = day + int(service["revisit_delay_days"])
                        if revisit_day < horizon_days:
                            revisit = Job(
                                job_id=f"{assignment.job.job_id}-revisit",
                                service_id=assignment.job.service_id,
                                arrival_slot=revisit_day * day_slots + min(base_slots // 2, base_slots - 1),
                                patience_slots=assignment.job.patience_slots,
                                due_slot=revisit_day * day_slots + min(base_slots // 2, base_slots - 1) + max(1, assignment.job.due_slot - assignment.job.arrival_slot),
                                duration_slots=max(1, int(math.ceil(assignment.job.duration_slots * 0.65))),
                                skill=assignment.job.skill,
                                equipment=assignment.job.equipment,
                                parts=dict(assignment.job.parts),
                                revisit=True,
                            )
                            pending_revisits[revisit_day].append(revisit)
                            generated_revisits += 1
                            service_generated[revisit.service_id] += 1
                else:
                    next_active.append(assignment)
            active = next_active

            still_waiting: list[Job] = []
            for job in waiting:
                if absolute_slot - job.arrival_slot > job.patience_slots:
                    job.abandoned = True
                    abandoned.append(job)
                    service_abandoned[job.service_id] += 1
                    total_wait_slots.append(max(0, absolute_slot - job.arrival_slot))
                else:
                    still_waiting.append(job)
            waiting = still_waiting

            busy_staff = {assignment.staff_id for assignment in active}
            busy_equipment = {assignment.equipment_id for assignment in active}
            queue = sorted(waiting, key=lambda job: _priority(job, policy.priority_rule, services))
            started_ids: set[str] = set()
            for job in queue:
                if job.job_id in started_ids:
                    continue
                eligible_staff = []
                for person in case["staff"]:
                    staff_id = person["id"]
                    available_until = day * day_slots + min(day_slots, int(person["daily_slots"]) + policy.overtime_slots)
                    if (
                        staff_id not in absent
                        and staff_id not in busy_staff
                        and job.skill in person["skills"]
                        and absolute_slot + job.duration_slots <= available_until
                    ):
                        eligible_staff.append(staff_id)
                if flex_active and "flex-staff" not in busy_staff and absolute_slot + job.duration_slots <= day * day_slots + base_slots:
                    eligible_staff.append("flex-staff")
                if not eligible_staff:
                    continue
                unit = available_unit(equipment_units, job.equipment, absolute_slot)
                if unit is None or unit.unit_id in busy_equipment:
                    continue
                maybe_fail(unit, equipment_catalog[job.equipment], float(scenario.get("failure_multiplier", 1.0)), rng, absolute_slot)
                if unit.down_until_slot > absolute_slot:
                    continue
                if not inventory.can_consume(job.parts):
                    if job.job_id not in jobs_stockout_blocked:
                        inventory.consume(job.parts)
                        jobs_stockout_blocked.add(job.job_id)
                        job.stockout_blocked = True
                    continue
                inventory.consume(job.parts)
                staff_id = min(eligible_staff)
                job.start_slot = absolute_slot
                active.append(ActiveJob(job, staff_id, unit.unit_id, job.duration_slots))
                busy_staff.add(staff_id)
                busy_equipment.add(unit.unit_id)
                started_ids.add(job.job_id)
            if started_ids:
                waiting = [job for job in waiting if job.job_id not in started_ids]

        inventory.end_day()
        daily_trace.append(
            {
                "day": day,
                "arrivals": sum(len(items) for slot, items in arrivals_by_slot.items() if day * day_slots <= slot < (day + 1) * day_slots),
                "completed": len(completed) - start_completed,
                "abandoned": len(abandoned) - start_abandoned,
                "opening_backlog": start_waiting,
                "ending_backlog": len(waiting) + len(active),
                "new_stockout_blocked": len(jobs_stockout_blocked) - start_stockout,
                "absent_staff": len(absent),
                "flex_active": flex_active,
                "inventory_on_hand": dict(inventory.on_hand),
            }
        )

    backlog_jobs = waiting + [assignment.job for assignment in active]
    for day, revisits in pending_revisits.items():
        if day >= horizon_days:
            backlog_jobs.extend(revisits)
    for job in backlog_jobs:
        service_backlog[job.service_id] += 1
    generated = generated_primary + generated_revisits
    flow_error = generated - len(completed) - len(abandoned) - len(backlog_jobs)
    inventory_result = inventory.summary()
    if flow_error != 0:
        raise RuntimeError(f"job-flow conservation failed: {flow_error}")
    if any(value != 0 for value in inventory_result["balance_error"].values()):
        raise RuntimeError(f"inventory conservation failed: {inventory_result['balance_error']}")

    waits_minutes = [value * slot_minutes for value in total_wait_slots]
    completion_rate = 0.0 if generated == 0 else len(completed) / generated
    abandonment_rate = 0.0 if generated == 0 else len(abandoned) / generated
    stockout_rate = 0.0 if generated == 0 else len(jobs_stockout_blocked) / generated
    sla_attainment = 0.0 if not completed else sla_met / len(completed)
    ftr_rate = 0.0 if not completed else first_time_right / len(completed)
    service_metrics = {}
    for service_id in services:
        denominator = service_generated[service_id]
        service_metrics[service_id] = {
            "generated": denominator,
            "completed": service_completed[service_id],
            "abandoned": service_abandoned[service_id],
            "backlog": service_backlog[service_id],
            "completion_rate": 0.0 if denominator == 0 else service_completed[service_id] / denominator,
        }

    reliability = reliability_summary(equipment_units)
    economics = case["economics"]
    base_cost = base_labor_cost + flex_cost + overtime_cost + inventory_result["inventory_cost"]
    penalty_cost = (
        len(abandoned) * float(economics["abandonment_cost"])
        + len(backlog_jobs) * float(economics["backlog_cost_per_job_day"])
        + (len(completed) - sla_met) * float(economics["sla_miss_cost"])
        + quality_failures * float(economics["revisit_cost"])
        + sum(inventory_result["shortage_units"].values()) * float(economics["stockout_cost_per_unit"])
        + sum(waits_minutes) * float(economics["wait_cost_per_minute"])
        + reliability["failures"] * sum(float(item["failure_cost"]) for item in case["equipment"]) / len(case["equipment"])
        + reliability["pm_events"] * sum(float(item["pm_cost"]) for item in case["equipment"]) / len(case["equipment"])
        + horizon_days * policy.quality_level * float(economics["quality_program_daily_cost"])
    )
    service_value = sum(service_completed[service_id] * float(economics["completion_revenue"][service_id]) for service_id in services)
    average_wip = sum(row["ending_backlog"] for row in daily_trace) / horizon_days
    throughput_per_day = len(completed) / horizon_days
    average_wait_days = 0.0 if not waits_minutes else sum(waits_minutes) / len(waits_minutes) / (slot_minutes * base_slots)
    little_law_implied_wip = throughput_per_day * average_wait_days
    available_equipment_slots = len(equipment_units) * horizon_days * day_slots

    return {
        "schema_version": 1,
        "case_id": case["case_id"],
        "policy": policy.as_dict(),
        "scenario_id": scenario["id"],
        "replication": replication,
        "metrics": {
            "generated_jobs": generated,
            "primary_jobs": generated_primary,
            "revisit_jobs": generated_revisits,
            "completed_jobs": len(completed),
            "abandoned_jobs": len(abandoned),
            "backlog_jobs": len(backlog_jobs),
            "no_shows": no_shows,
            "completion_rate": round(completion_rate, 6),
            "abandonment_rate": round(abandonment_rate, 6),
            "stockout_rate": round(stockout_rate, 6),
            "sla_attainment": round(sla_attainment, 6),
            "first_time_right": round(ftr_rate, 6),
            "mean_wait_minutes": round(0.0 if not waits_minutes else sum(waits_minutes) / len(waits_minutes), 4),
            "p50_wait_minutes": round(percentile(waits_minutes, 0.50), 4),
            "p90_wait_minutes": round(percentile(waits_minutes, 0.90), 4),
            "staff_utilization": round(0.0 if operating_staff_slots == 0 else sum(staff_busy_slots.values()) / operating_staff_slots, 6),
            "equipment_utilization": round(0.0 if available_equipment_slots == 0 else sum(equipment_busy_slots.values()) / available_equipment_slots, 6),
            "average_wip": round(average_wip, 4),
            "throughput_per_day": round(throughput_per_day, 4),
            "little_law_implied_wip": round(little_law_implied_wip, 4),
            "flow_time_boundary": "finite-horizon queue wait only; not a steady-state Little's Law certification",
            "base_cost": round(base_cost, 4),
            "penalty_cost": round(penalty_cost, 4),
            "total_cost": round(base_cost + penalty_cost, 4),
            "service_value": round(service_value, 4),
            "quality_failures": quality_failures,
            "absent_staff_days": absent_staff_days,
        },
        "service_metrics": service_metrics,
        "inventory": inventory_result,
        "reliability": reliability,
        "daily_trace": daily_trace,
        "conservation": {
            "job_flow_error": flow_error,
            "inventory_balance_error": inventory_result["balance_error"],
        },
        "boundary": {
            "synthetic": True,
            "nonanticipative_policy": True,
            "production_recommendation": False,
            "global_optimality_claim": False,
        },
    }
''')

write("src/service_ops_lab/optimization.py", '''
from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Any

from .forecasting import forecast_case
from .models import Policy
from .simulation import simulate_policy
from .util import weighted_cvar, weighted_mean


def generate_policies(case: dict[str, Any]) -> list[Policy]:
    grid = case["policy_grid"]
    return [
        Policy(float(demand_buffer), int(flex_staff), int(overtime_slots), int(inventory_cover_days), int(pm_interval_days), int(quality_level), str(priority_rule))
        for demand_buffer, flex_staff, overtime_slots, inventory_cover_days, pm_interval_days, quality_level, priority_rule in itertools.product(
            grid["demand_buffer"],
            grid["flex_staff"],
            grid["overtime_slots"],
            grid["inventory_cover_days"],
            grid["pm_interval_days"],
            grid["quality_level"],
            grid["priority_rule"],
        )
    ]


def _aggregate(case: dict[str, Any], policy: Policy, simulations: list[dict[str, Any]]) -> dict[str, Any]:
    probabilities = {item["id"]: float(item["probability"]) for item in case["scenarios"]}
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in simulations:
        by_scenario[result["scenario_id"]].append(result)

    scenario_summaries = []
    for scenario_id, results in sorted(by_scenario.items()):
        metric_names = results[0]["metrics"].keys()
        metrics = {
            name: sum(float(result["metrics"][name]) for result in results) / len(results)
            for name in metric_names
            if isinstance(results[0]["metrics"][name], (int, float)) and not isinstance(results[0]["metrics"][name], bool)
        }
        service_ids = results[0]["service_metrics"].keys()
        service = {
            service_id: {
                "completion_rate": sum(float(result["service_metrics"][service_id]["completion_rate"]) for result in results) / len(results)
            }
            for service_id in service_ids
        }
        scenario_summaries.append({"scenario_id": scenario_id, "probability": probabilities[scenario_id], "metrics": metrics, "service_metrics": service})

    metric_names = scenario_summaries[0]["metrics"].keys()
    expected = {
        name: weighted_mean((item["metrics"][name], item["probability"]) for item in scenario_summaries)
        for name in metric_names
    }
    higher_better = {"completion_rate", "sla_attainment", "first_time_right", "staff_utilization", "equipment_utilization", "service_value", "throughput_per_day"}
    worst = {
        name: (min(item["metrics"][name] for item in scenario_summaries) if name in higher_better else max(item["metrics"][name] for item in scenario_summaries))
        for name in metric_names
    }
    expected_service = {
        service_id: weighted_mean((item["service_metrics"][service_id]["completion_rate"], item["probability"]) for item in scenario_summaries)
        for service_id in scenario_summaries[0]["service_metrics"]
    }
    worst_service = {
        service_id: min(item["service_metrics"][service_id]["completion_rate"] for item in scenario_summaries)
        for service_id in scenario_summaries[0]["service_metrics"]
    }
    targets = case["targets"]
    violations = []

    def lower(name: str, actual: float, target: float) -> None:
        if actual + 1e-12 < target:
            violations.append({"constraint": name, "actual": actual, "target": target, "gap": target - actual})

    def upper(name: str, actual: float, target: float) -> None:
        if actual - 1e-12 > target:
            violations.append({"constraint": name, "actual": actual, "target": target, "gap": actual - target})

    lower("expected_completion", expected["completion_rate"], float(targets["expected_completion"]))
    lower("worst_completion", worst["completion_rate"], float(targets["worst_completion"]))
    lower("expected_sla", expected["sla_attainment"], float(targets["expected_sla"]))
    lower("minimum_ftr", expected["first_time_right"], float(targets["minimum_ftr"]))
    upper("maximum_abandonment", expected["abandonment_rate"], float(targets["maximum_abandonment"]))
    upper("maximum_stockout", expected["stockout_rate"], float(targets["maximum_stockout"]))
    upper("maximum_p90_wait_minutes", expected["p90_wait_minutes"], float(targets["maximum_p90_wait_minutes"]))
    for service_id, target in targets["service_completion_minimums"].items():
        lower(f"service_completion:{service_id}", expected_service[service_id], float(target))

    normalized_violation = 0.0
    for violation in violations:
        normalized_violation += violation["gap"] / max(1e-9, abs(violation["target"]))
    cvar_cost = weighted_cvar(
        ((item["metrics"]["total_cost"], item["probability"]) for item in scenario_summaries),
        float(targets["cvar_alpha"]),
    )
    objective = expected["total_cost"] + float(targets["risk_aversion"]) * cvar_cost
    return {
        "policy": policy.as_dict(),
        "feasible": not violations,
        "violation_score": round(normalized_violation, 8),
        "violations": violations,
        "objective": round(objective, 4),
        "cvar_cost": round(cvar_cost, 4),
        "expected_metrics": {key: round(value, 6) for key, value in expected.items()},
        "worst_metrics": {key: round(value, 6) for key, value in worst.items()},
        "expected_service_completion": {key: round(value, 6) for key, value in expected_service.items()},
        "worst_service_completion": {key: round(value, 6) for key, value in worst_service.items()},
        "scenario_summaries": scenario_summaries,
    }


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a = (left["expected_metrics"]["total_cost"], -left["worst_metrics"]["completion_rate"], left["expected_metrics"]["p90_wait_minutes"], -left["expected_metrics"]["first_time_right"])
    b = (right["expected_metrics"]["total_cost"], -right["worst_metrics"]["completion_rate"], right["expected_metrics"]["p90_wait_minutes"], -right["expected_metrics"]["first_time_right"])
    return all(x <= y + 1e-12 for x, y in zip(a, b, strict=True)) and any(x < y - 1e-12 for x, y in zip(a, b, strict=True))


def pareto_frontier(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [item for item in results if item["feasible"]] or results
    frontier = [item for item in candidates if not any(_dominates(other, item) for other in candidates if other is not item)]
    return sorted(frontier, key=lambda item: (item["expected_metrics"]["total_cost"], -item["worst_metrics"]["completion_rate"], item["policy"]["policy_id"]))


def optimize_case(case: dict[str, Any], *, policy_limit: int | None = None, replications: int | None = None) -> dict[str, Any]:
    forecast = forecast_case(case)
    policies = generate_policies(case)
    if policy_limit is not None:
        policies = policies[: int(policy_limit)]
    replications = int(replications if replications is not None else case["horizon"]["replications"])
    results = []
    for policy in policies:
        simulations = [
            simulate_policy(case, policy, scenario, replication=replication, forecast=forecast)
            for scenario in case["scenarios"]
            for replication in range(replications)
        ]
        results.append(_aggregate(case, policy, simulations))
    feasible = [item for item in results if item["feasible"]]
    if feasible:
        selected = min(feasible, key=lambda item: (item["objective"], item["expected_metrics"]["p90_wait_minutes"], item["policy"]["policy_id"]))
        status = "feasible-selected"
    else:
        selected = min(results, key=lambda item: (item["violation_score"], item["objective"], item["policy"]["policy_id"]))
        status = "least-violating-no-feasible-policy"
    frontier = pareto_frontier(results)
    return {
        "schema_version": 1,
        "case_id": case["case_id"],
        "candidate_policy_count": len(results),
        "feasible_policy_count": len(feasible),
        "selection_status": status,
        "selected_policy_id": selected["policy"]["policy_id"],
        "selected": selected,
        "pareto_frontier": [
            {
                "policy_id": item["policy"]["policy_id"],
                "expected_cost": item["expected_metrics"]["total_cost"],
                "worst_completion": item["worst_metrics"]["completion_rate"],
                "p90_wait_minutes": item["expected_metrics"]["p90_wait_minutes"],
                "first_time_right": item["expected_metrics"]["first_time_right"],
                "feasible": item["feasible"],
            }
            for item in frontier
        ],
        "policy_catalog": results,
        "forecast": forecast,
        "boundary": {
            "finite_policy_grid": True,
            "global_optimality_claim": False,
            "synthetic_case": True,
            "nonanticipative_policy": True,
        },
    }
''')

write("src/service_ops_lab/stress.py", '''
from __future__ import annotations

from typing import Any

from .forecasting import forecast_case
from .simulation import simulate_policy


def run_stress(case: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    policy = plan["selected"]["policy"]
    baseline = next(item for item in case["scenarios"] if item["id"] == "baseline")
    forecast = forecast_case(case)
    results = []
    for stress in case["stress_cases"]:
        simulation = simulate_policy(
            case,
            policy,
            {**baseline, "id": stress["id"], "probability": 1.0},
            replication=0,
            overrides=stress["overrides"],
            forecast=forecast,
        )
        results.append(
            {
                "stress_id": stress["id"],
                "overrides": stress["overrides"],
                "metrics": simulation["metrics"],
                "service_metrics": simulation["service_metrics"],
                "conservation": simulation["conservation"],
            }
        )
    return {
        "schema_version": 1,
        "case_id": case["case_id"],
        "selected_policy_id": plan["selected_policy_id"],
        "stress_case_count": len(results),
        "results": results,
        "boundary": "Stress cases are deterministic sensitivity tests, not probability forecasts.",
    }
''')

write("src/service_ops_lab/explain.py", '''
from __future__ import annotations

from typing import Any


def explain_plan(case: dict[str, Any], plan: dict[str, Any], stress: dict[str, Any]) -> dict[str, Any]:
    selected = plan["selected"]
    expected = selected["expected_metrics"]
    worst = selected["worst_metrics"]
    targets = case["targets"]
    gaps = list(selected["violations"])
    service_gaps = [
        {
            "service_id": service_id,
            "expected_completion": selected["expected_service_completion"][service_id],
            "worst_completion": selected["worst_service_completion"][service_id],
            "target": target,
        }
        for service_id, target in targets["service_completion_minimums"].items()
        if selected["expected_service_completion"][service_id] < target
    ]
    worst_stress = min(stress["results"], key=lambda item: (item["metrics"]["completion_rate"], -item["metrics"]["total_cost"], item["stress_id"]))
    costliest_stress = max(stress["results"], key=lambda item: (item["metrics"]["total_cost"], item["stress_id"]))
    statements = []
    statements.append(
        "A fully feasible policy was found within the declared finite grid."
        if selected["feasible"]
        else "No candidate satisfied every hard target; the selected policy minimizes normalized violation before risk-adjusted cost."
    )
    statements.append(
        f"Expected completion is {expected['completion_rate']:.1%}; worst modeled completion is {worst['completion_rate']:.1%}."
    )
    statements.append(
        f"Expected first-time-right is {expected['first_time_right']:.1%}; expected abandonment is {expected['abandonment_rate']:.1%}."
    )
    statements.append(
        f"The lowest-completion deterministic stress is {worst_stress['stress_id']} at {worst_stress['metrics']['completion_rate']:.1%}."
    )
    return {
        "schema_version": 1,
        "case_id": case["case_id"],
        "selected_policy_id": plan["selected_policy_id"],
        "selection_status": plan["selection_status"],
        "managerial_summary": statements,
        "hard_constraint_gaps": gaps,
        "service_gaps": service_gaps,
        "worst_completion_stress": worst_stress,
        "costliest_stress": costliest_stress,
        "recommended_review_sequence": [
            "Confirm that the synthetic demand, time, quality, staffing and cost assumptions are replaced with owned data.",
            "Review service-type fairness and urgent-work prioritization rather than relying only on aggregate completion.",
            "Inspect stockout, maintenance and absence traces before changing staffing or inventory policy.",
            "Re-run rolling-origin forecast validation and out-of-sample simulation after every material data revision.",
            "Use the selected policy as a bounded candidate, not as proof of global optimality or production suitability.",
        ],
        "model_limits": [
            "Finite policy grid rather than a proof of global optimality.",
            "Synthetic arrivals, service times, failures, absences, quality and costs.",
            "Finite-horizon queue diagnostics rather than steady-state queueing certification.",
            "No real customer, worker, business, course or financial data.",
        ],
    }
''')

write("src/service_ops_lab/reporting.py", '''
from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from .util import safe_csv_cell


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def render_markdown(case: dict[str, Any], plan: dict[str, Any], stress: dict[str, Any], explanation: dict[str, Any]) -> str:
    selected = plan["selected"]
    expected = selected["expected_metrics"]
    worst = selected["worst_metrics"]
    lines = [
        f"# Service Operations Decision Report — {case['title']}",
        "",
        f"- Case: `{case['case_id']}`",
        f"- As of: `{case['as_of']}`",
        f"- Selected policy: `{plan['selected_policy_id']}`",
        f"- Selection status: `{plan['selection_status']}`",
        f"- Candidate policies: **{plan['candidate_policy_count']}**",
        f"- Feasible policies: **{plan['feasible_policy_count']}**",
        "",
        "> This is a synthetic decision laboratory. It is not a production forecast, staffing instruction, customer-service claim, or proof of global optimality.",
        "",
        "## Decision dashboard",
        "",
        "| Metric | Expected | Worst modeled |",
        "|---|---:|---:|",
        f"| Completion | {expected['completion_rate']:.1%} | {worst['completion_rate']:.1%} |",
        f"| SLA attainment | {expected['sla_attainment']:.1%} | {worst['sla_attainment']:.1%} |",
        f"| First-time-right | {expected['first_time_right']:.1%} | {worst['first_time_right']:.1%} |",
        f"| Abandonment | {expected['abandonment_rate']:.1%} | {worst['abandonment_rate']:.1%} |",
        f"| Stockout blocked | {expected['stockout_rate']:.1%} | {worst['stockout_rate']:.1%} |",
        f"| P90 wait | {expected['p90_wait_minutes']:.1f} min | {worst['p90_wait_minutes']:.1f} min |",
        f"| Total cost | {expected['total_cost']:.2f} | {worst['total_cost']:.2f} |",
        "",
        "## Selected policy",
        "",
    ]
    for key, value in selected["policy"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines += ["", "## Managerial interpretation", ""]
    lines.extend(f"- {item}" for item in explanation["managerial_summary"])
    lines += ["", "## Constraint gaps", ""]
    if selected["violations"]:
        for item in selected["violations"]:
            lines.append(f"- `{item['constraint']}`: actual {item['actual']:.4f}, target {item['target']:.4f}, gap {item['gap']:.4f}.")
    else:
        lines.append("- All declared hard targets are satisfied in the modeled scenario set.")
    lines += ["", "## Stress envelope", "", "| Stress | Completion | SLA | FTR | Abandonment | P90 wait | Cost |", "|---|---:|---:|---:|---:|---:|---:|"]
    for item in stress["results"]:
        metric = item["metrics"]
        lines.append(f"| {item['stress_id']} | {metric['completion_rate']:.1%} | {metric['sla_attainment']:.1%} | {metric['first_time_right']:.1%} | {metric['abandonment_rate']:.1%} | {metric['p90_wait_minutes']:.1f} | {metric['total_cost']:.2f} |")
    lines += ["", "## Required next validation", ""]
    lines.extend(f"- {item}" for item in explanation["recommended_review_sequence"])
    lines += ["", "## Limits", ""]
    lines.extend(f"- {item}" for item in explanation["model_limits"])
    return "\n".join(lines) + "\n"


def render_html(case: dict[str, Any], plan: dict[str, Any], stress: dict[str, Any], explanation: dict[str, Any]) -> str:
    selected = plan["selected"]
    expected = selected["expected_metrics"]
    worst = selected["worst_metrics"]
    cards = [
        ("Expected completion", f"{expected['completion_rate']:.1%}"),
        ("Worst completion", f"{worst['completion_rate']:.1%}"),
        ("Expected SLA", f"{expected['sla_attainment']:.1%}"),
        ("First-time-right", f"{expected['first_time_right']:.1%}"),
        ("P90 wait", f"{expected['p90_wait_minutes']:.1f} min"),
        ("CVaR cost", f"{selected['cvar_cost']:.2f}"),
    ]
    card_html = "".join(f"<article><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></article>" for label, value in cards)
    policy_html = "".join(f"<li><code>{html.escape(str(key))}</code><b>{html.escape(str(value))}</b></li>" for key, value in selected["policy"].items())
    stress_rows = "".join(
        f"<tr><td>{html.escape(item['stress_id'])}</td><td>{item['metrics']['completion_rate']:.1%}</td><td>{item['metrics']['sla_attainment']:.1%}</td><td>{item['metrics']['first_time_right']:.1%}</td><td>{item['metrics']['abandonment_rate']:.1%}</td><td>{item['metrics']['p90_wait_minutes']:.1f}</td><td>{item['metrics']['total_cost']:.2f}</td></tr>"
        for item in stress["results"]
    )
    summary = "".join(f"<li>{html.escape(item)}</li>" for item in explanation["managerial_summary"])
    review = "".join(f"<li>{html.escape(item)}</li>" for item in explanation["recommended_review_sequence"])
    frontier = "".join(
        f"<tr><td><code>{html.escape(item['policy_id'])}</code></td><td>{item['expected_cost']:.2f}</td><td>{item['worst_completion']:.1%}</td><td>{item['p90_wait_minutes']:.1f}</td><td>{item['first_time_right']:.1%}</td></tr>"
        for item in plan["pareto_frontier"][:20]
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(case['title'])}</title><style>
:root{{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#162238;background:#f4f7fb}}*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1180px;margin:auto;padding:28px 18px 64px}}header{{padding:34px;border-radius:24px;background:linear-gradient(135deg,#13213a,#0b5963);color:white}}header p{{max-width:850px}}.badge{{display:inline-block;padding:6px 10px;border:1px solid #79d7d1;border-radius:999px;font-size:12px}}.metrics,.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}}.metrics article,.panel{{background:white;border:1px solid #d9e2ef;border-radius:16px;padding:18px}}.metrics span{{display:block;color:#5c677a;font-size:13px}}.metrics strong{{display:block;font-size:27px;margin-top:6px}}h2{{margin-top:32px}}ul.policy{{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px}}ul.policy li{{background:#eef4f8;padding:10px;border-radius:10px;display:flex;justify-content:space-between;gap:12px}}.table{{overflow:auto;background:white;border:1px solid #d9e2ef;border-radius:16px}}table{{width:100%;border-collapse:collapse;min-width:760px}}th,td{{padding:10px 12px;border-bottom:1px solid #e5ebf2;text-align:left;font-size:14px}}th{{background:#edf3f7}}.warning{{border-left:5px solid #d69a2d;background:#fff7e8;padding:14px 18px;border-radius:10px}}code{{overflow-wrap:anywhere}}@media print{{body{{background:white}}main{{max-width:none}}header{{color:black;background:white;border:2px solid #222}}}}@media(max-width:520px){{main{{padding:12px}}header{{padding:22px}}}}
</style></head><body><main><header><span class="badge">Synthetic integrated service-operations lab</span><h1>{html.escape(case['title'])}</h1><p>Demand forecasting, appointments and walk-ins, queueing, staffing, equipment reliability, spare-parts inventory, quality, revisits and risk-adjusted policy selection in one auditable model.</p><p><strong>{html.escape(plan['selection_status'])}</strong> · {plan['candidate_policy_count']} policies · {plan['feasible_policy_count']} feasible</p></header><section class="metrics">{card_html}</section><p class="warning">This static report uses fictional data. It is not a production forecast, staffing instruction, customer-service claim or proof of global optimality.</p><h2>Selected policy</h2><ul class="policy">{policy_html}</ul><section class="grid"><article class="panel"><h2>Managerial reading</h2><ul>{summary}</ul></article><article class="panel"><h2>Required validation</h2><ol>{review}</ol></article></section><h2>Deterministic stress envelope</h2><div class="table"><table><thead><tr><th>Stress</th><th>Completion</th><th>SLA</th><th>FTR</th><th>Abandon</th><th>P90 wait</th><th>Cost</th></tr></thead><tbody>{stress_rows}</tbody></table></div><h2>Pareto frontier</h2><div class="table"><table><thead><tr><th>Policy</th><th>Expected cost</th><th>Worst completion</th><th>P90 wait</th><th>FTR</th></tr></thead><tbody>{frontier}</tbody></table></div><h2>Interpretation boundary</h2><p>Results validate the deterministic software behavior of this synthetic model. They do not certify demand, service-time, reliability, inventory, quality, cost or workforce assumptions for a real operation.</p></main></body></html>'''


def write_outputs(output_dir: str | Path, case: dict[str, Any], plan: dict[str, Any], stress: dict[str, Any], explanation: dict[str, Any]) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    _json(root / "plan.json", plan)
    _json(root / "stress.json", stress)
    _json(root / "explanation.json", explanation)
    _json(root / "forecast.json", plan["forecast"])
    (root / "decision-report.md").write_text(render_markdown(case, plan, stress, explanation), encoding="utf-8", newline="\n")
    (root / "decision-lab.html").write_text(render_html(case, plan, stress, explanation) + "\n", encoding="utf-8", newline="\n")

    with (root / "policy-catalog.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["policy_id", "feasible", "violation_score", "objective", "expected_cost", "cvar_cost", "expected_completion", "worst_completion", "p90_wait", "first_time_right"])
        for item in plan["policy_catalog"]:
            writer.writerow([safe_csv_cell(item["policy"]["policy_id"]), item["feasible"], item["violation_score"], item["objective"], item["expected_metrics"]["total_cost"], item["cvar_cost"], item["expected_metrics"]["completion_rate"], item["worst_metrics"]["completion_rate"], item["expected_metrics"]["p90_wait_minutes"], item["expected_metrics"]["first_time_right"]])

    with (root / "scenario-results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scenario_id", "probability", "completion_rate", "sla_attainment", "first_time_right", "abandonment_rate", "stockout_rate", "p90_wait_minutes", "total_cost"])
        for item in plan["selected"]["scenario_summaries"]:
            metric = item["metrics"]
            writer.writerow([safe_csv_cell(item["scenario_id"]), item["probability"], metric["completion_rate"], metric["sla_attainment"], metric["first_time_right"], metric["abandonment_rate"], metric["stockout_rate"], metric["p90_wait_minutes"], metric["total_cost"]])

    with (root / "stress-results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["stress_id", "completion_rate", "sla_attainment", "first_time_right", "abandonment_rate", "p90_wait_minutes", "total_cost"])
        for item in stress["results"]:
            metric = item["metrics"]
            writer.writerow([safe_csv_cell(item["stress_id"]), metric["completion_rate"], metric["sla_attainment"], metric["first_time_right"], metric["abandonment_rate"], metric["p90_wait_minutes"], metric["total_cost"]])

    manifest = {}
    for path in sorted(root.iterdir()):
        if path.is_file() and path.name != "artifact-manifest.json":
            manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    _json(root / "artifact-manifest.json", {"schema_version": 1, "algorithm": "sha256", "files": manifest})
    return manifest
''')

write("src/service_ops_lab/artifacts.py", '''
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_manifest(directory: str | Path) -> list[str]:
    root = Path(directory)
    manifest_path = root / "artifact-manifest.json"
    if not manifest_path.is_file():
        return ["artifact-manifest.json is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = []
    expected = manifest.get("files", {})
    actual_names = {path.name for path in root.iterdir() if path.is_file() and path.name != manifest_path.name}
    if actual_names != set(expected):
        errors.append(f"manifest file set differs: expected={sorted(expected)} actual={sorted(actual_names)}")
    for name, digest in expected.items():
        path = root / name
        if not path.is_file():
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            errors.append(f"digest mismatch: {name}")
    return errors
''')

write("src/service_ops_lab/cli.py", '''
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .artifacts import verify_manifest
from .config import load_case, validate_case
from .errors import ServiceOpsError
from .explain import explain_plan
from .forecasting import forecast_case
from .optimization import optimize_case
from .reporting import write_outputs
from .simulation import simulate_policy
from .stress import run_stress
from .util import canonical_json, stable_hash


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="sodl", description="Synthetic integrated service-operations decision laboratory.")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = root.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--case")
    validate.add_argument("--json", action="store_true")
    forecast = sub.add_parser("forecast")
    forecast.add_argument("--case")
    forecast.add_argument("--output")
    simulate = sub.add_parser("simulate")
    simulate.add_argument("--case")
    simulate.add_argument("--policy", required=True)
    simulate.add_argument("--scenario", default="baseline")
    simulate.add_argument("--output")
    optimize = sub.add_parser("optimize")
    optimize.add_argument("--case")
    optimize.add_argument("--output-dir", required=True)
    optimize.add_argument("--policy-limit", type=int)
    optimize.add_argument("--replications", type=int)
    audit = sub.add_parser("audit")
    audit.add_argument("--directory", required=True)
    fingerprint = sub.add_parser("fingerprint")
    fingerprint.add_argument("--case")
    self_test = sub.add_parser("self-test")
    self_test.add_argument("--output-dir", required=True)
    return root


def _write(path: str | None, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8", newline="\n")
        print(path)
    else:
        print(text, end="")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            case = load_case(args.case, strict=True)
            result = {"ok": True, "case_id": case["case_id"], "issues": validate_case(case, strict=True)}
            if args.json:
                _write(None, result)
            else:
                print(f"case validation: PASS | services={len(case['service_types'])} staff={len(case['staff'])} scenarios={len(case['scenarios'])}")
            return 0
        if args.command == "forecast":
            _write(args.output, forecast_case(load_case(args.case)))
            return 0
        if args.command == "simulate":
            case = load_case(args.case)
            policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
            scenario = next(item for item in case["scenarios"] if item["id"] == args.scenario)
            _write(args.output, simulate_policy(case, policy, scenario))
            return 0
        if args.command == "optimize":
            case = load_case(args.case)
            plan = optimize_case(case, policy_limit=args.policy_limit, replications=args.replications)
            stress = run_stress(case, plan)
            explanation = explain_plan(case, plan, stress)
            write_outputs(args.output_dir, case, plan, stress, explanation)
            print(json.dumps({"selected_policy_id": plan["selected_policy_id"], "candidate_policy_count": plan["candidate_policy_count"], "feasible_policy_count": plan["feasible_policy_count"], "selection_status": plan["selection_status"]}, sort_keys=True))
            return 0
        if args.command == "audit":
            errors = verify_manifest(args.directory)
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return 0 if not errors else 1
        if args.command == "fingerprint":
            case = load_case(args.case)
            print(stable_hash(case))
            return 0
        if args.command == "self-test":
            case = load_case()
            plan = optimize_case(case, policy_limit=12, replications=1)
            stress = run_stress(case, plan)
            explanation = explain_plan(case, plan, stress)
            write_outputs(args.output_dir, case, plan, stress, explanation)
            errors = verify_manifest(args.output_dir)
            if errors:
                raise ServiceOpsError("; ".join(errors))
            print(json.dumps({"status": "pass", "candidate_policy_count": plan["candidate_policy_count"], "selected_policy_id": plan["selected_policy_id"]}, sort_keys=True))
            return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ServiceOpsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
''')
print("P041 simulation, optimization, reporting and CLI written")
