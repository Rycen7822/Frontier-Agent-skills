---
name: skill-evaluator
description: "Evaluate, benchmark, compare, regression-test, or security-audit an Agent Skill package. Use when deciding whether a skill triggers correctly, improves task outcomes over a no-skill or prior-version baseline, follows its intended process, remains efficient and safe, generalizes beyond development examples, or is ready to install, publish, or deploy."
metadata:
  version: 2.0.0
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
| L1 | Focused cases with verified run receipts | Diagnostic behavior only |
| L2 | Frozen baseline/candidate cases, independent-case intervals, benefit and context guardrails | Scoped incremental usefulness |
| L3 | L2 plus sequestered holdout, adversarial controls, environment binding, and required manual-review receipt | Readiness for the tested scope only |
| L4 | Version lineage and repeated evaluation cycles | Version and cycle monitoring only |

Without selection, order, and composition receipts, L4 must not claim library-scale multi-Skill orchestration evidence.

## Non-negotiable invariants

- Spec schema v3, canonical `requirements[]`, one receipt index, and one hashed receipt are the only decision inputs. Never accept inline run scores or legacy oracle fields.
- L2+ contribution requires the same cases and controls for a no-Skill baseline and a candidate treatment: natural routing for a routing claim, or forced loading for explicit-invocation value. When both are declared, natural routing remains the default comparison unless the analyzer caller selects the forced arm; a prior comparator matches the selected mode.
- Repeats diagnose run variability; inference resamples distinct case means. Point lift or absolute pass rate cannot replace the declared positive lower-bound benefit gate.
- Missing, invalid, duplicate, or tampered evidence remains outside metric denominators and makes usefulness inconclusive. Treatment-attributable failures with complete host evidence remain valid outcome failures.
- Target-Skill context is verified from captured component artifacts. The frozen intended-trigger candidate plan is the attribution denominator; total input tokens cannot substitute for attributed body/reference cost.
- A prior context delta is available only for one same-mode prior variant, complete 100% attributed paired rows, matching measurement sources, and successful outcomes; otherwise it is null.
- Safety and protected outcomes are unweighted guardrails. Utility cannot offset a material safety or protected-case failure.
- Static audit findings are provisional review locators. They never authorize deleting package resources, hiding matched text, weakening rules, or treating scanner silence as safety evidence.
- Empirical usefulness is `supported`, `not_supported`, `inconclusive`, or `not_applicable`. Manual review and deployment authority are separate final gates.
- Public templates contain placeholders. They are not live receipts, host evidence, or scored usefulness evidence.

## Run the owners

Run the matching CLI before opening its implementation source. Read implementation source only after a CLI failure when diagnosing an owning implementation defect.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/audit_skill_package.py" /path/to/skill
```

The L0 default is a bounded, package-relative triage summary and creates no sidecar files. Add `--json audit.json` only when a frozen evaluation or release contract requires the complete report; `--json -` reserves stdout for JSON and sends compact triage to stderr. `clean`, `review_required`, and `structural_invalid` are queue states, not safety approval.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py" eval-spec.json cases.jsonl
```

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/analyze_runs.py" receipt-index.jsonl \
  --spec eval-spec.json --json summary.json --markdown summary.md
```

The analyzer returns `0` for a completed supported/diagnostic result, `1` for verified not-supported or authority-blocked evidence, `2` for CLI/spec/case/index/I/O contract errors, and `3` for incomplete, invalid, or inconclusive evidence. Supply one `--manual-review-receipt <relative-path>` only when the frozen contract requires it. `--report-only` changes the process exit, never the reported states.

## Owner index

- [Evaluation contract](references/evaluation-contract.md): schema v3, levels, variants, fairness, and claim ceilings.
- [Task-suite design](references/task-suite-design.md): frontier-model filter, requirements, protected controls, and holdout boundaries.
- [Execution and grading](references/execution-and-grading.md): receipt v2, artifacts, routing, usage, context, graders, and failure classification.
- [Rubric and metrics](references/rubric-and-metrics.md): independent-case intervals, benefit/context gates, and usefulness states.
- [Reporting and decisions](references/reporting-and-decisions.md): evidence, usefulness, manual authority, and external-decision boundaries.
- [Longitudinal evaluation](references/longitudinal-evaluation.md): version and cycle monitoring.
- [Source map](references/source-map.md): source provenance and exact implementation owners.
- [Evaluation report](templates/evaluation-report.md): the single conditional report template.
- Executable owners: [package audit](scripts/audit_skill_package.py), [suite validator](scripts/validate_eval_suite.py), and [receipt analyzer](scripts/analyze_runs.py).
- Spec fixtures: [L0](templates/eval-spec.l0.example.json), [L1](templates/eval-spec.l1.example.json), and [L2](templates/eval-spec.example.json); public cases: [L1](templates/cases.l1.example.jsonl) and [L2](templates/cases.example.jsonl).
- Evidence fixtures: [receipt index](templates/runs.example.jsonl), [grader schema](templates/grader-output.schema.json), [grader prompt](templates/llm-grader-prompt.md), [holdout manifest](templates/holdout-manifest.example.json), and [public holdout placeholder](templates/holdout-cases.example.jsonl).
