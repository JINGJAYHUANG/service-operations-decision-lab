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


# JSON Schemas provide editor-level structure; Python validation remains authoritative for cross-field semantics.
schemas = {
    "case.schema.json": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.org/service-ops-lab/case.schema.json",
        "title": "Synthetic service operations case",
        "type": "object",
        "required": ["schema_version", "case_id", "synthetic", "horizon", "history", "service_types", "staff", "equipment", "inventory", "scenarios", "policy_grid", "targets", "economics", "stress_cases", "public_boundary"],
        "properties": {"schema_version": {"const": 1}, "case_id": {"type": "string"}, "synthetic": {"const": True}, "horizon": {"type": "object"}, "history": {"type": "array", "minItems": 28}, "service_types": {"type": "array", "minItems": 1}, "staff": {"type": "array", "minItems": 1}, "equipment": {"type": "array", "minItems": 1}, "inventory": {"type": "array", "minItems": 1}, "scenarios": {"type": "array", "minItems": 1}, "policy_grid": {"type": "object"}, "targets": {"type": "object"}, "economics": {"type": "object"}, "stress_cases": {"type": "array", "minItems": 6}, "public_boundary": {"type": "object"}},
    },
    "forecast.schema.json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://example.org/service-ops-lab/forecast.schema.json", "type": "object", "required": ["schema_version", "case_id", "horizon_days", "services"]},
    "simulation-result.schema.json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://example.org/service-ops-lab/simulation-result.schema.json", "type": "object", "required": ["schema_version", "case_id", "policy", "scenario_id", "metrics", "service_metrics", "inventory", "reliability", "conservation", "boundary"]},
    "plan.schema.json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://example.org/service-ops-lab/plan.schema.json", "type": "object", "required": ["schema_version", "case_id", "candidate_policy_count", "feasible_policy_count", "selection_status", "selected_policy_id", "selected", "pareto_frontier", "policy_catalog", "forecast", "boundary"]},
    "stress.schema.json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://example.org/service-ops-lab/stress.schema.json", "type": "object", "required": ["schema_version", "case_id", "selected_policy_id", "stress_case_count", "results", "boundary"]},
    "explanation.schema.json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://example.org/service-ops-lab/explanation.schema.json", "type": "object", "required": ["schema_version", "case_id", "selected_policy_id", "selection_status", "managerial_summary", "recommended_review_sequence", "model_limits"]},
    "artifact-manifest.schema.json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://example.org/service-ops-lab/artifact-manifest.schema.json", "type": "object", "required": ["schema_version", "algorithm", "files"], "properties": {"schema_version": {"const": 1}, "algorithm": {"const": "sha256"}, "files": {"type": "object"}}},
}
for name, schema in schemas.items():
    write_json(f"schemas/{name}", schema)

write("tools/generate_examples.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import filecmp
import shutil
import tempfile
from pathlib import Path

from service_ops_lab.config import load_case
from service_ops_lab.explain import explain_plan
from service_ops_lab.optimization import optimize_case
from service_ops_lab.reporting import write_outputs
from service_ops_lab.stress import run_stress

ROOT = Path(__file__).resolve().parents[1]


def generate(output: Path) -> None:
    case = load_case(ROOT / "examples/cases/northstar-service-hub.json", strict=True)
    plan = optimize_case(case)
    stress = run_stress(case, plan)
    explanation = explain_plan(case, plan, stress)
    write_outputs(output, case, plan, stress, explanation)


def compare_directories(left: Path, right: Path) -> list[str]:
    errors = []
    left_files = {path.relative_to(left).as_posix() for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right).as_posix() for path in right.rglob("*") if path.is_file()}
    if left_files != right_files:
        errors.append(f"file set differs: expected={sorted(left_files)} actual={sorted(right_files)}")
    for name in sorted(left_files & right_files):
        if (left / name).read_bytes() != (right / name).read_bytes():
            errors.append(f"generated artifact drift: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "examples/generated"))
    args = parser.parse_args()
    target = Path(args.output)
    if args.check:
        with tempfile.TemporaryDirectory() as temporary:
            fresh = Path(temporary) / "generated"
            generate(fresh)
            errors = compare_directories(target, fresh)
            if errors:
                print("\n".join(errors))
                return 1
        print("generated examples are current")
        return 0
    shutil.rmtree(target, ignore_errors=True)
    generate(target)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tools/audit_html.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path


class AuditParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors: list[str] = []
        self.h1 = 0
        self.main = 0
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "h1":
            self.h1 += 1
        if tag == "main":
            self.main += 1
        if tag in {"script", "iframe", "object", "embed", "form"}:
            self.errors.append(f"forbidden element: {tag}")
        for key, value in attrs:
            if key.lower().startswith("on"):
                self.errors.append(f"inline event handler: {key}")
            if key in {"src", "href"} and isinstance(value, str) and value.startswith(("http://", "https://", "//")):
                self.errors.append(f"remote runtime resource: {value}")
        identifier = values.get("id")
        if identifier:
            if identifier in self.ids:
                self.errors.append(f"duplicate id: {identifier}")
            self.ids.add(identifier)


def audit(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    parser = AuditParser()
    parser.feed(text)
    if parser.h1 != 1:
        parser.errors.append(f"expected exactly one h1, found {parser.h1}")
    if parser.main != 1:
        parser.errors.append(f"expected exactly one main, found {parser.main}")
    if "@media" not in text or "@media print" not in text:
        parser.errors.append("responsive or print CSS is missing")
    if "Synthetic integrated service-operations lab" not in text:
        parser.errors.append("synthetic boundary banner is missing")
    return parser.errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    errors = audit(Path(args.path))
    if errors:
        print("HTML audit failed:\n" + "\n".join(errors))
        return 1
    print("HTML audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tools/check_docs.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors = []
    count = 0
    for path in sorted(root.rglob("*.md")):
        if any(part in {".git", ".venv", "build", "dist"} for part in path.relative_to(root).parts):
            continue
        count += 1
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = target.split("#", 1)[0]
            if clean and not (path.parent / clean).resolve().exists():
                errors.append(f"{path.relative_to(root)} -> {target}")
    if errors:
        print("broken local documentation links:\n" + "\n".join(errors))
        return 1
    print(f"documentation check passed: {count} Markdown file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tools/public_audit.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP = {".git", ".venv", "dist", "build", "__pycache__", ".pytest_cache"}
TEXT = {"", ".cff", ".csv", ".html", ".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    "api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{30,}\b"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "personal_email": re.compile(r"\b[A-Z0-9._%+-]+@(?!users\.noreply\.github\.com\b|example\.(?:com|org|invalid)\b)[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "windows_home": re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+"),
    "mac_home": re.compile(r"(?<![\w.-])/" + r"Users/[^/\s]+"),
    "linux_home": re.compile(r"(?<![\w.-])/" + r"home/[^/\s]+"),
}
FORBIDDEN = {
    "legacy_course_case": "Hazel" + "'s Lawn Care",
    "private_strategy_repo": "goal49" + "-cloud-morning",
    "private_incubator_repo": "JINGJAYHUANG/" + "try",
}


def scan(root: Path):
    findings = []
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP for part in path.relative_to(root).parts) or path.suffix.lower() not in TEXT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        count += 1
        for number, line in enumerate(text.splitlines(), 1):
            for code, pattern in PATTERNS.items():
                match = pattern.search(line)
                if match:
                    findings.append((code, path.relative_to(root).as_posix(), number, match.group(0)[:100]))
            for code, marker in FORBIDDEN.items():
                if marker in line:
                    findings.append((code, path.relative_to(root).as_posix(), number, marker))
    return count, findings


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    count, findings = scan(root)
    if findings:
        print(f"public audit failed: {len(findings)} finding(s) in {count} file(s)")
        for item in findings:
            print(f"{item[0]} {item[1]}:{item[2]} {item[3]}")
        return 1
    print(f"public audit passed: {count} text file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tools/check_workflows.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ACTION = re.compile(r"(?m)^\s*(?:-\s*)?uses:\s*[^#\s]+@([^\s#]+)")
RUN = re.compile(r"^(?P<indent>\s*)(?:-\s*)?run:\s*\|[-+]?\s*$")
HEREDOC = re.compile(r"(?:^|\s)python(?:[0-9.]*)?\s+-\s+<<-?['\"]?(?P<tag>[A-Za-z_][A-Za-z0-9_]*)['\"]?\s*$")


def blocks(text: str):
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = RUN.match(lines[index])
        if not match:
            index += 1
            continue
        base = len(match.group("indent"))
        index += 1
        values = []
        while index < len(lines) and (not lines[index].strip() or len(lines[index]) - len(lines[index].lstrip(" ")) > base):
            values.append(lines[index])
            index += 1
        indent = min((len(line) - len(line.lstrip(" ")) for line in values if line.strip()), default=base + 2)
        yield "\n".join(line[indent:] if line.strip() else "" for line in values) + "\n"


def check(root: Path) -> list[str]:
    errors = []
    paths = sorted([*(root / ".github/workflows").glob("*.yml"), *(root / ".github/workflows").glob("*.yaml")])
    if not paths:
        return ["no workflow files found"]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for reference in ACTION.findall(text):
            if not re.fullmatch(r"[0-9a-f]{40}", reference):
                errors.append(f"{path}: unpinned action {reference}")
        for script in blocks(text):
            sanitized = re.sub(r"\$\{\{.*?\}\}", "GITHUB_EXPRESSION", script)
            if shutil.which("bash"):
                with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as handle:
                    handle.write(sanitized)
                    temporary = Path(handle.name)
                result = subprocess.run(["bash", "-n", str(temporary)], text=True, capture_output=True)
                temporary.unlink(missing_ok=True)
                if result.returncode:
                    errors.append(f"{path}: bash syntax: {result.stderr.strip()}")
            lines = script.splitlines()
            index = 0
            while index < len(lines):
                match = HEREDOC.search(lines[index])
                if not match:
                    index += 1
                    continue
                tag = match.group("tag")
                body = []
                index += 1
                while index < len(lines) and lines[index].strip() != tag:
                    body.append(lines[index])
                    index += 1
                if index >= len(lines):
                    errors.append(f"{path}: unterminated Python heredoc {tag}")
                    break
                try:
                    compile("\n".join(body) + "\n", f"{path}:{tag}", "exec")
                except SyntaxError as exc:
                    errors.append(f"{path}: embedded Python syntax: {exc}")
                index += 1
    return errors


def main() -> int:
    errors = check(Path(".").resolve())
    if errors:
        print("workflow check failed:\n" + "\n".join(errors))
        return 1
    print("workflow check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tools/check_schema_parity.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

EXPECTED = {
    "case.schema.json": {"schema_version", "case_id", "synthetic", "horizon", "history", "service_types", "staff", "equipment", "inventory", "scenarios", "policy_grid", "targets", "economics", "stress_cases", "public_boundary"},
    "forecast.schema.json": {"schema_version", "case_id", "horizon_days", "services"},
    "simulation-result.schema.json": {"schema_version", "case_id", "policy", "scenario_id", "metrics", "service_metrics", "inventory", "reliability", "conservation", "boundary"},
    "plan.schema.json": {"schema_version", "case_id", "candidate_policy_count", "feasible_policy_count", "selection_status", "selected_policy_id", "selected", "pareto_frontier", "policy_catalog", "forecast", "boundary"},
    "stress.schema.json": {"schema_version", "case_id", "selected_policy_id", "stress_case_count", "results", "boundary"},
    "explanation.schema.json": {"schema_version", "case_id", "selected_policy_id", "selection_status", "managerial_summary", "recommended_review_sequence", "model_limits"},
    "artifact-manifest.schema.json": {"schema_version", "algorithm", "files"},
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = []
    actual = {path.name for path in (root / "schemas").glob("*.json")}
    if actual != set(EXPECTED):
        errors.append(f"schema file set differs: {sorted(actual)}")
    for name, fields in EXPECTED.items():
        schema = json.loads((root / "schemas" / name).read_text(encoding="utf-8"))
        if set(schema.get("required", [])) != fields:
            errors.append(f"{name}: required fields differ")
    if errors:
        print("schema parity failed:\n" + "\n".join(errors))
        return 1
    print(f"schema parity passed: {len(EXPECTED)} schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tools/check_version.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    package = re.search(r'^__version__ = "([^"]+)"$', (root / "src/service_ops_lab/__init__.py").read_text(encoding="utf-8"), re.M).group(1)
    citation = re.search(r'^version: "([^"]+)"$', (root / "CITATION.cff").read_text(encoding="utf-8"), re.M).group(1)
    origin = json.loads((root / "ORIGIN_MANIFEST.json").read_text(encoding="utf-8"))["version"]
    values = {"project": project, "package": package, "citation": citation, "origin": origin}
    if len(set(values.values())) != 1:
        print(values)
        return 1
    print(values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tools/check_origin.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    value = json.loads((root / "ORIGIN_MANIFEST.json").read_text(encoding="utf-8"))
    required = {"course prompt or case text", "real company identity", "real customer or employee records", "real demand, quality, maintenance, inventory, staffing or financial data"}
    if not required.issubset(set(value.get("excluded", []))):
        print("origin manifest exclusions are incomplete")
        return 1
    if value.get("assets", {}).get("case_data") != "deterministic synthetic fixture":
        print("case origin is not declared synthetic")
        return 1
    print("origin manifest passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tools/release_check.py", '''
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from service_ops_lab.artifacts import verify_manifest
from service_ops_lab.config import load_case

ROOT = Path(__file__).resolve().parents[1]


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    load_case(ROOT / "examples/cases/northstar-service-hub.json", strict=True)
    run(sys.executable, "-m", "compileall", "-q", "src", "tools", "tests")
    run(sys.executable, "tools/check_version.py")
    run(sys.executable, "tools/generate_examples.py", "--check")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    run(sys.executable, "tools/audit_html.py", "examples/generated/decision-lab.html")
    run(sys.executable, "tools/check_schema_parity.py")
    run(sys.executable, "tools/check_docs.py", ".")
    run(sys.executable, "tools/check_workflows.py")
    run(sys.executable, "tools/check_origin.py")
    run(sys.executable, "tools/public_audit.py", ".")
    errors = verify_manifest(ROOT / "examples/generated")
    if errors:
        raise SystemExit("; ".join(errors))
    plan = json.loads((ROOT / "examples/generated/plan.json").read_text(encoding="utf-8"))
    if plan["candidate_policy_count"] != 288:
        raise SystemExit("expected 288 generated policies")
    if not plan["pareto_frontier"]:
        raise SystemExit("Pareto frontier is empty")
    print("release gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')

write("tests/helpers.py", '''
from __future__ import annotations

import json
from pathlib import Path

from service_ops_lab.config import load_case

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "examples/cases/northstar-service-hub.json"
GENERATED = ROOT / "examples/generated"


def case():
    return load_case(CASE_PATH, strict=True)


def generated(name: str):
    return json.loads((GENERATED / name).read_text(encoding="utf-8"))
''')

write("tests/test_config.py", '''
from __future__ import annotations

import copy
import unittest

from service_ops_lab.config import load_case, validate_case
from helpers import CASE_PATH, case


class ConfigTests(unittest.TestCase):
    def test_case_is_strictly_valid(self):
        self.assertEqual(validate_case(case(), strict=True), [])

    def test_packaged_case_matches_public_case(self):
        self.assertEqual(load_case(), case())

    def test_case_is_synthetic(self):
        self.assertTrue(case()["synthetic"])

    def test_horizon_is_21_days(self):
        self.assertEqual(case()["horizon"]["days"], 21)

    def test_history_is_56_days(self):
        self.assertEqual(len(case()["history"]), 56)

    def test_three_services(self):
        self.assertEqual(len(case()["service_types"]), 3)

    def test_five_staff(self):
        self.assertEqual(len(case()["staff"]), 5)

    def test_four_skus(self):
        self.assertEqual(len(case()["inventory"]), 4)

    def test_five_scenarios(self):
        self.assertEqual(len(case()["scenarios"]), 5)

    def test_probabilities_sum_to_one(self):
        self.assertAlmostEqual(sum(item["probability"] for item in case()["scenarios"]), 1.0)

    def test_eight_stress_cases(self):
        self.assertEqual(len(case()["stress_cases"]), 8)

    def test_policy_grid_is_288(self):
        result = 1
        for values in case()["policy_grid"].values():
            result *= len(values)
        self.assertEqual(result, 288)

    def test_missing_top_level_rejected(self):
        value = case(); value.pop("targets")
        self.assertTrue(validate_case(value, strict=True))

    def test_unknown_top_level_rejected_in_strict_mode(self):
        value = case(); value["invented"] = True
        self.assertTrue(validate_case(value, strict=True))

    def test_duplicate_service_rejected(self):
        value = case(); value["service_types"].append(copy.deepcopy(value["service_types"][0]))
        self.assertTrue(any("unique" in item for item in validate_case(value)))

    def test_bad_scenario_probability_rejected(self):
        value = case(); value["scenarios"][0]["probability"] += 0.1
        self.assertTrue(any("probabilities" in item for item in validate_case(value)))

    def test_unknown_part_rejected(self):
        value = case(); value["service_types"][0]["parts"]["missing"] = 1
        self.assertTrue(any("unknown inventory" in item for item in validate_case(value)))

    def test_real_company_flag_rejected(self):
        value = case(); value["public_boundary"]["contains_real_company_data"] = True
        self.assertTrue(validate_case(value))

    def test_course_material_flag_rejected(self):
        value = case(); value["public_boundary"]["contains_course_material"] = True
        self.assertTrue(validate_case(value))

    def test_empty_grid_dimension_rejected(self):
        value = case(); value["policy_grid"]["quality_level"] = []
        self.assertTrue(validate_case(value))


if __name__ == "__main__":
    unittest.main()
''')

write("tests/test_forecasting.py", '''
from __future__ import annotations

import unittest

from service_ops_lab.forecasting import MODELS, forecast_case, rolling_origin
from helpers import case


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.case = case()
        self.result = forecast_case(self.case)

    def test_four_models_exist(self):
        self.assertEqual(set(MODELS), {"seasonal-naive", "moving-average-7", "damped-trend", "weekday-profile"})

    def test_every_service_forecasted(self):
        self.assertEqual(set(self.result["services"]), {item["id"] for item in self.case["service_types"]})

    def test_horizon_length(self):
        for value in self.result["services"].values():
            self.assertEqual(len(value["point_forecast"]), 21)

    def test_forecasts_are_nonnegative(self):
        for value in self.result["services"].values():
            self.assertTrue(all(item >= 0 for item in value["point_forecast"]))

    def test_p95_not_below_p80(self):
        for value in self.result["services"].values():
            self.assertTrue(all(a >= b for a, b in zip(value["p95"], value["p80"], strict=True)))

    def test_p80_not_below_p50(self):
        for value in self.result["services"].values():
            self.assertTrue(all(a >= b for a, b in zip(value["p80"], value["p50"], strict=True)))

    def test_selected_model_is_candidate(self):
        for value in self.result["services"].values():
            self.assertIn(value["selected_model"], value["diagnostics"])

    def test_selection_is_deterministic(self):
        self.assertEqual(self.result, forecast_case(self.case))

    def test_rolling_origin_has_metrics(self):
        metrics = rolling_origin([float(index % 7 + 1) for index in range(35)], MODELS["moving-average-7"])
        self.assertEqual(set(metrics), {"wape", "mae", "bias", "residual_sd"})

    def test_constant_series_zero_bias_for_moving_average(self):
        metrics = rolling_origin([5.0] * 35, MODELS["moving-average-7"])
        self.assertAlmostEqual(metrics["bias"], 0.0)

    def test_empty_model_forecasts_zero(self):
        for model in MODELS.values():
            self.assertEqual(model([], 3), [0.0, 0.0, 0.0])


def _make_model_shape_test(name):
    def test(self):
        values = MODELS[name]([float(index % 5) for index in range(28)], 8)
        self.assertEqual(len(values), 8)
        self.assertTrue(all(item >= 0 for item in values))
    return test


for _name in MODELS:
    setattr(ForecastTests, f"test_shape_{_name.replace('-', '_')}", _make_model_shape_test(_name))


if __name__ == "__main__":
    unittest.main()
''')

write("tests/test_inventory_reliability.py", '''
from __future__ import annotations

import random
import unittest

from service_ops_lab.inventory import InventoryState
from service_ops_lab.reliability import available_unit, begin_day, build_units, maybe_fail, summary
from helpers import case


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.items = case()["inventory"]

    def test_initial_stock(self):
        state = InventoryState(self.items, 2)
        self.assertEqual(state.on_hand["filter-set"], 95)

    def test_valid_consumption(self):
        state = InventoryState(self.items, 2)
        self.assertTrue(state.consume({"filter-set": 2}))
        self.assertEqual(state.on_hand["filter-set"], 93)

    def test_invalid_consumption_does_not_go_negative(self):
        state = InventoryState(self.items, 2)
        self.assertFalse(state.consume({"filter-set": 1000}))
        self.assertEqual(state.on_hand["filter-set"], 95)

    def test_reorder_uses_pack_size(self):
        state = InventoryState(self.items, 5)
        state.on_hand["filter-set"] = 0
        state.reorder(0, {"filter-set": 10})
        order = next(item for item in state.orders if item["sku"] == "filter-set")
        self.assertEqual(order["quantity"] % 20, 0)

    def test_receipt_arrives(self):
        state = InventoryState(self.items, 5)
        state.on_hand["filter-set"] = 0
        state.reorder(0, {"filter-set": 10})
        arrival = next(item["arrival_day"] for item in state.orders if item["sku"] == "filter-set")
        before = state.on_hand["filter-set"]
        state.begin_day(arrival)
        self.assertGreater(state.on_hand["filter-set"], before)

    def test_balance_identity(self):
        state = InventoryState(self.items, 2)
        state.consume({"seal-kit": 3})
        result = state.summary()
        self.assertTrue(all(value == 0 for value in result["balance_error"].values()))

    def test_holding_cost_accumulates(self):
        state = InventoryState(self.items, 2)
        state.end_day()
        self.assertGreater(state.cost, 0)


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.case = case()
        self.units = build_units(self.case["equipment"])
        self.catalog = {item["id"]: item for item in self.case["equipment"]}

    def test_unit_count(self):
        self.assertEqual(len(self.units), 5)

    def test_available_unit(self):
        self.assertIsNotNone(available_unit(self.units, "mobile-kit", 0))

    def test_unknown_equipment_has_no_unit(self):
        self.assertIsNone(available_unit(self.units, "missing", 0))

    def test_pm_creates_downtime(self):
        begin_day(self.units, self.catalog, 0, 32, 5)
        self.assertGreater(summary(self.units)["pm_events"], 0)

    def test_forced_failure(self):
        unit = self.units[0]
        item = dict(self.catalog[unit.equipment_type]); item["failure_probability"] = 1.0
        maybe_fail(unit, item, 1.0, random.Random(1), 0)
        self.assertEqual(unit.failures, 1)
        self.assertGreater(unit.down_until_slot, 0)

    def test_summary_has_every_unit(self):
        self.assertEqual(len(summary(self.units)["by_unit"]), len(self.units))


if __name__ == "__main__":
    unittest.main()
''')

write("tests/test_simulation.py", '''
from __future__ import annotations

import copy
import unittest

from service_ops_lab.forecasting import forecast_case
from service_ops_lab.models import Policy
from service_ops_lab.simulation import simulate_policy
from helpers import case


BASE = Policy(0.1, 1, 4, 3, 5, 1, "sla")


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = case()
        cls.forecast = forecast_case(cls.case)
        cls.baseline = next(item for item in cls.case["scenarios"] if item["id"] == "baseline")
        cls.result = simulate_policy(cls.case, BASE, cls.baseline, forecast=cls.forecast)

    def test_is_deterministic(self):
        again = simulate_policy(self.case, BASE, self.baseline, forecast=self.forecast)
        self.assertEqual(self.result, again)

    def test_job_flow_conservation(self):
        self.assertEqual(self.result["conservation"]["job_flow_error"], 0)

    def test_inventory_conservation(self):
        self.assertTrue(all(value == 0 for value in self.result["conservation"]["inventory_balance_error"].values()))

    def test_completion_bounded(self):
        self.assertGreaterEqual(self.result["metrics"]["completion_rate"], 0)
        self.assertLessEqual(self.result["metrics"]["completion_rate"], 1)

    def test_sla_bounded(self):
        self.assertGreaterEqual(self.result["metrics"]["sla_attainment"], 0)
        self.assertLessEqual(self.result["metrics"]["sla_attainment"], 1)

    def test_ftr_bounded(self):
        self.assertGreaterEqual(self.result["metrics"]["first_time_right"], 0)
        self.assertLessEqual(self.result["metrics"]["first_time_right"], 1)

    def test_all_services_reported(self):
        self.assertEqual(set(self.result["service_metrics"]), {item["id"] for item in self.case["service_types"]})

    def test_daily_trace_length(self):
        self.assertEqual(len(self.result["daily_trace"]), 21)

    def test_boundary_is_explicit(self):
        self.assertTrue(self.result["boundary"]["synthetic"])
        self.assertFalse(self.result["boundary"]["global_optimality_claim"])

    def test_cost_nonnegative(self):
        self.assertGreater(self.result["metrics"]["total_cost"], 0)

    def test_equipment_summary(self):
        self.assertEqual(len(self.result["reliability"]["by_unit"]), 5)

    def test_inventory_summary(self):
        self.assertEqual(set(self.result["inventory"]["ending"]), {item["id"] for item in self.case["inventory"]})

    def test_demand_surge_not_fewer_generated_jobs(self):
        surge = next(item for item in self.case["scenarios"] if item["id"] == "demand-surge")
        result = simulate_policy(self.case, BASE, surge, forecast=self.forecast)
        self.assertGreaterEqual(result["metrics"]["generated_jobs"], self.result["metrics"]["generated_jobs"])

    def test_quality_program_improves_or_equals_ftr_under_same_seed(self):
        low = Policy(0.1, 1, 4, 3, 5, 0, "sla")
        high = Policy(0.1, 1, 4, 3, 5, 1, "sla")
        left = simulate_policy(self.case, low, self.baseline, forecast=self.forecast)
        right = simulate_policy(self.case, high, self.baseline, forecast=self.forecast)
        self.assertGreaterEqual(right["metrics"]["first_time_right"], left["metrics"]["first_time_right"])

    def test_supply_delay_is_replayable(self):
        result = simulate_policy(self.case, BASE, self.baseline, overrides={"lead_time_shift": 5}, forecast=self.forecast)
        again = simulate_policy(self.case, BASE, self.baseline, overrides={"lead_time_shift": 5}, forecast=self.forecast)
        self.assertEqual(result, again)


def _make_policy_rule_test(rule):
    def test(self):
        policy = Policy(0.0, 0, 0, 1, 9, 0, rule)
        result = simulate_policy(self.case, policy, self.baseline, forecast=self.forecast)
        self.assertEqual(result["policy"]["priority_rule"], rule)
        self.assertEqual(result["conservation"]["job_flow_error"], 0)
    return test


for _rule in ("fifo", "sla", "shortest"):
    setattr(SimulationTests, f"test_priority_{_rule}", _make_policy_rule_test(_rule))


if __name__ == "__main__":
    unittest.main()
''')

write("tests/test_optimization_stress.py", '''
from __future__ import annotations

import unittest

from service_ops_lab.explain import explain_plan
from service_ops_lab.optimization import generate_policies, optimize_case, pareto_frontier
from service_ops_lab.stress import run_stress
from helpers import case, generated


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.case = case()

    def test_policy_count(self):
        self.assertEqual(len(generate_policies(self.case)), 288)

    def test_policy_ids_unique(self):
        values = [item.policy_id for item in generate_policies(self.case)]
        self.assertEqual(len(values), len(set(values)))

    def test_small_search(self):
        plan = optimize_case(self.case, policy_limit=4, replications=1)
        self.assertEqual(plan["candidate_policy_count"], 4)
        self.assertIn(plan["selection_status"], {"feasible-selected", "least-violating-no-feasible-policy"})

    def test_generated_full_search(self):
        plan = generated("plan.json")
        self.assertEqual(plan["candidate_policy_count"], 288)
        self.assertGreaterEqual(plan["feasible_policy_count"], 1)

    def test_selected_policy_exists_in_catalog(self):
        plan = generated("plan.json")
        self.assertIn(plan["selected_policy_id"], {item["policy"]["policy_id"] for item in plan["policy_catalog"]})

    def test_selected_policy_is_feasible_when_feasible_set_exists(self):
        plan = generated("plan.json")
        if plan["feasible_policy_count"]:
            self.assertTrue(plan["selected"]["feasible"])

    def test_cvar_not_below_expected_tailless_cost(self):
        plan = generated("plan.json")
        self.assertGreaterEqual(plan["selected"]["cvar_cost"], plan["selected"]["expected_metrics"]["total_cost"] * 0.80)

    def test_pareto_frontier_nonempty(self):
        self.assertTrue(generated("plan.json")["pareto_frontier"])

    def test_boundary_no_global_optimality(self):
        self.assertFalse(generated("plan.json")["boundary"]["global_optimality_claim"])

    def test_stress_count(self):
        self.assertEqual(generated("stress.json")["stress_case_count"], 8)

    def test_stress_conservation(self):
        for item in generated("stress.json")["results"]:
            self.assertEqual(item["conservation"]["job_flow_error"], 0)
            self.assertTrue(all(value == 0 for value in item["conservation"]["inventory_balance_error"].values()))

    def test_explanation_matches_selected_policy(self):
        plan = generated("plan.json")
        explanation = generated("explanation.json")
        self.assertEqual(explanation["selected_policy_id"], plan["selected_policy_id"])

    def test_explanation_has_review_sequence(self):
        self.assertGreaterEqual(len(generated("explanation.json")["recommended_review_sequence"]), 4)


if __name__ == "__main__":
    unittest.main()
''')

write("tests/test_reporting_artifacts.py", '''
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from service_ops_lab.artifacts import verify_manifest
from service_ops_lab.reporting import render_html, render_markdown
from service_ops_lab.util import safe_csv_cell, stable_hash
from helpers import GENERATED, case, generated


class ReportingTests(unittest.TestCase):
    def test_manifest_verifies(self):
        self.assertEqual(verify_manifest(GENERATED), [])

    def test_manifest_detects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in GENERATED.iterdir():
                if path.is_file():
                    (root / path.name).write_bytes(path.read_bytes())
            (root / "plan.json").write_text("{}\n")
            self.assertTrue(verify_manifest(root))

    def test_markdown_boundary(self):
        text = (GENERATED / "decision-report.md").read_text(encoding="utf-8")
        self.assertIn("not a production forecast", text)
        self.assertIn("Required next validation", text)

    def test_html_boundary(self):
        text = (GENERATED / "decision-lab.html").read_text(encoding="utf-8")
        self.assertIn("Synthetic integrated service-operations lab", text)
        self.assertNotIn("<script", text.casefold())
        self.assertNotIn("https://", text)

    def test_csv_formula_neutralization(self):
        self.assertEqual(safe_csv_cell("=1+1"), "'=1+1")
        self.assertEqual(safe_csv_cell("safe"), "safe")

    def test_policy_csv_rows(self):
        with (GENERATED / "policy-catalog.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 288)

    def test_scenario_csv_rows(self):
        with (GENERATED / "scenario-results.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 5)

    def test_stress_csv_rows(self):
        with (GENERATED / "stress-results.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 8)

    def test_case_fingerprint_deterministic(self):
        self.assertEqual(stable_hash(case()), stable_hash(case()))

    def test_json_outputs_parse(self):
        for name in ("plan.json", "stress.json", "explanation.json", "forecast.json", "artifact-manifest.json"):
            with self.subTest(name=name):
                json.loads((GENERATED / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
''')

write("tests/test_cli_publication.py", '''
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import CASE_PATH, GENERATED, ROOT


def run_cli(*args):
    env = dict(os.environ); env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run([sys.executable, "-m", "service_ops_lab", *args], cwd=ROOT, env=env, text=True, capture_output=True)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec); sys.modules[name] = value; spec.loader.exec_module(value)
    return value


class CliTests(unittest.TestCase):
    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0); self.assertIn("0.1.0", result.stdout)

    def test_validate(self):
        result = run_cli("validate", "--case", str(CASE_PATH))
        self.assertEqual(result.returncode, 0, result.stderr); self.assertIn("PASS", result.stdout)

    def test_forecast(self):
        result = run_cli("forecast", "--case", str(CASE_PATH))
        self.assertEqual(result.returncode, 0, result.stderr); self.assertIn("selected_model", result.stdout)

    def test_fingerprint(self):
        result = run_cli("fingerprint", "--case", str(CASE_PATH))
        self.assertEqual(result.returncode, 0); self.assertEqual(len(result.stdout.strip()), 64)

    def test_audit(self):
        result = run_cli("audit", "--directory", str(GENERATED))
        self.assertEqual(result.returncode, 0, result.stderr); self.assertTrue(json.loads(result.stdout)["ok"])

    def test_self_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli("self-test", "--output-dir", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_case_returns_two(self):
        result = run_cli("validate", "--case", "missing.json")
        self.assertEqual(result.returncode, 2)


class PublicationTests(unittest.TestCase):
    def test_public_audit_passes(self):
        audit = module("sodl_public_audit", "tools/public_audit.py")
        count, findings = audit.scan(ROOT)
        self.assertGreater(count, 35); self.assertEqual(findings, [])

    def test_public_audit_detects_synthetic_token(self):
        audit = module("sodl_public_audit_token", "tools/public_audit.py")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.txt").write_text("gh" + "p_" + "A" * 36)
            _, findings = audit.scan(Path(tmp))
            self.assertTrue(any(item[0] == "github_token" for item in findings))

    def test_public_audit_detects_legacy_marker(self):
        audit = module("sodl_public_audit_legacy", "tools/public_audit.py")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.txt").write_text("Hazel" + "'s Lawn Care")
            _, findings = audit.scan(Path(tmp))
            self.assertTrue(any(item[0] == "legacy_course_case" for item in findings))

    def test_docs(self):
        result = subprocess.run([sys.executable, "tools/check_docs.py", "."], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_workflows(self):
        result = subprocess.run([sys.executable, "tools/check_workflows.py"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_schema_parity(self):
        result = subprocess.run([sys.executable, "tools/check_schema_parity.py"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_current(self):
        env = dict(os.environ); env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run([sys.executable, "tools/generate_examples.py", "--check"], cwd=ROOT, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_html_audit(self):
        result = subprocess.run([sys.executable, "tools/audit_html.py", "examples/generated/decision-lab.html"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_workflow_actions_pinned(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "uses:" in line:
                    reference = line.split("@", 1)[-1].split()[0]
                    self.assertEqual(len(reference), 40)

    def test_release_workflow_is_main_bound(self):
        text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("origin/main", text)
        self.assertIn("SHA256SUMS.txt", text)
        self.assertIn("RELEASE_PROVENANCE.json", text)
        self.assertIn("refusing to move", text)


if __name__ == "__main__":
    unittest.main()
''')

write(".github/pull_request_template.md", '''
## Decision surface

Describe the forecasting, queueing, workforce, maintenance, inventory, quality, risk or reporting behavior changed.

## Evidence

- [ ] positive test added or updated
- [ ] boundary/failure test added or updated
- [ ] job and inventory conservation preserved
- [ ] generated artifacts rebuilt
- [ ] public boundary unchanged
- [ ] no global-optimality or real-business claim introduced
- [ ] `PYTHONPATH=src python tools/release_check.py` passes
''')

write(".github/ISSUE_TEMPLATE/model.yml", '''
name: Model or policy proposal
description: Propose a synthetic model, decision rule or constraint change.
title: "model: "
body:
  - type: textarea
    attributes:
      label: Decision problem
    validations:
      required: true
  - type: textarea
    attributes:
      label: Mathematical or operational contract
    validations:
      required: true
  - type: textarea
    attributes:
      label: Positive and failure fixtures
    validations:
      required: true
  - type: checkboxes
    attributes:
      label: Public boundary
      options:
        - label: Uses synthetic or clearly licensed public data only.
          required: true
        - label: Does not claim a real enterprise outcome or global optimum.
          required: true
''')

write(".github/ISSUE_TEMPLATE/bug.yml", '''
name: Bug report
description: Report a reproducible defect using synthetic data.
title: "bug: "
body:
  - type: textarea
    attributes:
      label: Minimal synthetic reproduction
    validations:
      required: true
  - type: textarea
    attributes:
      label: Expected and actual result
    validations:
      required: true
  - type: checkboxes
    attributes:
      label: Data confirmation
      options:
        - label: I removed customer, employee, course and private operational data.
          required: true
''')

write(".github/workflows/ci.yml", '''
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: service-operations-lab-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: Python ${{ matrix.python-version }}
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    env:
      PYTHONPATH: src
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 1
          persist-credentials: false
      - name: Set up Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: ${{ matrix.python-version }}
          cache: ""
      - name: Run complete release gate
        run: python tools/release_check.py

  generated-artifacts:
    name: Full generated artifact replay
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    env:
      PYTHONPATH: src
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 1
          persist-credentials: false
      - name: Set up Python 3.13
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.13"
          cache: ""
      - name: Regenerate full decision artifacts
        run: python tools/generate_examples.py --output /tmp/generated
      - name: Compare committed artifacts
        shell: bash
        run: diff -ru examples/generated /tmp/generated
      - name: Upload full replay evidence
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with:
          name: service-operations-full-replay-${{ github.run_id }}
          path: /tmp/generated
          if-no-files-found: error
          retention-days: 14

  reproducible-wheel:
    name: Reproducible wheel
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 1
          persist-credentials: false
      - name: Set up Python 3.13
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.13"
          cache: ""
      - name: Install pinned build tooling
        run: python -m pip install --disable-pip-version-check setuptools==80.9.0 wheel==0.45.1
      - name: Build twice and compare
        shell: bash
        run: |
          set -euo pipefail
          export SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
          version="$(python - <<'PY'
          import tomllib
          from pathlib import Path
          print(tomllib.loads(Path('pyproject.toml').read_text())['project']['version'])
          PY
          )"
          mkdir -p /tmp/wheel-a /tmp/wheel-b
          python -m pip wheel --disable-pip-version-check --no-deps --no-build-isolation --wheel-dir /tmp/wheel-a .
          rm -rf build src/*.egg-info
          python -m pip wheel --disable-pip-version-check --no-deps --no-build-isolation --wheel-dir /tmp/wheel-b .
          cmp "/tmp/wheel-a/service_operations_decision_lab-${version}-py3-none-any.whl" "/tmp/wheel-b/service_operations_decision_lab-${version}-py3-none-any.whl"
          sha256sum /tmp/wheel-a/*.whl
''')

write(".github/workflows/release.yml", '''
name: Release

on:
  create:
  push:
    branches:
      - "release/v*"

permissions:
  contents: write

concurrency:
  group: service-operations-decision-lab-release
  cancel-in-progress: false

jobs:
  release:
    if: >-
      (github.event_name == 'create' && github.event.ref_type == 'branch' && startsWith(github.event.ref, 'release/v')) ||
      (github.event_name == 'push' && startsWith(github.ref_name, 'release/v'))
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    env:
      PYTHONPATH: src
    steps:
      - name: Check out immutable candidate
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          ref: ${{ github.sha }}
          fetch-depth: 0
          persist-credentials: true
      - name: Set up Python 3.13
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.13"
          cache: ""
      - name: Confirm candidate equals main and resolve version
        id: version
        shell: bash
        run: |
          set -euo pipefail
          git fetch origin main --no-tags
          test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
          if [[ "$GITHUB_EVENT_NAME" == "create" ]]; then ref="${{ github.event.ref }}"; else ref="$GITHUB_REF_NAME"; fi
          version="${ref#release/}"
          [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
          expected="v$(python - <<'PY'
          import tomllib
          from pathlib import Path
          print(tomllib.loads(Path('pyproject.toml').read_text())['project']['version'])
          PY
          )"
          test "$version" = "$expected"
          test -f "docs/release-notes/${version}.md"
          echo "value=$version" >> "$GITHUB_OUTPUT"
      - name: Run complete release gate
        run: python tools/release_check.py
      - name: Install pinned build tooling
        run: python -m pip install --disable-pip-version-check setuptools==80.9.0 wheel==0.45.1
      - name: Configure annotated tag identity
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
      - name: Create or verify immutable tag
        shell: bash
        env:
          VERSION: ${{ steps.version.outputs.value }}
        run: |
          set -euo pipefail
          head_sha="$(git rev-parse HEAD)"
          if git ls-remote --exit-code --tags origin "refs/tags/$VERSION" >/dev/null 2>&1; then
            git fetch origin "refs/tags/$VERSION:refs/tags/$VERSION" --force
            if [[ "$(git rev-list -n 1 "$VERSION")" != "$head_sha" ]]; then
              echo "refusing to move an existing release tag" >&2
              exit 1
            fi
          else
            git tag -a "$VERSION" -m "Service Operations Decision Lab $VERSION" HEAD
            git push origin "refs/tags/$VERSION"
          fi
      - name: Build and verify release assets
        shell: bash
        env:
          VERSION: ${{ steps.version.outputs.value }}
        run: |
          set -euo pipefail
          version="${VERSION#v}"
          rm -rf dist
          mkdir -p dist
          prefix="service-operations-decision-lab-${version}/"
          git archive --format=tar --prefix="$prefix" HEAD | gzip -n > "dist/service-operations-decision-lab-${version}.tar.gz"
          git archive --format=zip --prefix="$prefix" HEAD > "dist/service-operations-decision-lab-${version}.zip"
          SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" python -m pip wheel --disable-pip-version-check --no-deps --no-build-isolation --wheel-dir dist .
          (cd examples/generated && zip -X -q -r ../../dist/service-operations-decision-lab-${version}-generated.zip .)
          VERSION="$VERSION" python - <<'PY'
          import json
          import os
          import re
          from pathlib import Path
          tests = sum(1 for path in Path('tests').glob('test_*.py') for line in path.read_text().splitlines() if re.match(r'\s*def test_', line))
          plan = json.loads(Path('examples/generated/plan.json').read_text())
          stress = json.loads(Path('examples/generated/stress.json').read_text())
          payload = {
              'schema_version': 1,
              'repository': os.environ['GITHUB_REPOSITORY'],
              'tag': os.environ['VERSION'],
              'commit': os.environ['GITHUB_SHA'],
              'workflow_run_id': os.environ['GITHUB_RUN_ID'],
              'workflow_run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
              'static_test_function_count': tests,
              'candidate_policy_count': plan['candidate_policy_count'],
              'feasible_policy_count': plan['feasible_policy_count'],
              'scenario_count': len(plan['selected']['scenario_summaries']),
              'stress_case_count': stress['stress_case_count'],
              'schema_count': len(list(Path('schemas').glob('*.json'))),
              'generated_artifact_count': len(list(Path('examples/generated').iterdir())),
              'python_matrix': ['3.11', '3.12', '3.13'],
              'public_boundary_audit': 'passed',
              'maturity': 'synthetic-reference-implementation',
              'production_optimality_certification': 'not-claimed',
          }
          Path('dist/RELEASE_PROVENANCE.json').write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
          PY
          (cd dist && sha256sum "service-operations-decision-lab-${version}.tar.gz" "service-operations-decision-lab-${version}.zip" "service_operations_decision_lab-${version}-py3-none-any.whl" "service-operations-decision-lab-${version}-generated.zip" RELEASE_PROVENANCE.json > SHA256SUMS.txt && sha256sum -c SHA256SUMS.txt)
      - name: Create or repair GitHub Release
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
          VERSION: ${{ steps.version.outputs.value }}
        run: |
          set -euo pipefail
          version="${VERSION#v}"
          assets=("dist/service-operations-decision-lab-${version}.tar.gz" "dist/service-operations-decision-lab-${version}.zip" "dist/service_operations_decision_lab-${version}-py3-none-any.whl" "dist/service-operations-decision-lab-${version}-generated.zip" "dist/SHA256SUMS.txt" "dist/RELEASE_PROVENANCE.json")
          if gh release view "$VERSION" >/dev/null 2>&1; then
            gh release edit "$VERSION" --title "Service Operations Decision Lab $VERSION" --notes-file "docs/release-notes/${VERSION}.md"
            gh release upload "$VERSION" "${assets[@]}" --clobber
          else
            gh release create "$VERSION" "${assets[@]}" --title "Service Operations Decision Lab $VERSION" --notes-file "docs/release-notes/${VERSION}.md" --verify-tag
          fi
''')

write("docs/release-notes/v0.1.0.md", '''
# Service Operations Decision Lab v0.1.0

Initial public release of an original, fully synthetic integrated service-operations decision laboratory.

## Included

- rolling-origin demand forecasting;
- appointment, walk-in, no-show, queue, SLA and abandonment simulation;
- skill-constrained workforce, flexible capacity and overtime;
- equipment PM, failure, repair and downtime;
- lead-time spare-parts inventory and stockout blocking;
- first-time-right quality and revisit generation;
- 288-policy nonanticipative search across five scenarios;
- hard service constraints, weighted CVaR and Pareto alternatives;
- eight deterministic stress cases;
- conservation identities, explanations and deterministic reports;
- Python 3.11–3.13 CI and reproducible release assets.

## Boundary

All entities and values are synthetic. This release does not reproduce coursework, describe a real service company, certify a production forecast, or prove global optimality.
''')
print("P041 tests, tools, schemas and long-lived workflows written")
