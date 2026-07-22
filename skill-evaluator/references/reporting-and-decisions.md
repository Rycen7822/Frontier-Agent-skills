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
usefulness_status: {{not_applicable|supported|not_supported|inconclusive}}
final_authority_status: {{eligible|blocked}}
decision_signal: {{analyzer decision signal}}
target: {{package identity and hash}}
baseline: {{declared baseline identity, L2+ only}}
claim_scope: {{model/harness/suite/environment}}
blocking_observations: []
```

Do not replace these axes with a single aggregate score or prose verdict.

## Identity and frozen scope

Report candidate revision/source/plugin hashes, target package hash, treatment/catalog identities, model and harness, environment fingerprint, spec/cases/case-contracts/fixture-set/grader-set/grader-schedule hashes, authority boundary, declared variants, repeat count, and claim ceiling. Use immutable identities rather than `latest` paths.

For holdout evidence, report the public manifest hash, payload hash, custody status, and whether the payload was exposed. A public manifest is not the holdout payload.

## Receipt integrity and run accounting

Report:

- receipt verification status and checked-run count;
- expected, observed, valid, invalid, timed-out, and missing `variant × case_id × repeat` keys;
- duplicate keys and receipt/index identity mismatches;
- fixture, package, artifact, grader, provenance, and deterministic-invocation binding failures;
- trust boundaries that remain externally attested or unverified.

An invalid receipt is invalid evidence. Do not summarize claims copied from a trace, final answer, or host event when the receipt binding failed.

Arm report v2 repeats the candidate identity and all frozen input hashes, binds the receipt index's raw file bytes, and carries separate `evidence_status` and `usefulness_status`. Its `report_hash` uses the same self-field-removal canonical algorithm as receipt v2. Aggregate input identities are raw arm-report file hashes, not reserialized object hashes. A missing arm is incomplete; a schema, identity, capture, conservation, or self-hash failure is invalid; a complete arm whose benefit is unsupported remains complete evidence.

## Independent-case attribution

Separate descriptive run pairs from inferential cases:

- `run_pair_count` describes matched repeat-level outcomes;
- `paired_case_count` is the number of distinct cases in the case-cluster interval;
- wins, losses, tie-pass, and tie-fail are descriptive pair diagnostics;
- interval point/lower/upper values come from one case-mean difference per distinct case.

Never present repeats as independent statistical samples. Report the confidence level, iterations, seed, resampling unit, missing paired fields, and candidate-only/baseline-only case IDs. If the matrix or required field coverage is incomplete, report the interval as not evaluable.

## Gates and usefulness

List every frozen hard gate with metric, operator, threshold, observed value, and status. Identify the single designated benefit gate separately from guardrails.

Usefulness is `supported` only when evidence is complete, the benefit lower-bound gate passes, every guardrail passes, protected outcomes have no failure, and no material safety harm was observed. Report `not_supported`, `inconclusive`, or `not_applicable` exactly as derived; do not repair the status in prose.

Show routing and task outcomes by declared slice. Preserve decisive case-level failures even when aggregates pass.

## Skill context and total cost

Report attributed Target-Skill context separately from end-to-end usage:

- intended-trigger denominator and complete attributed-run count;
- attribution rate and measurement-source counts;
- verified component bytes, host-receipt tokens when present, and p95 values;
- body/resource loading closure against routing facts;
- total input/output tokens and latency from usage, plus typed task/prewrite/load/protocol/workflow counts and residue;
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
