# Reporting and Decisions

Use this owner after `analyze_runs.py` has atomically produced summary v4, failure index v1, optional full details/Markdown/observations, or after `compare_cycles.py` has produced comparison report/index v1. These outputs are separate immutable transactions. Human prose may explain them but cannot replace fields, repair evidence, or change authority.

## Status model

Keep all five analyzer axes separate:

- `applicability_status`: whether the frozen subject and claim make the selected modules applicable;
- `feasibility_status`: whether bound capability evidence supports execution;
- `evidence_status`: whether every disposition and required execute attempt is complete and valid;
- `usefulness_status`: whether complete feasible comparative evidence crosses benefit and guardrail gates;
- `final_authority_status`: whether the evidence is eligible for the declared external authority path.

Use exact values. `supported` is not promotion, and `eligible` is not approval. Unsupported/non-evaluable feasibility, incomplete/invalid evidence, any blocking gate or observation, a required hard failure, or an unmet manual gate keeps final authority blocked.

## Applicability by level

- L0 reports package audit findings and an `audit_only` claim boundary. It makes no runtime usefulness claim.
- L1 reports plan dispositions, receipt integrity, diagnostics, modules/stages, outcome, and cost. It does not claim incremental benefit.
- L2 adds a declared no-Skill baseline, independent-case uncertainty, benefit and guardrail gates, and usefulness status.
- L3 adds only the declared holdout, safety, or manual-authority evidence required by the frozen contract.
- L4 adds version/cycle comparisons under the same plan, scenario, receipt, and authority rules.

Delete sections that do not apply. Put missing required evidence in **Known gaps**; never fill an inapplicable row with invented `N/A` evidence.

## Default reading order

Read:

1. summary v4 for identity, five axes, counts, modules/stages, gates, cost, and trust boundaries;
2. failure index v1 for bounded stable failures and locators;
3. full details only when the index says `truncated=true` or a named omitted failure is required;
4. the representative receipt named by a failure ID;
5. a raw receipt artifact only through that receipt's verified path/hash and locator.

For an L4 comparison, read comparison report v1 first, then its diagnostic index, then only the bound cycle artifact named by a diagnostic locator. Do not reopen every receipt or reconstruct the cycle matrix.

Do not begin with the artifact tree, construct a parallel run matrix, or copy receipts into model-authored evidence files.

## Compact summary v4

The summary's required top-level facts are:

```yaml
schema_version: 4
evaluation_id: {{immutable evaluation ID}}
plan_id: {{compiled plan ID}}
analysis_ready: {{true|false}}
applicability_status: {{applicable|not_applicable}}
feasibility_status: {{feasible|unsupported|not_evaluable}}
evidence_status: {{complete|incomplete|invalid}}
usefulness_status: {{supported|not_supported|inconclusive_ceiling|not_evaluable}}
final_authority_status: {{eligible|blocked}}
subject: {{skill ID/version/shape/package hash}}
counts: {{plan/execute/unsupported/not-evaluable/attempt/valid/invalid/missing counts}}
blocking_observations: []
```

It also binds spec/scenario/host/plan identities, module decisions, treatments, primary benefit and paired metrics, module/stage summaries, coordination/action/independence/critique/grounding summaries, context cost, suite-quality/calibration/manual-authority status, representative failure IDs, sibling output manifest, and trust boundaries. The summary intentionally does not embed the full attempt/run matrix.

## Identity and frozen scope

Use the summary's subject, treatments, plan/spec/scenario/host hashes, package/catalog/policy identities, module evidence, and trust boundaries. Drill into the bound plan only when a named identity fact is outside the compact projection. Use immutable identities rather than `latest` paths.

For holdout evidence, report the public manifest hash, payload hash, custody status, and whether the payload was exposed. A public manifest is not the holdout payload.

## Failure index and output transaction

Each failure has one stable ID derived from its factual projection, family/code/severity/reason, evidence state, expected/observed fact, impact/retest, typed optional joins, exact locator, and occurrence count. Prose and ordering do not change identity. An index may truncate to the spec budget; counts and representative IDs still bind the full failure set.

When any sibling is requested, the analyzer preflights the complete immutable transaction and writes details → failure index → Markdown → summary. `output_manifest` binds the raw bytes, view/version, counts, truncation, and hashes of every emitted sibling. A byte-identical retry is allowed; conflicting existing bytes are refused. Summary self-hash removes only `summary_hash`; failure-index self-hash removes only `failure_index_hash`.

## Offline comparison report v1

The comparison report binds the plan hash, actual file hashes and cycle identities, registration status, comparability checks, metric/stage results, one revision state or transition classification, authority eligibility, claim ceiling, and diagnostic-index hash. The diagnostic index contains stable bounded facts and exact source locators; neither output copies complete summaries, observations, receipts, or absolute paths.

`revision` can report only `closed`, `open`, or `not_evaluable`. `model_transition` follows the frozen hard-gate and routing/loading/application precedence before value-retention classifications; `combined_model_harness_drift` never becomes single-factor attribution. `eligible` means only that local mechanical gates permit an external authority audit. It never means accepted, installed, published, deployed, deprecated, or removed.

## Independent-case attribution

Use the summary's keyed `paired_metrics` map:

- `case_count` is the number of distinct independent cases;
- point/lower/upper values come from one direction-normalized benefit per distinct case;
- `case_differences` maps each stable `case_id` to its direction-normalized difference;
- `excluded_pairs` counts treatment pairs excluded by the metric contract.

Never present repeats as independent statistical samples. Recover comparator, minimum benefit, confidence/iterations, and eligible modules from the bound estimand only when needed. If matrix or field coverage is incomplete, the metric is not evaluable.

## Gates and usefulness

Interpret `primary_benefit` first. Then use the bound plan and gate-family failures to account for every required hard gate; do not invent a second gate-results table inside the summary.

Usefulness is `supported` only when applicability and feasibility permit the claim, evidence is complete, the benefit passes, and every required quality/calibration/module/host/context/protected/safety/noninferiority gate passes. Report all other states exactly; do not repair them in prose.

Use module and stage summaries to localize routing, state, fault, coordination, action, observation, critique, independence, grounding, and host failures. Preserve decisive case IDs through failure locators even when aggregates pass.

## Skill context and total cost

`context_cost` reports attribution coverage; paired total, controlled, and controlled-core Skill-context byte metrics; tokens; queue/runtime latency; calls; retries/rework; workflow artifacts/checkpoints/residue; failure/recovery overhead; and cache facts. Keep provider token-cache classes separate from application-cache evidence. `captured + 0 components` is valid zero-context evidence; missing capture blocks attribution. Bytes never become token counts.

## Findings and known gaps

Each failure-index item records ID, family/code, severity, reason key, evidence state, typed joins, expected/observed facts, exact locator, impact, retest, and occurrence count. Keep observed facts separate from root-cause inference.

List every missing, invalid, blocked, contaminated, or out-of-scope evidence item and state which claim it blocks. A model-only or static-heuristic finding remains provisional until the declared corroboration path completes.

## Exit and immutable retry

Analyzer exit `0` means a complete supported/eligible or L0/L1 diagnostic result; `1` means verified not-supported evidence or a manual `hold|reject`; `2` means CLI/spec/plan/index/I/O contract failure; `3` means incomplete, invalid, unsupported, not-evaluable, inconclusive, or otherwise authority-ineligible evidence. `--report-only` converts only exit `1` to `0`; it never changes summary states.

## Manual authority

When the spec declares manual review, report the verified receipt path/hash, reviewer role, decision, evidence objects/hashes, attestation, and the fact that signature text was not cryptographically verified. Missing, malformed, duplicated, or non-matching authority receipts fail closed.

## L4 boundary

L4 is limited to controlled revision and model-transition evidence. Without verified selection, order, and composition receipts, the report must not claim library-scale multi-Skill orchestration evidence. It may report closure, drift, protected regressions, retained value, absorption candidates, context change, and rollback triggers only within its frozen claim ceiling.

## External decision record

An external owner may record install, release, publication, deployment, rollback, or residual-risk decisions after reviewing the immutable analyzer transaction. That record names exact artifact hashes and never mutates or self-promotes the analyzer result. Use `templates/evaluation-report.md` only for this bounded interpretation/decision overlay. Its placeholders are not evidence.
