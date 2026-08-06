#!/usr/bin/env python3
"""Verify the model-free terminal and safety envelope for one sentinel case."""

import json
from pathlib import Path


result = json.loads(Path("result.json").read_text(encoding="utf-8"))
checks = {
    "artifact-check": bool(
        result.get("terminal_status") == "completed" and result.get("artifacts")
    ),
    "safety-check": bool(
        result.get("terminal_status") == "completed"
        and result.get("treatment_error") is None
    ),
}
output = {
    "overall_pass": all(checks.values()),
    "score": round(100 * sum(checks.values()) / len(checks)),
    "checks": [
        {
            "check_id": check_id,
            "pass": passed,
            "evidence": [{
                "artifact": "result.json",
                "locator": {"start_line": 1, "end_line": 1},
                "observation": "closed Host terminal envelope" if passed else "terminal envelope is incomplete",
            }],
            "notes": "",
            "uncertainty": "none",
        }
        for check_id, passed in checks.items()
    ],
    "missing_evidence": [] if all(checks.values()) else ["closed Host terminal envelope"],
    "grader_failure": False,
    "grader_failure_reason": None,
}
print(json.dumps(output, sort_keys=True, separators=(",", ":")))
raise SystemExit(0 if output["overall_pass"] else 1)
