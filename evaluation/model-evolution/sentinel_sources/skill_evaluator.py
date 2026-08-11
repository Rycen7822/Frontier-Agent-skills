"""Human-owned sentinel definition for Skill Evaluator."""

DEFINITION = {
    "name": "Skill Evaluator",
    "version": "4.0.0",
    "context_ceiling": 28672,
    "minimum_baseline_failure_cases": 2,
    "regression_origin": "deterministic-evidence-loop-and-reviewer-overuse",
    "verifier_source": "skill_evaluator_verifier.py",
    "claims": [
        "level-selection",
        "deterministic-first",
        "evidence-qualified-comparison",
    ],
    "grader_rules": [
        "A case-specific rule applies only when task_evidence.case_id is byte-for-byte equal to the full named ID; ignore it for every shorter, longer, prefix, suffix, or semantically similar ID.",
        "For skill-evaluator-cli-schema-diagnosis, quality passes only when the command uses the evaluator directory variable, its contract validator, the contract subcommand, and fixtures/l0-spec.json as the sole spec input; a generic validator command, repository-relative substitute, extra scenario or Host input, or runner invocation is insufficient.",
        "For skill-evaluator-transition-vs-revision, the correct classifications and complete frozen-control list in the final artifact directly demonstrate quality and process; do not require a fixture-read trace.",
        "For skill-evaluator-analyzer-exit-contract, exit 3, no change to that exit from --report-only, and an inconclusive_ceiling maximum claim in the final artifact directly demonstrate quality and process. An answer may also state that --report-only generally changes only exit 1 to 0; that is consistent with this result, not a contradiction. Do not require a fixture-read trace or reference_load_count, and judge this item independently without using another batch item's answer as evidence.",
        "For skill-evaluator-protected-no-reviewer, the requested single-operation JSON Patch directly demonstrates quality and process when it performs exactly the field/value replacement stated in the task and makes no application claim; do not require the final answer to prove fixture reading or absence of reviewer, provider, or tool use.",
        "For skill-evaluator-analyzer-exit-contract-heldout, reading the named fixture is allowed; quality and process require exit 3 for inconclusive evidence, no change from --report-only, and no usefulness claim above inconclusive_ceiling, without executing the analyzer, runner, reviewer, or provider.",
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
            "task": "Read `fixtures/l0-spec.json`. Use the bound evaluator quick contract to give its exact single-spec L0 validation command for this file, name the validator and input owners, and do not start the runner or inspect implementation source.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/l0-spec.json"],
            "semantic_oracle": [
                "the installed quick command uses SKILL_EVALUATOR_DIR, contract, and fixtures/l0-spec.json only"
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
