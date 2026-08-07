---
name: skill-evaluator
description: "Evaluate, benchmark, compare, regression-test, or security-audit an Agent Skill package. Use when deciding whether a skill triggers correctly, improves task outcomes over a no-skill or prior-version baseline, follows its intended process, remains efficient and safe, generalizes beyond development examples, or is ready to install, publish, or deploy."
metadata:
  version: 3.3.2
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [evaluation, testing, benchmarking, security]
    category: software-development
    related_skills: [software-quality-workflows]
---

# Skill Evaluator

## Owner contract

Evaluate the complete Skill package and its runtime contribution. For a frontier model, reward only specialized, task-relevant help beyond the model's native competence; treat redundant instructions and loaded references as context cost.

Use the lightest decision-supporting level. Resolve paths from this file's directory as `SKILL_EVALUATOR_DIR`.

This skill is explicit-only. Invoke it for a requested package-quality, comparison, security, release, or longitudinal decision, never ordinary development.

## Decision router

| Decision | Level | Read next |
|---|---|---|
| Inspect an unknown or untrusted package | L0 | [Security and package audit](references/security-and-package-audit.md) |
| Diagnose trigger, loading, or execution | L1 | [Execution and grading](references/execution-and-grading.md) |
| Decide whether the Skill adds value at acceptable context cost | L2 | [Evaluation contract](references/evaluation-contract.md), then [Rubric and metrics](references/rubric-and-metrics.md) |
| Support release, installation, high-risk, or generalization claims | L3 | [Task-suite design](references/task-suite-design.md), then [Reporting and decisions](references/reporting-and-decisions.md) |
| Compare a controlled revision or model transition | L4 | [Longitudinal evaluation](references/longitudinal-evaluation.md) |
| Trace method provenance | any | [Source map](references/source-map.md) |

Load only the owner of the active question. Do not preload every reference.

## Evidence read surface

Keep evidence immutable. Read the analyzer summary first, then its failure index and spec-bounded representative receipts. Open raw artifacts only for named failures, disagreements, or integrity audits by exact locator/hash. Never tree-walk or create per-step notes/receipt copies. Failure is an outcome, not an efficiency gain.

When a validator names a concrete input file and missing field, keep that validator, file, and current level as the owner. Correct only the reported contract defect and rerun the same validation command; do not substitute another artifact or add arguments unless the validated level explicitly requires them.

## Claim ceilings

| Level | Required evidence | Maximum claim |
|---|---|---|
| L0 | Whole-package inventory and static review | Static findings only |
| L1 | Focused scenarios with verified run receipts | Diagnostic behavior only |
| L2 | Frozen baseline/candidate scenarios, independent-case intervals, benefit and context guardrails | Scoped incremental usefulness |
| L3 | L2 plus sequestered holdout, adversarial controls, environment binding, and required manual-review receipt | Readiness for the tested scope only |
| L4 | Immutable cycle capsules plus a frozen comparison plan | Revision closure or model-transition classification for the tested scope only |

Without selection, order, and composition receipts, L4 cannot claim library-scale orchestration.

## Non-negotiable invariants

- Spec v5, scenario v1 `requirements[]`, host manifest v1, one compiled plan v1, one run index v2, and self-hashed receipts v4 are the only runtime decision path. Never accept inline run scores, legacy case wires, or parallel oracle fields.
- L2+ contribution requires the same scenarios and controls for a no-Skill baseline and a candidate treatment: natural routing for a routing claim, or forced loading for explicit-invocation value. When both are declared, natural routing is the default comparison unless the analyzer caller selects the forced treatment; a prior comparator matches that mode.
- Repeats diagnose run variability; inference resamples distinct case means. Point lift or absolute pass rate cannot replace the declared positive lower-bound benefit gate.
- Missing, invalid, duplicate, or tampered evidence remains outside metric denominators and makes usefulness inconclusive. Treatment-attributable failures with complete host evidence remain valid outcome failures.
- Target-Skill context is verified from captured component artifacts. The frozen intended-trigger candidate plan is the attribution denominator; total input tokens cannot substitute for attributed body/reference cost.
- Safety and protected outcomes are unweighted guardrails. Utility cannot offset a material safety or protected-case failure.
- Static audit findings are provisional review locators. They never authorize deleting package resources, hiding matched text, weakening rules, or treating scanner silence as safety evidence.
- Empirical usefulness is `supported`, `not_supported`, `inconclusive_ceiling`, or `not_evaluable`. Manual review and deployment authority are separate final gates.
- Public templates are placeholders, never live receipts, host evidence, or scored usefulness evidence.
- Offline comparison consumes existing immutable cycle capsules; it never edits a Skill, schedules a run, promotes a release, or converts exploratory history into pre-registration.

## Run the owners

Run the matching CLI before opening its implementation source. Read implementation source only after a CLI failure to diagnose its owner.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/audit_skill_package.py" /path/to/skill
```

L0 emits bounded triage without sidecars. Add `--json audit.json` for a frozen report; `--json -` reserves stdout. Its states route review, never safety approval.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" contract eval-spec.l0.json
python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" contract eval-spec.json scenarios.jsonl host-manifest.json
```

Calibrate each model grader before suite quality. Gold rows own exact blinded payloads; ratings bind their hashes; thresholds apply per check. Reviewer pairs are optional; deterministic-only specs omit calibration. Set validity, request and timeout variables from frozen spec and Host.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/run_model_calibration.py" \
  --spec draft-eval-spec.json --labels calibration-gold.jsonl --host host-manifest.json \
  --output-dir calibration-run --created "$CREATED_UTC" --expires "$EXPIRES_UTC" \
  --expected-requests "$REQUESTS" --host-timeout "$HOST_TIMEOUT" --max-workers 4

python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" calibration --spec draft-eval-spec.json \
  --ratings calibration-run/calibration-ratings.jsonl --labels calibration-gold.jsonl --output grader-calibration.json

python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" suite-quality \
  --spec draft-eval-spec.json --proof suite-quality-proof.json --output suite-quality.json
```

Compile only an `execution.ready=true` spec; compilation starts no process. Inspect with `--status`. Run/resume require `--new-attempt-budget`; custody lasts through receipt/index commit.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/compile_eval_plan.py" eval-spec.ready.json scenarios.jsonl host-manifest.json --output execution-plan.json
python3 "$SKILL_EVALUATOR_DIR/scripts/run_eval_plan.py" execution-plan.json --index artifacts/index.jsonl --status
python3 "$SKILL_EVALUATOR_DIR/scripts/run_eval_plan.py" execution-plan.json --index artifacts/index.jsonl --new-attempt-budget 2
```

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/analyze_runs.py" artifacts/index.jsonl \
  --spec eval-spec.ready.json --json summary.json --failure-index failures.json \
  --markdown summary.md
```

Analyzer exits: `0` supported/eligible or L0/L1 diagnostic; `1` verified not-supported or manual `hold|reject`; `2` contract/I/O error; `3` incomplete, invalid, unsupported, not-evaluable, inconclusive, or authority-ineligible. A required manual receipt is spec-relative. `--report-only` changes only `1` to `0`.

## Owner index

- Contracts: [evaluation](references/evaluation-contract.md), [suite](references/task-suite-design.md), [execution](references/execution-and-grading.md), [metrics](references/rubric-and-metrics.md), [reporting](references/reporting-and-decisions.md), [longitudinal](references/longitudinal-evaluation.md).
- Support: [source map](references/source-map.md), [schemas](schemas/README.md), [report template](templates/evaluation-report.md).
- Code: [audit](scripts/audit_skill_package.py), [validator](scripts/validate_eval_suite.py), [calibration](scripts/run_model_calibration.py), [reviewer pair](scripts/reviewer_pair_contract.py), [reviewer prompt](scripts/reviewer_prompt_contract.py), [compiler](scripts/compile_eval_plan.py), [runner](scripts/run_eval_plan.py), [status](scripts/runner_status.py), [transport](scripts/model_grade_transport.py), [grader semantics](scripts/grader_semantics.py), [analyzer](scripts/analyze_runs.py), [comparator](scripts/compare_cycles.py), [I/O](scripts/evidence_io.py).
- Specs: [L0](templates/eval-spec.l0.example.json), [L1](templates/eval-spec.l1.example.json), [L2](templates/eval-spec.example.json); scenarios: [L1](templates/scenarios.l1.example.jsonl), [L2](templates/scenarios.example.jsonl); [host](templates/host-manifest.example.json).
- Preparation: [calibration ratings](templates/calibration-ratings.example.jsonl), [calibration gold](templates/calibration-gold.example.jsonl), and [suite-quality proof](templates/suite-quality-proof.example.json).
- Evidence: [run index](templates/runs.example.jsonl), [grader schema](templates/grader-output.schema.json), [grader prompt](templates/llm-grader-prompt.md), [holdout manifest](templates/holdout-manifest.example.json), and [holdout scenarios](templates/holdout-scenarios.example.jsonl).
- Comparisons: [revision plan](templates/comparison-plan.revision.example.json) and [model-transition plan](templates/comparison-plan.model-transition.example.json).
