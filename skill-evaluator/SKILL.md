---
name: skill-evaluator
description: "Evaluate, benchmark, compare, regression-test, or security-audit an Agent Skill package. Use when deciding whether a skill triggers correctly, improves task outcomes over a no-skill or prior-version baseline, follows its intended process, remains efficient and safe, generalizes beyond development examples, or is ready to install, publish, or deploy."
metadata:
  version: 3.0.0
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

Use the lightest level that can support the decision. A package audit or smoke run never becomes a comparative, release, or deployment claim. Resolve all paths below from this `SKILL.md` directory as `SKILL_EVALUATOR_DIR`.

This skill is explicit-only. Ordinary software development does not run an evaluation automatically; invoke it only for a requested package-quality, comparison, security, release, or longitudinal decision.

## Decision router

| Decision | Level | Read next |
|---|---|---|
| Inspect an unknown or untrusted package | L0 | [Security and package audit](references/security-and-package-audit.md) |
| Diagnose trigger, loading, or execution | L1 | [Execution and grading](references/execution-and-grading.md) |
| Decide whether the Skill adds value at acceptable context cost | L2 | [Evaluation contract](references/evaluation-contract.md), then [Rubric and metrics](references/rubric-and-metrics.md) |
| Support release, installation, high-risk, or generalization claims | L3 | [Task-suite design](references/task-suite-design.md), then [Reporting and decisions](references/reporting-and-decisions.md) |
| Monitor versions or evaluation cycles | L4 | [Longitudinal evaluation](references/longitudinal-evaluation.md) |
| Trace method provenance | any | [Source map](references/source-map.md) |

Load only the owner of the active question. Do not preload every reference.

## Evidence read surface

Keep scored evidence immutable for the spec retention period. Read the analyzer summary first, then its failure index, then only the spec-bounded representative receipts. Open a receipt-owned raw artifact only for a named failure, grader disagreement, or integrity audit, following the exact index locator and hash. Never start with a tree walk or create per-step worknotes, per-notice JSON, or model-authored receipt copies. An early failing run remains an outcome failure, never an efficiency gain.

## Claim ceilings

| Level | Required evidence | Maximum claim |
|---|---|---|
| L0 | Whole-package inventory and static review | Static findings only |
| L1 | Focused scenarios with verified run receipts | Diagnostic behavior only |
| L2 | Frozen baseline/candidate scenarios, independent-case intervals, benefit and context guardrails | Scoped incremental usefulness |
| L3 | L2 plus sequestered holdout, adversarial controls, environment binding, and required manual-review receipt | Readiness for the tested scope only |
| L4 | Version lineage and repeated evaluation cycles | Version and cycle monitoring only |

Without selection, order, and composition receipts, L4 must not claim library-scale multi-Skill orchestration evidence.

## Non-negotiable invariants

- Spec v5, scenario v1 `requirements[]`, host manifest v1, one compiled plan v1, one run index v2, and self-hashed receipts v4 are the only runtime decision path. Never accept inline run scores, legacy case wires, or parallel oracle fields.
- L2+ contribution requires the same scenarios and controls for a no-Skill baseline and a candidate treatment: natural routing for a routing claim, or forced loading for explicit-invocation value. When both are declared, natural routing is the default comparison unless the analyzer caller selects the forced treatment; a prior comparator matches that mode.
- Repeats diagnose run variability; inference resamples distinct case means. Point lift or absolute pass rate cannot replace the declared positive lower-bound benefit gate.
- Missing, invalid, duplicate, or tampered evidence remains outside metric denominators and makes usefulness inconclusive. Treatment-attributable failures with complete host evidence remain valid outcome failures.
- Target-Skill context is verified from captured component artifacts. The frozen intended-trigger candidate plan is the attribution denominator; total input tokens cannot substitute for attributed body/reference cost.
- Safety and protected outcomes are unweighted guardrails. Utility cannot offset a material safety or protected-case failure.
- Static audit findings are provisional review locators. They never authorize deleting package resources, hiding matched text, weakening rules, or treating scanner silence as safety evidence.
- Empirical usefulness is `supported`, `not_supported`, `inconclusive_ceiling`, or `not_evaluable`. Manual review and deployment authority are separate final gates.
- Public templates contain placeholders. They are not live receipts, host evidence, or scored usefulness evidence.

## Run the owners

Run the matching CLI before opening its implementation source. Read implementation source only after a CLI failure when diagnosing an owning implementation defect.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/audit_skill_package.py" /path/to/skill
```

L0 emits bounded triage without sidecars. Add `--json audit.json` for a frozen report; `--json -` reserves stdout. Its states route review, never safety approval.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" contract eval-spec.l0.json
python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" contract eval-spec.json scenarios.jsonl host-manifest.json
```

For a selected model grader, normalize blinded calibration evidence before suite quality. Deterministic-grader-only specs omit calibration.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" calibration --spec draft-eval-spec.json \
  --ratings calibration-ratings.jsonl --labels calibration-gold.jsonl --output grader-calibration.json

python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" suite-quality \
  --spec draft-eval-spec.json --proof suite-quality-proof.json --output suite-quality.json
```

Compile only a final `execution.ready=true` spec; compilation starts no host or grader. The runner executes only `execute` entries, `--resume` seals recoverable attempts, and `--index` must equal the plan-declared path.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/compile_eval_plan.py" eval-spec.ready.json scenarios.jsonl host-manifest.json --output execution-plan.json
python3 "$SKILL_EVALUATOR_DIR/scripts/run_eval_plan.py" execution-plan.json --index artifacts/index.jsonl
```

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/analyze_runs.py" artifacts/index.jsonl \
  --spec eval-spec.ready.json --json summary.json --failure-index failures.json \
  --markdown summary.md
```

Analyzer exits: `0` complete supported/eligible or L0/L1 diagnostic; `1` verified not-supported or manual `hold|reject`; `2` contract/I/O error; `3` incomplete, invalid, unsupported, not-evaluable, inconclusive, or authority-ineligible. A required manual receipt is spec-relative. `--report-only` converts only `1` to `0`, never the states.

## Owner index

- [Evaluation contract](references/evaluation-contract.md): spec v5, levels, treatments, preparation gates, fairness, and claim ceilings.
- [Task-suite design](references/task-suite-design.md): scenario v1, frontier-model filter, requirements, protected controls, and holdout boundaries.
- [Execution and grading](references/execution-and-grading.md): host protocol, execution plan, receipt v4, artifacts, routing, usage, context, graders, and failure classification.
- [Rubric and metrics](references/rubric-and-metrics.md): independent-case intervals, benefit/context gates, and usefulness states.
- [Reporting and decisions](references/reporting-and-decisions.md): evidence, usefulness, manual authority, and external-decision boundaries.
- [Longitudinal evaluation](references/longitudinal-evaluation.md): version and cycle monitoring.
- [Source map](references/source-map.md): source provenance and exact implementation owners.
- [Contract schemas](schemas/README.md): Draft 2020-12 owners for the 3.0 wire contracts.
- [Evaluation report](templates/evaluation-report.md): the single conditional report template.
- Executable owners: [audit](scripts/audit_skill_package.py), [validator](scripts/validate_eval_suite.py), [compiler](scripts/compile_eval_plan.py), [runner](scripts/run_eval_plan.py), [analyzer](scripts/analyze_runs.py), and [I/O](scripts/evidence_io.py).
- Spec fixtures: [L0](templates/eval-spec.l0.example.json), [L1](templates/eval-spec.l1.example.json), and [L2](templates/eval-spec.example.json); public scenarios: [L1](templates/scenarios.l1.example.jsonl) and [L2](templates/scenarios.example.jsonl); [host manifest](templates/host-manifest.example.json).
- Preparation fixtures: [calibration ratings](templates/calibration-ratings.example.jsonl), [calibration gold](templates/calibration-gold.example.jsonl), and [suite-quality proof](templates/suite-quality-proof.example.json).
- Evidence fixtures: [run index](templates/runs.example.jsonl), [grader schema](templates/grader-output.schema.json), [grader prompt](templates/llm-grader-prompt.md), [holdout manifest](templates/holdout-manifest.example.json), and [holdout scenarios](templates/holdout-scenarios.example.jsonl).
