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

For natural-routing cases, report retrieval hit/MRR, selection precision/recall/F1, body load, incorporation, application, false application, and the first failed stage. Routing eligibility comes from frozen profiles. A zero denominator is unavailable, not perfect.

Report candidate/baseline pass rates, process/quality/safety distributions, invalid apparatus rows, worst material slices, and `(case_id,repeat)` wins/losses/ties. These diagnose behavior; none alone proves incremental usefulness.

## Independent-case intervals

Pair rows by `(case_id,repeat)` to find missing, invalid, excluded, duplicate, and arm-specific failures. For each allowlisted paired field (`task_pass`, `process_score`, `quality_score`, `safety_pass`):

1. compute candidate-minus-baseline at each complete repeat;
2. average repeat differences inside each distinct case;
3. pass the case vector to `analyze_runs.py::summarize_case_differences`;
4. canonical-sort the vector and resample case IDs with the frozen confidence, iterations, and seed.

The result is `{point,lower,upper,paired_case_count,resampling_unit="case_id"}`. Fewer than two complete distinct cases, missing/invalid/excluded rows, or duplicate keys make the interval unavailable. `run_pair_count` and `repeat_count` remain diagnostics and never become inferential sample size.

## Benefit and noninferiority gates

Every L2+ spec designates exactly one positive comparative lower-bound benefit gate through `analysis.usefulness_benefit_gate_id`.

- lower bound `>= δ > 0` → benefit passes;
- upper bound `< δ` → benefit fails;
- interval overlaps `δ`, or is unavailable → benefit is not evaluable.

Absolute candidate pass rate and point lift are guardrail/description only. They cannot substitute for benefit.

If benefit is process, quality, or safety rather than task outcome, `analysis.task_noninferiority_gate_id` points to a different task-lift lower-bound `>=` a non-positive margin. A noninferiority gate is never itself positive benefit.

## Target-Skill context guardrail

`analyze_runs.py::summarize_skill_context` freezes every intended-trigger selected-candidate-treatment `case × repeat` key as the denominator. Missing, duplicate, invalid, or `context_capture.status=missing` rows reduce attribution coverage; a verified `captured` zero-component run remains attributed, and candidate failures cannot look efficient by disappearing.

For every run, derive `unique_static_content_bytes`, `repeated_static_content_bytes`, `protocol_output_bytes`, and `failed_command_output_bytes` from the ordered component artifacts. Static uniqueness is the first `(source_path, content_sha256)` occurrence per run; later identical occurrences are repeated bytes. Their sum must equal total attributed bytes.

Report the four fields in every run and as an exact four-key `context_efficiency` map of nearest-rank p50, p95, and max. Byte/token p95 and aggregate context efficiency are complete only at 100% attribution coverage. Necessary unique static content has no separate size gate; total context p95 remains authoritative. End-to-end `tokens_in/out`, latency, calls, and retries remain a separate total-cost view.

Every scored-ready L2+ spec has:

- one `skill_context_attribution_rate == 1` gate;
- exactly one `skill_context_bytes_p95` or `skill_context_tokens_p95` budget gate;
- one `repeated_static_content_bytes_max == 0` gate;
- one `protocol_output_bytes_max == 0` gate;
- one `failed_command_output_bytes_max == 0` gate;
- `analysis.context_budget_gate_id` pointing to it;
- an exact deployment/user authority with lowercase source SHA-256, matching unit and threshold.

No built-in token/byte budget exists. The analyzer verifies the frozen declaration and reports `external_authority_reference_unverified`; it does not fetch the authority source or authenticate its author.

## Safety and protected guardrails

Critical incidents, unauthorized effects, and required safety failures remain visible and unweighted. A blocked unsafe attempt records both the attempt and containment.

`analyze_runs.py::derive_protected_outcome_failures` counts missing, duplicate, invalid, or required-outcome-failed protected keys across both selected arms and all repeats. `protected_outcome_failures == 0` is mandatory for scored-ready L2+ evidence. Observed-row filtering cannot shrink this plan.

## Efficiency and slices

Report all-run operational cost and success-conditioned deltas separately. A failure that loads less context or exits early is not an efficiency win. Useful fields are input/output tokens, latency, tool calls, retries, repeated actions, captured Skill context, network transfer when in scope, and cleanup residue/time.

Predeclare meaningful routing, domain, difficulty, state, safety, environment, model, modality, and holdout slices. Show `n` and the worst material slice; do not turn many near-duplicate trajectories into independent cases.

## Empirical usefulness status

`analyze_runs.py::derive_usefulness_status` is the sole empirical status owner:

| Evidence and gates | `usefulness_status` |
|---|---|
| L0/L1 | `not_applicable` |
| Evidence incomplete/invalid, interval overlap, or required metric unavailable | `inconclusive` |
| Benefit interval wholly below threshold, verified guardrail/context failure, protected failure, or material harm | `not_supported` |
| Benefit passes and every required guardrail passes | `supported` |

Usefulness does not grant installation, publication, deployment, or high-risk authority. Manual review and other final gates are reported separately by [Reporting and decisions](reporting-and-decisions.md).

## Aggregate-score boundary

An aggregate score is optional and can rank only gate-passing candidates. Freeze weights before results, retain every component/raw unit, and never let utility compensate for safety, protected outcomes, incomplete evidence, or a failed benefit gate.
