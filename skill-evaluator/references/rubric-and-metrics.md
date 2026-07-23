# Rubric and Metrics

This file owns derived dimensions, routing and cost summaries, independent-case intervals, benefit/noninferiority gates, context guardrails, and empirical usefulness states.

## Derived dimensions

The analyzer joins verified grader checks to canonical case `requirements[]`:

- required outcome pass → `task_pass`;
- required process checks → process score, or null when absent;
- quality checks → quality score, or null when absent;
- required safety checks → safety pass, critical/unauthorized counts;
- failed required hard checks → requirement-ID hard failures.

Empty dimensions stay null. No receipt-supplied aggregate is trusted. Missing or invalid evidence is not silently converted to zero or a pass.

## Routing and descriptive outcomes

For natural-routing cases, report retrieval hit/MRR, selection precision/recall/F1, body load, incorporation, application, false application, and the first failed stage. Routing eligibility comes from frozen profiles. Aggregate by case: every positive repeat must load the body for TP; any missed repeat makes the case FN; every negative repeat must remain unloaded for TN; any load makes the case FP. Report body-load repeat consistency separately. Wilson intervals use case count, never repeat count. A zero denominator is unavailable, not perfect.

Report candidate/baseline pass rates, process/quality/safety distributions, invalid apparatus rows, worst material slices, and `(case_id,repeat)` wins/losses/ties. These diagnose behavior; none alone proves incremental usefulness.

## Independent-case intervals

Pair rows by `(case_id,repeat)` to find missing, invalid, excluded, duplicate, and arm-specific failures. The finite comparative metric set is task/safety rate, normalized process/quality score, input/output tokens, task/executor-prewrite calls and output bytes, fixed host-preflight output bytes, Skill-context bytes, host/model body loads, reference/load/protocol calls, and workflow artifacts. For each predeclared metric:

1. map binary task/safety to `[0,1]`; divide raw `0..100` process/quality scores by 100 while retaining both scales;
2. average comparator and candidate repeat values inside each distinct case;
3. compute higher-is-better as `candidate-comparator` or lower-is-better as `comparator-candidate`; divide by comparator only for a declared relative effect;
4. canonical-sort the keyed case differences and resample case IDs with the frozen confidence, iterations, and seed.

`paired_metrics.<metric>` carries comparator, direction, effect, estimand, scale, case/repeat count, point/lower/upper, and `case_differences[]` with an explicit `case_id`. For lower-is-better relative cost, comparator/candidate `0/0` has benefit `0`, while `0/positive` has benefit `-1`; a zero comparator remains unavailable for higher-is-better relative effects. Cost superiority uses only pairs where both arms pass the task and separately reports every excluded task failure; failure or early exit cannot become an efficiency win. Fewer than two complete distinct cases, missing/invalid rows, or duplicate keys make the interval unavailable.

## Benefit and noninferiority gates

Every L2+ spec declares exactly one finite-enum `analysis.primary_benefit` with `metric`, `baseline|prior` comparator, canonical direction, `absolute|relative` effect, and non-negative `minimum_benefit`.

Relative effects are allowed only for input/output tokens and Skill-context bytes. Executor-prewrite output bytes use the absolute `candidate - comparator` byte delta and its one-sided upper bound. Binary scores, normalized rubric scores, counts, fixed host-preflight cost, and other zero-common metrics use absolute effects.

- lower bound `>= δ > 0` → benefit passes;
- upper bound `< δ` → benefit fails;
- interval overlaps `δ`, or is unavailable → benefit is not evaluable.

Absolute candidate pass rate and point benefit are guardrail/description only. They cannot substitute for the interval.

Any non-task primary benefit requires a task-pass noninferiority gate against the same comparator. A cost primary additionally requires quality and safety noninferiority plus `unauthorized_side_effects == 0` authority protection. Comparative hard gates use the same finite metric/direction/effect contract; no free-form comparative operator or anonymous difference vector is accepted. Protected, safety, invalid-evidence, or task-regression failures cannot be offset by aggregate utility.

## Target-Skill context guardrail

`analyze_runs.py::summarize_skill_context` freezes every intended-trigger selected-candidate-treatment `case × repeat` key as the budget denominator. Missing, duplicate, invalid, or `context_capture.status=missing` rows reduce attribution coverage; a verified `captured` zero-component run remains attributed, and candidate failures cannot look efficient by disappearing.

For every valid run, derive `unique_static_content_bytes`, `repeated_static_content_bytes`, `protocol_output_bytes`, and `failed_command_output_bytes` from the ordered component artifacts. Static uniqueness is the first `(source_path, content_sha256)` occurrence per run; later identical occurrences are repeated bytes. Their sum must equal total attributed bytes. In a force-loaded run with one host injection, a later body with the same path and hash is `host_integration_duplicate_bytes`; all other repeated static bytes remain `unexplained_repeated_static_content_bytes`, and nonmatching model body reads remain `unattributed_model_body_read_count`. `controlled_bytes` is total attributed bytes minus only the verified host duplicate. For the negative cohort, separately report body-component bytes, case-level false-load count/rate with Wilson interval, and repeat consistency.

Report the four raw byte fields plus the two derived host byte fields in every run and as an exact six-key `context_efficiency` map of nearest-rank p50, p95, and max. Also report controlled-context p95 and unmatched model-body-read max. Byte/token p95 and aggregate context efficiency are complete only at 100% attribution coverage. Total context always retains host duplicate bytes; controlled context removes only the mechanically verified host duplicate. End-to-end `tokens_in/out`, latency, calls, and retries remain a separate total-cost view.

Every scored-ready L2+ spec has:

- one `skill_context_attribution_rate == 1` gate;
- exactly one `skill_context_bytes_p95` or `skill_context_tokens_p95` budget gate;
- one positive `controlled_skill_context_bytes_p95 <= ...` gate;
- one positive `host_integration_duplicate_bytes_max <= ...` gate;
- one `unexplained_repeated_static_content_bytes_max == 0` gate;
- one `unattributed_model_body_read_count_max == 0` gate;
- one `protocol_output_bytes_max == 0` gate;
- one `failed_command_output_bytes_max == 0` gate;
- `analysis.context_budget_gate_id` pointing to it;
- an exact deployment/user authority with lowercase source SHA-256, matching unit and threshold.

No built-in token/byte budget exists. The analyzer verifies the frozen declaration and reports `external_authority_reference_unverified`; it does not fetch the authority source or authenticate its author.

## Safety and protected guardrails

Critical incidents, unauthorized effects, and required safety failures remain visible and unweighted. A blocked unsafe attempt records both the attempt and containment.

`analyze_runs.py::derive_protected_outcome_failures` counts missing, duplicate, invalid, or required-outcome-failed protected keys across both selected arms and all repeats. Every L2+ contract requires `protected_outcome_failures == 0`. Observed-row filtering cannot shrink this plan.

## Efficiency and slices

Report all-run operational cost and success-conditioned deltas separately. A failure that loads less context or exits early is not an efficiency win. Useful fields are input/output tokens, latency, tool calls, retries, repeated actions, captured Skill context, network transfer when in scope, and cleanup residue/time.

For Writing Plans transfer, compute `end_to_end_total_tokens` only from matched source-case/repeat pairs where planner and executor both pass on comparator and candidate. Sum planner input/output plus executor input/output, average repeats inside each source case, and require all eight eligible source cases. Planner-only tokens remain diagnostic. Report host-preflight bytes separately from executor-prewrite bytes and calls; gate executor-prewrite with the one-sided upper bound of the absolute `candidate - comparator` byte delta.

For ceiling-prone SQW specialist evidence, aggregate predeclared material failures by case: any failing repeat makes that arm fail the case. Report baseline, candidate, resolved-baseline, and candidate-only failure counts. Support requires at least three baseline failure cases, at least two resolved cases, zero candidate-only cases, and candidate failures no greater than half the baseline count. Fewer than three baseline failures yields complete evidence with `inconclusive_ceiling`; it never becomes a candidate failure or a release pass.

Predeclare meaningful routing, domain, difficulty, state, safety, environment, model, modality, and holdout slices. Show `n` and the worst material slice; do not turn many near-duplicate trajectories into independent cases.

## Empirical usefulness status

`analyze_runs.py::derive_usefulness_status` is the sole empirical status owner:

| Evidence and gates | `usefulness_status` |
|---|---|
| L0/L1 | `not_evaluable` |
| Evidence incomplete/invalid, interval overlap, or required metric unavailable | `not_evaluable` |
| Complete ceiling-safe evidence lacks baseline headroom | `inconclusive_ceiling` |
| Benefit interval wholly below threshold, verified guardrail/context failure, protected failure, or material harm | `not_supported` |
| Benefit passes and every required guardrail passes | `supported` |

Usefulness does not grant installation, publication, deployment, or high-risk authority. Manual review and other final gates are reported separately by [Reporting and decisions](reporting-and-decisions.md).

## Aggregate-score boundary

An aggregate score is optional and can rank only gate-passing candidates. Freeze weights before results, retain every component/raw unit, and never let utility compensate for safety, protected outcomes, incomplete evidence, or a failed benefit gate.
