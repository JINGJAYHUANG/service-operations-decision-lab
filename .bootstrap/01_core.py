from __future__ import annotations

import json
import math
import random
import textwrap
from datetime import date, timedelta
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


write("src/service_ops_lab/__init__.py", '''
"""Synthetic, evidence-first service-operations decision laboratory."""

from .config import load_case, validate_case
from .forecasting import forecast_case
from .optimization import optimize_case
from .simulation import simulate_policy

__all__ = ["forecast_case", "load_case", "optimize_case", "simulate_policy", "validate_case"]
__version__ = "0.1.0"
''')

write("src/service_ops_lab/__main__.py", '''
from .cli import main

raise SystemExit(main())
''')

write("src/service_ops_lab/errors.py", '''
class ServiceOpsError(RuntimeError):
    """Base class for expected project errors."""


class CaseValidationError(ServiceOpsError):
    """The planning case violates its public data contract."""


class SimulationError(ServiceOpsError):
    """A policy simulation violated an invariant."""
''')

write("src/service_ops_lab/util.py", '''
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def percentile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if probability <= 0:
        return ordered[0]
    if probability >= 1:
        return ordered[-1]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def weighted_mean(items: Iterable[tuple[float, float]]) -> float:
    pairs = [(float(value), float(weight)) for value, weight in items]
    denominator = sum(weight for _, weight in pairs)
    return 0.0 if denominator <= 0 else sum(value * weight for value, weight in pairs) / denominator


def weighted_cvar(items: Iterable[tuple[float, float]], alpha: float) -> float:
    pairs = sorted(((float(value), float(weight)) for value, weight in items), reverse=True)
    tail = max(1e-12, 1.0 - float(alpha))
    remaining = tail
    total = 0.0
    used = 0.0
    for value, probability in pairs:
        take = min(max(0.0, probability), remaining)
        total += value * take
        used += take
        remaining -= take
        if remaining <= 1e-12:
            break
    return 0.0 if used <= 0 else total / used


def safe_csv_cell(value: Any) -> Any:
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else value


def flatten_numeric(prefix: str, value: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            result[name] = float(item)
        elif isinstance(item, Mapping):
            result.update(flatten_numeric(name, item))
    return result
''')

write("src/service_ops_lab/models.py", '''
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Policy:
    demand_buffer: float
    flex_staff: int
    overtime_slots: int
    inventory_cover_days: int
    pm_interval_days: int
    quality_level: int
    priority_rule: str

    @property
    def policy_id(self) -> str:
        return (
            f"db{int(self.demand_buffer * 100):02d}-fs{self.flex_staff}-ot{self.overtime_slots}"
            f"-ic{self.inventory_cover_days}-pm{self.pm_interval_days}-q{self.quality_level}"
            f"-{self.priority_rule}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "demand_buffer": self.demand_buffer,
            "flex_staff": self.flex_staff,
            "overtime_slots": self.overtime_slots,
            "inventory_cover_days": self.inventory_cover_days,
            "pm_interval_days": self.pm_interval_days,
            "quality_level": self.quality_level,
            "priority_rule": self.priority_rule,
        }


@dataclass(slots=True)
class Job:
    job_id: str
    service_id: str
    arrival_slot: int
    patience_slots: int
    due_slot: int
    duration_slots: int
    skill: str
    equipment: str
    parts: dict[str, int]
    revisit: bool = False
    start_slot: int | None = None
    completion_slot: int | None = None
    abandoned: bool = False
    stockout_blocked: bool = False


@dataclass(slots=True)
class ActiveJob:
    job: Job
    staff_id: str
    equipment_id: str
    remaining_slots: int
''')

write("src/service_ops_lab/config.py", '''
from __future__ import annotations

import json
import math
from importlib import resources
from pathlib import Path
from typing import Any

from .errors import CaseValidationError

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "case_id",
    "title",
    "as_of",
    "synthetic",
    "horizon",
    "history",
    "service_types",
    "staff",
    "equipment",
    "inventory",
    "scenarios",
    "policy_grid",
    "targets",
    "economics",
    "stress_cases",
    "public_boundary",
}


def load_case(path: str | Path | None = None, *, strict: bool = True) -> dict[str, Any]:
    if path is None:
        text = resources.files("service_ops_lab").joinpath("data", "default_case.json").read_text(encoding="utf-8")
    else:
        text = Path(path).read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise CaseValidationError("case root must be a JSON object")
    issues = validate_case(value, strict=strict)
    if issues:
        raise CaseValidationError("; ".join(issues))
    return value


def validate_case(case: dict[str, Any], *, strict: bool = True) -> list[str]:
    issues: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL - set(case))
    extra = sorted(set(case) - REQUIRED_TOP_LEVEL)
    if missing:
        issues.append("missing top-level fields: " + ", ".join(missing))
    if strict and extra:
        issues.append("unknown top-level fields: " + ", ".join(extra))
    if case.get("schema_version") != 1:
        issues.append("schema_version must equal 1")
    if case.get("synthetic") is not True:
        issues.append("public case must set synthetic=true")
    boundary = case.get("public_boundary", {})
    if not isinstance(boundary, dict) or boundary.get("contains_real_company_data") is not False:
        issues.append("public_boundary.contains_real_company_data must be false")
    if boundary.get("contains_personal_data") is not False:
        issues.append("public_boundary.contains_personal_data must be false")
    if boundary.get("contains_course_material") is not False:
        issues.append("public_boundary.contains_course_material must be false")

    horizon = case.get("horizon", {})
    if not isinstance(horizon, dict) or not isinstance(horizon.get("days"), int) or horizon.get("days", 0) < 7:
        issues.append("horizon.days must be an integer of at least 7")
    if horizon.get("slots_per_day") not in {16, 24, 32, 36, 40, 48}:
        issues.append("horizon.slots_per_day must be an approved 15- or 30-minute operating grid")

    def unique(items: Any, label: str) -> list[dict[str, Any]]:
        if not isinstance(items, list) or not items:
            issues.append(f"{label} must be a non-empty array")
            return []
        rows = [item for item in items if isinstance(item, dict)]
        if len(rows) != len(items):
            issues.append(f"{label} entries must be objects")
        ids = [str(item.get("id", "")) for item in rows]
        if any(not item for item in ids):
            issues.append(f"{label} ids must be non-empty")
        if len(ids) != len(set(ids)):
            issues.append(f"{label} ids must be unique")
        return rows

    services = unique(case.get("service_types"), "service_types")
    staff = unique(case.get("staff"), "staff")
    equipment = unique(case.get("equipment"), "equipment")
    inventory = unique(case.get("inventory"), "inventory")
    scenarios = unique(case.get("scenarios"), "scenarios")
    stress = unique(case.get("stress_cases"), "stress_cases")

    service_ids = {item.get("id") for item in services}
    equipment_ids = {item.get("id") for item in equipment}
    sku_ids = {item.get("id") for item in inventory}
    for item in services:
        if item.get("skill") not in {skill for person in staff for skill in person.get("skills", [])}:
            issues.append(f"service {item.get('id')} requires an unavailable skill")
        if item.get("equipment") not in equipment_ids:
            issues.append(f"service {item.get('id')} references unknown equipment")
        for sku in item.get("parts", {}):
            if sku not in sku_ids:
                issues.append(f"service {item.get('id')} references unknown inventory {sku}")
        for key in ("mean_minutes", "sla_minutes", "patience_minutes", "base_ftr"):
            if key not in item:
                issues.append(f"service {item.get('id')} missing {key}")

    history = case.get("history")
    if not isinstance(history, list) or len(history) < 28:
        issues.append("history must contain at least 28 daily observations")
    else:
        dates = [item.get("date") for item in history if isinstance(item, dict)]
        if len(dates) != len(set(dates)):
            issues.append("history dates must be unique")
        for index, row in enumerate(history):
            if not isinstance(row, dict) or set(row.get("demand", {})) != service_ids:
                issues.append(f"history[{index}] must contain exact service demand keys")

    probability = sum(float(item.get("probability", 0)) for item in scenarios)
    if scenarios and not math.isclose(probability, 1.0, abs_tol=1e-9):
        issues.append(f"scenario probabilities must sum to 1.0, found {probability}")
    if not any(item.get("id") == "baseline" for item in scenarios):
        issues.append("scenarios must include baseline")

    grid = case.get("policy_grid", {})
    required_grid = {
        "demand_buffer",
        "flex_staff",
        "overtime_slots",
        "inventory_cover_days",
        "pm_interval_days",
        "quality_level",
        "priority_rule",
    }
    if not isinstance(grid, dict) or set(grid) != required_grid:
        issues.append("policy_grid must contain the exact seven decision dimensions")
    elif any(not isinstance(grid[key], list) or not grid[key] for key in required_grid):
        issues.append("every policy_grid dimension must be non-empty")

    targets = case.get("targets", {})
    for key in ("expected_completion", "worst_completion", "expected_sla", "minimum_ftr"):
        value = targets.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            issues.append(f"targets.{key} must be between 0 and 1")
    for key in ("maximum_abandonment", "maximum_stockout"):
        value = targets.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            issues.append(f"targets.{key} must be between 0 and 1")
    if targets.get("maximum_p90_wait_minutes", 0) <= 0:
        issues.append("targets.maximum_p90_wait_minutes must be positive")
    if not isinstance(targets.get("service_completion_minimums"), dict) or set(targets.get("service_completion_minimums", {})) != service_ids:
        issues.append("service completion minimums must cover every service type")

    for person in staff:
        if not person.get("skills"):
            issues.append(f"staff {person.get('id')} must have at least one skill")
        if person.get("daily_slots", 0) <= 0:
            issues.append(f"staff {person.get('id')} daily_slots must be positive")
    for item in equipment:
        if item.get("units", 0) <= 0 or item.get("failure_probability", -1) < 0:
            issues.append(f"equipment {item.get('id')} has invalid units or failure probability")
    for item in inventory:
        if item.get("initial_on_hand", -1) < 0 or item.get("lead_time_days", -1) < 0 or item.get("pack_size", 0) <= 0:
            issues.append(f"inventory {item.get('id')} has invalid stock, lead time, or pack size")
    if len(stress) < 6:
        issues.append("at least six stress cases are required")
    return issues
''')

write("src/service_ops_lab/forecasting.py", '''
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable

from .util import percentile


def _seasonal_naive(history: list[float], horizon: int) -> list[float]:
    if len(history) < 7:
        return [history[-1] if history else 0.0] * horizon
    return [max(0.0, history[len(history) - 7 + (index % 7)]) for index in range(horizon)]


def _moving_average(history: list[float], horizon: int, window: int = 7) -> list[float]:
    level = sum(history[-window:]) / min(window, len(history)) if history else 0.0
    return [max(0.0, level)] * horizon


def _damped_trend(history: list[float], horizon: int) -> list[float]:
    if not history:
        return [0.0] * horizon
    recent = history[-14:] if len(history) >= 14 else history
    level = sum(recent[-7:]) / min(7, len(recent))
    previous = sum(recent[:-7]) / max(1, len(recent) - min(7, len(recent))) if len(recent) > 7 else level
    trend = (level - previous) / 7.0
    damping = 0.82
    return [max(0.0, level + trend * sum(damping ** step for step in range(1, index + 2))) for index in range(horizon)]


def _weekday_profile(history: list[float], horizon: int) -> list[float]:
    if not history:
        return [0.0] * horizon
    buckets: dict[int, list[float]] = defaultdict(list)
    start_weekday = (-len(history)) % 7
    for index, value in enumerate(history):
        buckets[(start_weekday + index) % 7].append(value)
    overall = sum(history) / len(history)
    return [max(0.0, sum(buckets.get(index % 7, [overall])) / len(buckets.get(index % 7, [overall]))) for index in range(horizon)]


MODELS: dict[str, Callable[[list[float], int], list[float]]] = {
    "seasonal-naive": _seasonal_naive,
    "moving-average-7": _moving_average,
    "damped-trend": _damped_trend,
    "weekday-profile": _weekday_profile,
}


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    errors = [forecast - observed for observed, forecast in zip(actual, predicted, strict=True)]
    absolute = [abs(value) for value in errors]
    denominator = sum(abs(value) for value in actual)
    return {
        "wape": 0.0 if denominator == 0 else sum(absolute) / denominator,
        "mae": 0.0 if not absolute else sum(absolute) / len(absolute),
        "bias": 0.0 if not errors else sum(errors) / len(errors),
        "residual_sd": 0.0 if len(errors) < 2 else math.sqrt(sum((value - sum(errors) / len(errors)) ** 2 for value in errors) / (len(errors) - 1)),
    }


def rolling_origin(series: list[float], model: Callable[[list[float], int], list[float]], *, minimum_train: int = 21) -> dict[str, float]:
    actual: list[float] = []
    predicted: list[float] = []
    for split in range(minimum_train, len(series)):
        forecast = model(series[:split], 1)[0]
        actual.append(series[split])
        predicted.append(forecast)
    return _metrics(actual, predicted)


def forecast_case(case: dict[str, Any]) -> dict[str, Any]:
    horizon = int(case["horizon"]["days"])
    history_by_service: dict[str, list[float]] = {item["id"]: [] for item in case["service_types"]}
    for row in case["history"]:
        for service_id, value in row["demand"].items():
            history_by_service[service_id].append(float(value))
    results: dict[str, Any] = {}
    for service_id, series in history_by_service.items():
        candidates = {}
        for name, model in MODELS.items():
            diagnostics = rolling_origin(series, model)
            diagnostics["selection_loss"] = diagnostics["wape"] + 0.20 * abs(diagnostics["bias"]) / max(1.0, sum(series) / len(series))
            candidates[name] = diagnostics
        selected = min(candidates, key=lambda name: (candidates[name]["selection_loss"], name))
        point = MODELS[selected](series, horizon)
        residual_sd = candidates[selected]["residual_sd"]
        results[service_id] = {
            "selected_model": selected,
            "diagnostics": candidates,
            "point_forecast": [round(value, 4) for value in point],
            "p50": [round(max(0.0, value), 4) for value in point],
            "p80": [round(max(0.0, value + 0.841621 * residual_sd), 4) for value in point],
            "p95": [round(max(0.0, value + 1.644854 * residual_sd), 4) for value in point],
            "history_last_14": [round(value, 4) for value in series[-14:]],
        }
    return {"schema_version": 1, "case_id": case["case_id"], "horizon_days": horizon, "services": results}
''')

write("src/service_ops_lab/inventory.py", '''
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


class InventoryState:
    def __init__(self, items: list[dict[str, Any]], cover_days: int):
        self.catalog = {item["id"]: item for item in items}
        self.on_hand = {item["id"]: int(item["initial_on_hand"]) for item in items}
        self.cover_days = int(cover_days)
        self.pipeline: dict[int, list[tuple[str, int]]] = defaultdict(list)
        self.orders: list[dict[str, Any]] = []
        self.consumed = {item["id"]: 0 for item in items}
        self.received = {item["id"]: 0 for item in items}
        self.shortage_units = {item["id"]: 0 for item in items}
        self.holding_unit_days = {item["id"]: 0 for item in items}
        self.cost = 0.0

    def begin_day(self, day: int) -> None:
        for sku, quantity in self.pipeline.pop(day, []):
            self.on_hand[sku] += quantity
            self.received[sku] += quantity

    def can_consume(self, parts: dict[str, int]) -> bool:
        return all(self.on_hand.get(sku, 0) >= quantity for sku, quantity in parts.items())

    def consume(self, parts: dict[str, int]) -> bool:
        if not self.can_consume(parts):
            for sku, quantity in parts.items():
                self.shortage_units[sku] += max(0, quantity - self.on_hand.get(sku, 0))
            return False
        for sku, quantity in parts.items():
            self.on_hand[sku] -= quantity
            self.consumed[sku] += quantity
        return True

    def reorder(self, day: int, expected_daily_use: dict[str, float]) -> None:
        for sku, item in self.catalog.items():
            pipeline = sum(quantity for arrivals in self.pipeline.values() for item_sku, quantity in arrivals if item_sku == sku)
            target = max(float(item["reorder_point"]), expected_daily_use.get(sku, 0.0) * self.cover_days)
            position = self.on_hand[sku] + pipeline
            if position >= target:
                continue
            pack = int(item["pack_size"])
            quantity = int(math.ceil((target - position) / pack) * pack)
            arrival = day + int(item["lead_time_days"])
            self.pipeline[arrival].append((sku, quantity))
            self.orders.append({"day": day, "arrival_day": arrival, "sku": sku, "quantity": quantity})
            self.cost += float(item["order_cost"]) + quantity * float(item["unit_cost"])

    def end_day(self) -> None:
        for sku, quantity in self.on_hand.items():
            self.holding_unit_days[sku] += quantity
            self.cost += quantity * float(self.catalog[sku]["holding_cost_per_day"])

    def summary(self) -> dict[str, Any]:
        opening = {sku: int(item["initial_on_hand"]) for sku, item in self.catalog.items()}
        ending = dict(self.on_hand)
        balance = {
            sku: opening[sku] + self.received[sku] - self.consumed[sku] - ending[sku]
            for sku in self.catalog
        }
        return {
            "opening": opening,
            "received": dict(self.received),
            "consumed": dict(self.consumed),
            "ending": ending,
            "shortage_units": dict(self.shortage_units),
            "holding_unit_days": dict(self.holding_unit_days),
            "orders": list(self.orders),
            "inventory_cost": round(self.cost, 4),
            "balance_error": balance,
        }
''')

write("src/service_ops_lab/reliability.py", '''
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class EquipmentUnit:
    unit_id: str
    equipment_type: str
    down_until_slot: int = -1
    last_pm_day: int = -999
    failures: int = 0
    pm_events: int = 0
    downtime_slots: int = 0


def build_units(equipment: list[dict[str, Any]]) -> list[EquipmentUnit]:
    return [EquipmentUnit(f"{item['id']}-{index + 1}", item["id"]) for item in equipment for index in range(int(item["units"]))]


def begin_day(units: list[EquipmentUnit], catalog: dict[str, dict[str, Any]], day: int, slots_per_day: int, pm_interval_days: int) -> None:
    for unit in units:
        item = catalog[unit.equipment_type]
        if day - unit.last_pm_day >= pm_interval_days:
            unit.down_until_slot = max(unit.down_until_slot, day * slots_per_day + int(item["pm_duration_slots"]))
            unit.last_pm_day = day
            unit.pm_events += 1
            unit.downtime_slots += int(item["pm_duration_slots"])


def available_unit(units: list[EquipmentUnit], equipment_type: str, absolute_slot: int) -> EquipmentUnit | None:
    candidates = [unit for unit in units if unit.equipment_type == equipment_type and unit.down_until_slot <= absolute_slot]
    return min(candidates, key=lambda unit: unit.unit_id) if candidates else None


def maybe_fail(unit: EquipmentUnit, item: dict[str, Any], scenario_multiplier: float, rng: random.Random, absolute_slot: int) -> None:
    probability = min(0.95, max(0.0, float(item["failure_probability"]) * scenario_multiplier))
    if rng.random() < probability:
        downtime = max(1, int(round(float(item["repair_slots"]) * max(0.5, scenario_multiplier))))
        unit.down_until_slot = max(unit.down_until_slot, absolute_slot + downtime)
        unit.failures += 1
        unit.downtime_slots += downtime


def summary(units: list[EquipmentUnit]) -> dict[str, Any]:
    return {
        "failures": sum(unit.failures for unit in units),
        "pm_events": sum(unit.pm_events for unit in units),
        "downtime_slots": sum(unit.downtime_slots for unit in units),
        "by_unit": [
            {
                "unit_id": unit.unit_id,
                "equipment_type": unit.equipment_type,
                "failures": unit.failures,
                "pm_events": unit.pm_events,
                "downtime_slots": unit.downtime_slots,
            }
            for unit in units
        ],
    }
''')

# Deterministic synthetic case generator.
service_types = [
    {
        "id": "preventive-care",
        "skill": "care",
        "equipment": "mobile-kit",
        "parts": {"filter-set": 1},
        "mean_minutes": 52,
        "duration_cv": 0.28,
        "sla_minutes": 45,
        "patience_minutes": 70,
        "base_ftr": 0.91,
        "revisit_delay_days": 3,
        "appointment_share": 0.72,
        "no_show_rate": 0.07,
        "priority": 2,
    },
    {
        "id": "diagnostic-repair",
        "skill": "diagnostic",
        "equipment": "diagnostic-bench",
        "parts": {"sensor-pack": 1, "seal-kit": 1},
        "mean_minutes": 94,
        "duration_cv": 0.42,
        "sla_minutes": 75,
        "patience_minutes": 110,
        "base_ftr": 0.84,
        "revisit_delay_days": 4,
        "appointment_share": 0.60,
        "no_show_rate": 0.05,
        "priority": 1,
    },
    {
        "id": "urgent-restoration",
        "skill": "restoration",
        "equipment": "mobile-kit",
        "parts": {"seal-kit": 1, "emergency-module": 1},
        "mean_minutes": 72,
        "duration_cv": 0.36,
        "sla_minutes": 30,
        "patience_minutes": 40,
        "base_ftr": 0.87,
        "revisit_delay_days": 2,
        "appointment_share": 0.18,
        "no_show_rate": 0.01,
        "priority": 3,
    },
]
start = date(2026, 1, 5)
rng = random.Random(410064)
history = []
base = {"preventive-care": 7.4, "diagnostic-repair": 5.1, "urgent-restoration": 3.0}
weekday_effect = [1.12, 1.06, 1.02, 1.00, 0.94, 0.65, 0.48]
for index in range(56):
    current = start + timedelta(days=index)
    demand = {}
    for service_id, level in base.items():
        trend = 1.0 + index * (0.0015 if service_id != "urgent-restoration" else 0.0007)
        noise = rng.gauss(0, 0.65 if service_id != "urgent-restoration" else 0.45)
        demand[service_id] = max(0, int(round(level * weekday_effect[current.weekday()] * trend + noise)))
    history.append({"date": current.isoformat(), "demand": demand})

case = {
    "schema_version": 1,
    "case_id": "northstar-service-hub-v1",
    "title": "Northstar Service Hub — Synthetic Integrated Operations Case",
    "as_of": "2026-08-31",
    "synthetic": True,
    "horizon": {"start_date": "2026-09-07", "days": 21, "slot_minutes": 15, "slots_per_day": 32, "replications": 2},
    "history": history,
    "service_types": service_types,
    "staff": [
        {"id": "staff-a", "skills": ["care", "restoration"], "daily_slots": 32, "absence_probability": 0.015, "cost_per_slot": 7.8},
        {"id": "staff-b", "skills": ["diagnostic"], "daily_slots": 32, "absence_probability": 0.020, "cost_per_slot": 8.5},
        {"id": "staff-c", "skills": ["care", "diagnostic"], "daily_slots": 32, "absence_probability": 0.025, "cost_per_slot": 8.2},
        {"id": "staff-d", "skills": ["restoration", "diagnostic"], "daily_slots": 32, "absence_probability": 0.018, "cost_per_slot": 8.8},
        {"id": "staff-e", "skills": ["care"], "daily_slots": 28, "absence_probability": 0.030, "cost_per_slot": 7.4},
    ],
    "equipment": [
        {"id": "mobile-kit", "units": 3, "failure_probability": 0.0018, "repair_slots": 8, "pm_duration_slots": 2, "failure_cost": 210, "pm_cost": 36},
        {"id": "diagnostic-bench", "units": 2, "failure_probability": 0.0024, "repair_slots": 12, "pm_duration_slots": 3, "failure_cost": 320, "pm_cost": 55},
    ],
    "inventory": [
        {"id": "filter-set", "initial_on_hand": 95, "reorder_point": 30, "lead_time_days": 3, "pack_size": 20, "unit_cost": 8.2, "order_cost": 18, "holding_cost_per_day": 0.025},
        {"id": "sensor-pack", "initial_on_hand": 74, "reorder_point": 24, "lead_time_days": 4, "pack_size": 12, "unit_cost": 21.5, "order_cost": 24, "holding_cost_per_day": 0.055},
        {"id": "seal-kit", "initial_on_hand": 105, "reorder_point": 36, "lead_time_days": 2, "pack_size": 24, "unit_cost": 6.8, "order_cost": 16, "holding_cost_per_day": 0.020},
        {"id": "emergency-module", "initial_on_hand": 52, "reorder_point": 18, "lead_time_days": 5, "pack_size": 10, "unit_cost": 34.0, "order_cost": 28, "holding_cost_per_day": 0.075},
    ],
    "scenarios": [
        {"id": "baseline", "probability": 0.40, "demand_multiplier": 1.00, "service_time_multiplier": 1.00, "absence_multiplier": 1.00, "failure_multiplier": 1.00, "lead_time_shift": 0, "quality_shift": 0.00},
        {"id": "demand-surge", "probability": 0.20, "demand_multiplier": 1.22, "service_time_multiplier": 1.02, "absence_multiplier": 1.00, "failure_multiplier": 1.00, "lead_time_shift": 0, "quality_shift": -0.01},
        {"id": "slow-service", "probability": 0.15, "demand_multiplier": 1.02, "service_time_multiplier": 1.24, "absence_multiplier": 1.15, "failure_multiplier": 1.20, "lead_time_shift": 0, "quality_shift": -0.025},
        {"id": "supply-disruption", "probability": 0.15, "demand_multiplier": 1.00, "service_time_multiplier": 1.04, "absence_multiplier": 1.00, "failure_multiplier": 1.10, "lead_time_shift": 3, "quality_shift": -0.01},
        {"id": "compound-downside", "probability": 0.10, "demand_multiplier": 1.16, "service_time_multiplier": 1.18, "absence_multiplier": 1.30, "failure_multiplier": 1.45, "lead_time_shift": 2, "quality_shift": -0.04},
    ],
    "policy_grid": {
        "demand_buffer": [0.00, 0.10, 0.20],
        "flex_staff": [0, 1],
        "overtime_slots": [0, 4],
        "inventory_cover_days": [1, 3],
        "pm_interval_days": [5, 9],
        "quality_level": [0, 1],
        "priority_rule": ["fifo", "sla", "shortest"],
    },
    "targets": {
        "expected_completion": 0.88,
        "worst_completion": 0.70,
        "expected_sla": 0.74,
        "minimum_ftr": 0.82,
        "maximum_abandonment": 0.12,
        "maximum_stockout": 0.08,
        "maximum_p90_wait_minutes": 72,
        "service_completion_minimums": {"preventive-care": 0.82, "diagnostic-repair": 0.75, "urgent-restoration": 0.78},
        "cvar_alpha": 0.80,
        "risk_aversion": 0.18,
    },
    "economics": {
        "completion_revenue": {"preventive-care": 112, "diagnostic-repair": 195, "urgent-restoration": 168},
        "abandonment_cost": 78,
        "backlog_cost_per_job_day": 16,
        "sla_miss_cost": 24,
        "revisit_cost": 58,
        "overtime_cost_per_slot": 12.5,
        "flex_staff_cost_per_slot": 10.5,
        "quality_program_daily_cost": 62,
        "stockout_cost_per_unit": 18,
        "wait_cost_per_minute": 0.16,
    },
    "stress_cases": [
        {"id": "demand-spike", "overrides": {"demand_multiplier": 1.35}},
        {"id": "slow-processing", "overrides": {"service_time_multiplier": 1.35}},
        {"id": "absence-shock", "overrides": {"absence_multiplier": 2.20}},
        {"id": "equipment-shock", "overrides": {"failure_multiplier": 2.40}},
        {"id": "supply-delay", "overrides": {"lead_time_shift": 5}},
        {"id": "quality-drift", "overrides": {"quality_shift": -0.09}},
        {"id": "urgent-mix-shift", "overrides": {"urgent_mix_multiplier": 1.70}},
        {"id": "compound-stress", "overrides": {"demand_multiplier": 1.28, "service_time_multiplier": 1.24, "absence_multiplier": 1.80, "failure_multiplier": 1.80, "lead_time_shift": 3, "quality_shift": -0.06}},
    ],
    "public_boundary": {
        "contains_real_company_data": False,
        "contains_personal_data": False,
        "contains_course_material": False,
        "contains_real_customer_data": False,
        "contains_real_employee_data": False,
        "contains_real_financial_data": False,
        "contains_production_recommendation": False,
        "notes": "All names, dates, demand, staffing, quality, equipment, inventory, cost and performance values are synthetic.",
    },
}
write_json("examples/cases/northstar-service-hub.json", case)
write_json("src/service_ops_lab/data/default_case.json", case)
print("P041 core source and synthetic case written")
