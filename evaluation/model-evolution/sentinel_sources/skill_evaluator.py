"""Human-owned sentinel definition for Skill Evaluator."""

DEFINITION = {
    "name": "Skill Evaluator",
    "version": "3.3.1",
    "context_ceiling": 28672,
    "minimum_baseline_failure_cases": 2,
    "regression_origin": "deterministic-evidence-loop-and-reviewer-overuse",
    "verifier_source": "skill_evaluator_verifier.py",
    "claims": [
        "level-selection",
        "deterministic-first",
        "evidence-qualified-comparison",
    ],
    "process_evidence": [
        "the claim is assigned to the least expensive valid L0-L4 evidence owner",
        "schema, path, and lifecycle facts are closed before model grading",
        "the comparison uses bound evidence and marks unsupported claims as unsupported",
    ],
    "fixtures": {
        "fixtures/router.md": "L0 owns whole-package inventory and static review. L1 owns execution diagnosis with verified run receipts. Higher levels are unnecessary when the requested claim is already closed at a lower level.\n",
        "fixtures/receipt.json": '{"schema_version":4,"exit_code":0,"terminal":true,"error":null}\n',
        "fixtures/analysis-summary.json": '{"schema_version":4,"status":"inconclusive_ceiling","missing_evidence":["required holdout"],"contract_error":false,"io_error":false,"manual_decision":null}\n',
        "fixtures/l0-spec.json": '{"schema_version":5,"level":"L0","execution":{"ready":false}}\n',
        "fixtures/cli-contract.md": "Validate an L0 spec with the contract subcommand and one spec path: python3 skill-evaluator/scripts/validate_eval_suite.py contract SPEC. Do not invoke the runner or add scenario and Host inputs.\n",
        "fixtures/control-matrix.md": "Comparison A: model M1 to M2, Skill v3 fixed. Comparison B: Skill v3 to v4, model M2 fixed. In both comparisons Host, tasks, grader, and policy are fixed.\n",
        "fixtures/invalid-record.json": '{"schema_version":"1","status":"completed"}\n',
    },
    "cases": [
        {
            "id": "level-owner-selection",
            "coverage": "owner-selection",
            "task": "Read `fixtures/router.md` and `fixtures/receipt.json`. Select the least expensive valid L0-L4 owner for diagnosing this completed execution receipt, and explain why no higher level is needed.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/router.md", "fixtures/receipt.json"],
            "semantic_oracle": [
                "L1 owns execution diagnosis and no higher level is necessary"
            ],
        },
        {
            "id": "deterministic-first",
            "coverage": "deterministic-first",
            "task": "Treat `fixtures/receipt.json` as already schema-, path-, and lifecycle-verified. Close those deterministic facts and state whether a model grader is needed for them.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/receipt.json"],
            "semantic_oracle": [
                "verified schema, path, and lifecycle facts need no model grader"
            ],
        },
        {
            "id": "analyzer-exit-contract",
            "coverage": "evidence-qualified-comparison",
            "task": "Read `fixtures/analysis-summary.json`. State the analyzer exit code, whether `--report-only` changes it, and the maximum usefulness claim permitted.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/analysis-summary.json"],
            "semantic_oracle": [
                "inconclusive evidence exits 3 and report-only does not change it"
            ],
        },
        {
            "id": "cli-schema-diagnosis",
            "coverage": "cli-diagnosis",
            "task": "Read `fixtures/cli-contract.md`. Give the exact single-spec L0 validation command for `fixtures/l0-spec.json`, name the validator and input owners, and do not start the runner.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/cli-contract.md",
                "fixtures/l0-spec.json",
            ],
            "semantic_oracle": [
                "validate_eval_suite.py receives contract and fixtures/l0-spec.json"
            ],
        },
        {
            "id": "transition-vs-revision",
            "coverage": "transition-revision",
            "task": "Read `fixtures/control-matrix.md`. Classify both comparisons and name the controls that remain frozen.",
            "protected": False,
            "turns": 2,
            "initial_files": ["fixtures/control-matrix.md"],
            "semantic_oracle": ["A is a model transition and B is a Skill revision"],
        },
        {
            "id": "protected-no-reviewer",
            "coverage": "protected",
            "task": "Read `fixtures/invalid-record.json`. Give only the JSON patch that changes `schema_version` to integer 1. Do not claim application and do not invoke a reviewer or provider.",
            "protected": True,
            "turns": 1,
            "initial_files": ["fixtures/invalid-record.json"],
            "semantic_oracle": [
                "schema_version becomes integer 1 and status remains completed"
            ],
        },
    ],
}
