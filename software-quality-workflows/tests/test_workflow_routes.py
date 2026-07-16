from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from route_workflow import RESULT_KEYS, assess, validate_route_result  # noqa: E402


class WorkflowRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads((ROOT / "tests" / "fixtures" / "workflow-route-cases.json").read_text(encoding="utf-8"))

    def test_frozen_sparse_route_matrix_matches_one_card_router(self) -> None:
        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                actual = assess({**self.fixture["defaults"], **case["facts"]})
                self.assertEqual(RESULT_KEYS, set(actual))
                self.assertEqual([], validate_route_result(actual, ROOT))
                for key, expected in case["expected"].items():
                    if key == "primary_card_id":
                        observed = actual["primary_card"]["card_id"] if actual["primary_card"] else None
                    else:
                        observed = actual[key]
                    self.assertEqual(expected, observed, (key, actual))

    def test_incomplete_assessment_and_detached_unknowns_fail_closed(self) -> None:
        defaults = self.fixture["defaults"]
        incomplete = deepcopy(defaults)
        incomplete["surface_assessment"]["evidence_refs"] = []
        detached = {**defaults, "unknown_implicated_facts": ["public_contract.compatibility"]}
        for payload, code in ((incomplete, "ROUTE_FACTS_INCOMPLETE"), (detached, "ROUTE_FACTS_INVALID")):
            with self.subTest(code=code), self.assertRaises(ValueError) as caught:
                assess(payload)
            self.assertEqual(code, caught.exception.code)

    def test_cli_rejects_empty_and_unknown_route_facts_with_typed_error(self) -> None:
        for payload, code in (({}, "ROUTE_INPUT_INCOMPLETE"), ({"complexity_score": 99}, "ROUTE_INPUT_UNKNOWN_FIELD")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "facts.json"
                source.write_text(json.dumps(payload), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPTS / "route_workflow.py"), str(source)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertEqual(2, result.returncode)
            self.assertEqual(code, json.loads(result.stdout)["error"]["code"])


if __name__ == "__main__":
    unittest.main()
