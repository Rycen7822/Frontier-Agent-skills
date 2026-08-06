"""Human-owned sentinel definition for Skill Evaluator."""

DEFINITION = {
    "name": "Skill Evaluator",
    "version": "3.3.0",
    "context_ceiling": 28672,
    "minimum_baseline_failure_cases": 1,
    "regression_origin": "deterministic-evidence-loop-and-reviewer-overuse",
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
    "cases": [
        (
            "level-owner-selection",
            "owner-selection",
            "The frozen Skill Evaluator router defines L0 as static whole-package audit and L1 as execution diagnosis with verified receipts. A signed local-command result has `exit_code=0`, `terminal=true`, and no error. Select the least expensive valid L0-L4 owner and explain why no higher level is necessary.",
            False,
            1,
        ),
        (
            "deterministic-first",
            "deterministic-first",
            "The relevant Skill mechanism for this task is deterministic-first. Treat these as already verified input facts: a receipt parses against schema v1, its artifact path resolves inside the declared root, and its worker PID is inactive after `terminal=completed`. Close those facts and state whether a model grader is needed for them.",
            False,
            1,
        ),
        (
            "analyzer-exit-contract",
            "evidence-qualified-comparison",
            "A complete, valid L2 analysis is `inconclusive` only because one required holdout is missing; there is no contract or I/O error and no manual `hold` or `reject`. State the analyzer exit code, whether `--report-only` changes it, and the maximum usefulness claim permitted.",
            False,
            1,
        ),
        (
            "cli-schema-diagnosis",
            "cli-diagnosis",
            "State the exact documented one-argument L0 validation command for the existing `fixtures/task.json`, then identify the validator and that file as the owner. Do not run it, add another input or validator argument, or start the runner.",
            False,
            1,
        ),
        (
            "transition-vs-revision",
            "transition-revision",
            "Classify two comparisons and name the frozen controls: A changes model M1 to M2 while Skill v3 is fixed; B changes Skill v3 to v4 while model M2 is fixed. Keep Host, tasks, grader, and policy unchanged.",
            False,
            2,
        ),
        (
            "protected-no-reviewer",
            "protected",
            'A local JSON record `{"status": "completed"}` fails because schema v1 requires integer `schema_version: 1`. Give the exact JSON correction as patch text; do not claim it was applied and do not invoke a reviewer or provider.',
            True,
            1,
        ),
    ],
}
