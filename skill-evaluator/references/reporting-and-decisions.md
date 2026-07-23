# Reporting and Decisions

Use this owner after `analyze_runs.py` has produced JSON or Markdown. The report explains verified evidence and bounded decision signals; it does not turn missing evidence into a favorable conclusion or make a deployment decision for the operator.

## Status model

Keep these three axes separate:

- `evidence_status`: whether the frozen run matrix is complete and valid;
- `usefulness_status`: whether comparative evidence supports incremental benefit without a guardrail or protected-outcome failure;
- `final_authority_status`: whether the evidence is eligible for the declared external decision path.

Use the analyzer's exact values. `supported` usefulness is not a promotion, and `eligible` authority is not an approval. Final authority is `eligible` only when usefulness is `supported`, every required manual gate passes, the candidate has zero required hard-grader failures, and `blocking_observations` is empty. Every other state is `blocked`.

## Applicability by level

- L0 reports package audit findings and an `audit_only` claim boundary. It makes no runtime usefulness claim.
- L1 reports candidate diagnostics, receipt integrity, run accounting, routing, outcome, and cost. It does not claim incremental benefit.
- L2 adds a declared no-Skill baseline, independent-case uncertainty, benefit and guardrail gates, and usefulness status.
- L3 adds only the declared holdout, safety, or manual-authority evidence required by the frozen contract.
- L4 adds version/cycle comparisons under the same receipt, case, and authority rules.

Delete sections that do not apply. Put missing required evidence in **Known gaps**; never fill an inapplicable row with invented `N/A` evidence.

## Executive block

Start with the analyzer-owned facts:

```yaml
evaluation_id: {{immutable evaluation ID}}
level: {{L0|L1|L2|L3|L4}}
evidence_status: {{complete|incomplete|invalid}}
usefulness_status: {{supported|not_supported|inconclusive_ceiling|not_evaluable}}
final_authority_status: {{eligible|blocked}}
decision_signal: {{analyzer decision signal}}
target: {{package identity and hash}}
baseline: {{declared baseline identity, L2+ only}}
claim_scope: {{model/harness/suite/environment}}
blocking_observations: []
```

Do not replace these axes with a single aggregate score or prose verdict.

## Identity and frozen scope

Report candidate revision/source/plugin hashes, target package hash, suite treatment-contract hash, receipt-to-treatment index hash, model and harness, environment fingerprint, spec/cases/case-contracts/fixture-set/grader-set/grader-schedule hashes, authority boundary, declared variants, repeat count, and claim ceiling. Use immutable identities rather than `latest` paths.

For holdout evidence, report the public manifest hash, payload hash, custody status, and whether the payload was exposed. A public manifest is not the holdout payload.

## Receipt integrity and run accounting

Report:

- receipt verification status and checked-run count;
- expected, observed, valid, invalid, timed-out, and missing `variant × case_id × repeat` keys;
- duplicate keys and receipt/index identity mismatches;
- fixture, package, artifact, grader, provenance, and deterministic-invocation binding failures;
- trust boundaries that remain externally attested or unverified.

An invalid receipt is invalid evidence. Do not summarize claims copied from a trace, final answer, or host event when the receipt binding failed.

`p3-arm-report/2.0` repeats the candidate identity and frozen input hashes, binds the decision contract raw bytes, the receipt index, the receipt-to-treatment index, and the exact task/planner/transfer analysis inputs, then carries separate `evidence_status` and `usefulness_status`. `p3-aggregate-report/2.0` fixes the ordered evaluated skill IDs, binds each arm's raw file bytes, and is `passed` only when every arm is complete and supported. Both self-hash by removing only `report_hash` and hashing canonical UTF-8 JSON. Missing evidence is incomplete; identity, schema, apparatus, capture, conservation, or self-hash failure is invalid; complete unsupported or ceiling-inconclusive evidence blocks the aggregate.

## Independent-case attribution

Use the report's keyed `paired_metrics` map:

- `case_count` is the number of distinct independent cases;
- `repeat_count` describes repeats per case and never becomes inferential `n`;
- point/lower/upper values come from one direction-normalized benefit per distinct case;
- every difference names its `case_id` and retains comparator/candidate raw and reported-scale values;
- `paired_task_failures` discloses cost pairs excluded because either arm failed the task.

Never present repeats as independent statistical samples. Report comparator, metric, direction, effect, estimand, scale, threshold, interval, and keyed contrary cases. If the matrix or required field coverage is incomplete, report the interval as not evaluable. For lower-is-better relative cost only, encode comparator/candidate `0/0` as zero benefit and `0/positive` as `-1`; other relative zero-comparator cases remain not evaluable. Report executor-prewrite as the absolute `candidate - comparator` byte delta with a one-sided upper bound.

## Gates and usefulness

List the single `primary_benefit` separately, then every frozen hard gate with metric, comparator when comparative, direction/effect, threshold, observed value, and status.

Usefulness is `supported` only when evidence is complete, the benefit gate passes, every guardrail passes, protected outcomes have no failure, and no material safety harm was observed. Report `not_supported`, `inconclusive_ceiling`, or `not_evaluable` exactly as derived; do not repair the status in prose.

Show routing and task outcomes by declared slice. Preserve decisive case-level failures even when aggregates pass.

## Skill context and total cost

Report attributed Target-Skill context separately from end-to-end usage:

- intended-trigger denominator and complete attributed-run count;
- attribution rate and measurement-source counts;
- verified component bytes, host-receipt tokens when present, and p95 values;
- body/resource loading closure against routing facts;
- total input/output tokens and latency from usage, plus typed task/executor-prewrite/load/protocol/workflow counts and residue;
- transfer host-preflight bytes separately from executor-prewrite bytes, plus matched planner+executor total tokens;
- context-budget authority reference and its externally unverified trust boundary.

`captured + 0 components` is valid zero-context evidence. `missing` capture blocks attribution. Replay-manifest bytes do not become token counts.

## Findings and known gaps

Each finding records an ID, severity, affected dimension/cases, observed fact, evidence locator, confidence basis, impact, root-cause status, and required retest. Keep observed facts separate from root-cause inference.

List every missing, invalid, blocked, contaminated, or out-of-scope evidence item and state which claim it blocks. A model-only or static-heuristic finding remains provisional until the declared corroboration path completes.

## Manual authority

When the spec declares manual review, report the verified receipt path/hash, reviewer role, decision, evidence objects/hashes, attestation, and the fact that signature text was not cryptographically verified. Missing, malformed, duplicated, or non-matching authority receipts fail closed.

## L4 boundary

L4 is limited to version and cycle monitoring. Without verified selection, order, and composition receipts, the report must not claim library-scale multi-Skill orchestration evidence. It may compare immutable versions/cycles and report drift, protected regressions, context change, and rollback triggers only.

## Artifact manifest

End with immutable paths or hashes for the spec, case/holdout bindings, receipt index, receipts and bound artifacts, package inventory, environment fingerprint, grader outputs, analyzer JSON/Markdown, package audit, manual-review receipt when declared, and cleanup evidence.

Use `templates/evaluation-report.md` as the conditional skeleton. Public examples and placeholders are not evaluation evidence.
