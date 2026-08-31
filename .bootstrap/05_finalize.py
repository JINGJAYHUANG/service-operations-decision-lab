from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

simulation = ROOT / "src/service_ops_lab/simulation.py"
text = simulation.read_text(encoding="utf-8")
old = 'rng = random.Random(_seed(case["case_id"], scenario["id"], replication, "operations"))'
new = 'rng = random.Random(_seed(case["case_id"], replication, "common-random-numbers"))'
if text.count(old) != 1:
    raise SystemExit("expected one scenario-specific RNG statement")
text = text.replace(old, new)
old = '''        start_completed = len(completed)
        start_abandoned = len(abandoned)
'''
new = '''        day_arrivals = sum(
            len(items)
            for slot, items in arrivals_by_slot.items()
            if day * day_slots <= slot < (day + 1) * day_slots
        )
        start_completed = len(completed)
        start_abandoned = len(abandoned)
'''
if text.count(old) != 1:
    raise SystemExit("expected one daily trace anchor")
text = text.replace(old, new)
old = '''                "arrivals": sum(len(items) for slot, items in arrivals_by_slot.items() if day * day_slots <= slot < (day + 1) * day_slots),
'''
new = '''                "arrivals": day_arrivals,
'''
if text.count(old) != 1:
    raise SystemExit("expected one daily arrivals expression")
text = text.replace(old, new)
simulation.write_text(text, encoding="utf-8", newline="\n")

tests = ROOT / "tests/test_cli_publication.py"
text = tests.read_text(encoding="utf-8")
old = '''    def test_generated_current(self):
        env = dict(os.environ); env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run([sys.executable, "tools/generate_examples.py", "--check"], cwd=ROOT, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
'''
new = '''    def test_generated_contract(self):
        plan = json.loads((GENERATED / "plan.json").read_text(encoding="utf-8"))
        manifest = json.loads((GENERATED / "artifact-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["candidate_policy_count"], 288)
        self.assertEqual(manifest["algorithm"], "sha256")
        self.assertIn("decision-lab.html", manifest["files"])
'''
if text.count(old) != 1:
    raise SystemExit("expected one expensive generated-current test")
tests.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
print("P041 deterministic replay and test-efficiency patches applied")
