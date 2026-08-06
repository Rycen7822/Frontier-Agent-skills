# Rubric and Metrics

This file owns the five independent status axes, module/stage summaries, case-cluster inference, non-compensating gates, context/cost semantics, independence/critique/grounding summaries, and empirical usefulness.

## Five independent axes

The analyzer derives these axes without allowing one to rewrite another:

| Axis | Values | Question |
|---|---|---|
| `applicability_status` | `applicable|not_applicable` | Does the frozen subject/claim require evaluable modules? |
| `feasibility_status` | `feasible|unsupported|not_evaluable` | Do bound host capabilities permit the planned work? |
| `evidence_status` | `complete|incomplete|invalid` | Are every required plan disposition and execute attempt verified? |
| `usefulness_status` | `supported|not_supported|inconclusive_ceiling|not_evaluable` | Does complete feasible comparative evidence cross the frozen gates? |
| `final_authority_status` | `eligible|blocked` | May this evidence proceed to its declared external authority? |

An unsupported capability is not a candidate failure. Complete evidence for an unsupported/non-evaluable plan still blocks usefulness and final authority. A treatment failure on a supported path remains valid outcome evidence.

## Derived dimensions

The analyzer joins verified grader checks to scenario v1 `requirements[]`:

- required outcome pass → `task_pass`;
- required process checks → process score, or null when absent;
- quality checks → quality score, or null when absent;
- required safety checks → safety pass, critical/unauthorized counts;
- failed required hard checks → requirement-ID hard failures.

Empty dimensions stay null. No receipt-supplied aggregate is trusted. Missing or invalid evidence is not silently converted to zero or a pass.

## Module and stage summaries

Every module summary reports planned, present, valid, invalid, missing, eligible, pass rate/interval when evaluable, repeat consistency, hard requirement IDs, failure mechanisms, worst slice, and one status. A `not_applicable` module has zero planned/present work; activating one cannot silently add unrelated plan entries or host requests.

Stage summaries use exact frozen denominators. Plan stages are existence, contract quality, compliance, execution, and outcome. Required runtime surfaces add only their declared routing, state, fault, coordination, action/safety, observation/grounding, critique, independence, or host-conformance stages. Each stage reports eligible, reached, passed, status, and a stable reason key. A legitimate routing no-match counts against its exact expected cell, not a target-presence proxy.

Module/stage pass rates, candidate/baseline outcomes, repeat consistency, failures, and worst slices are descriptive. They do not replace the primary-benefit interval or hard gates.

## Independent-case intervals

Pair rows by `(case_id,repeat)` to find missing, invalid, excluded, duplicate, and treatment-specific failures. The finite comparative metric set is task/safety rate, normalized process/quality score, input/output tokens, task/executor-prewrite calls and output bytes, fixed host-preflight output bytes, Skill-context bytes, host/model body loads, reference/load/protocol calls, and workflow artifacts. For each predeclared metric:

1. map binary task/safety to `[0,1]`; divide raw `0..100` process/quality scores by 100 while retaining both scales;
2. average comparator and candidate repeat values inside each distinct case;
3. compute higher-is-better as `candidate-comparator` or lower-is-better as `comparator-candidate`; divide by comparator only for a declared relative effect;
4. canonical-sort the keyed case differences and resample case IDs with the frozen confidence, iterations, and seed.

`paired_metrics.<metric>` carries comparator, direction, effect, estimand, scale, case/repeat count, point/lower/upper, and `case_differences[]` with an explicit `case_id`. For lower-is-better relative cost, comparator/candidate `0/0` has benefit `0`, while `0/positive` has benefit `-1`; a zero comparator remains unavailable for higher-is-better relative effects. Cost superiority uses only pairs where both treatments pass the task and separately reports every excluded task failure; failure or early exit cannot become an efficiency win. Fewer than two complete distinct cases, missing/invalid rows, or duplicate keys make the interval unavailable.

## Benefit and noninferiority gates

Each L2+ causal question declares an `analysis.estimands[]` item with metric, candidate/comparator treatment IDs, canonical direction, `absolute|relative` effect, minimum benefit, and eligible modules. The analyzer's compact `primary_benefit` is the bound primary estimand result; it is not a receipt-supplied score.

Relative effects are allowed only for input/output tokens and Skill-context bytes. Executor-prewrite output bytes use the absolute `candidate - comparator` byte delta and its one-sided upper bound. Binary scores, normalized rubric scores, counts, fixed host-preflight cost, and other zero-common metrics use absolute effects.

- lower bound `>= δ` → benefit passes; normally `δ > 0`; a finite release sentinel may use `δ = 0` only when candidate required failures are independently forbidden and `minimum_baseline_failure_cases > 0` supplies corpus materiality;
- upper bound `< δ` → benefit fails;
- interval overlaps `δ`, or is unavailable → benefit is not evaluable.

Absolute candidate pass rate and point benefit are guardrail/description only. They cannot substitute for the interval.

Any non-task primary benefit requires a task-pass noninferiority gate against the same comparator. A cost primary additionally requires quality and safety noninferiority plus zero unauthorized effects. Hard gates have one declared kind, metric, direction, threshold, authority, and required flag. Protected, safety, invalid-evidence, module, context, host, calibration, quality, or task-regression failures cannot be offset by aggregate utility.

Calibration v2 evaluates `minimum_examples` and `minimum_agreement` independently for every selected model check. The artifact records exact per-check sample and agreement metrics; one failing check closes the gate regardless of aggregate or dimension-level values. Optional reviewer corroboration does not lower the judge-to-gold or manual-authority requirements.

## Target-Skill context guardrail

`analyze_runs.py::summarize_skill_context` freezes every intended-trigger selected-candidate-treatment `case × repeat` key as the budget denominator. Missing, duplicate, invalid, or `context_usage.status=missing` rows reduce attribution coverage; a verified `captured` zero-component run remains attributed, and candidate failures cannot look efficient by disappearing.

For every valid run, derive static, repeated, protocol-output, failed-command-output, host-integration-duplicate, unexplained-repeated, unique-reference, controlled, and controlled-core bytes from verified components. Static uniqueness uses `(source_path, content_sha256)` per run. Only the one verified force-load host duplicate is removed from controlled bytes; controlled-core additionally removes the first occurrence of each reference identity. Repeated references remain overhead.

Context-byte comparisons use every valid, fully attributed pair even when either task outcome fails; task failure gates remain independent. Other lower-is-better cost metrics exclude failed task pairs so an incomplete task cannot look efficient.

Scored context claims require complete attribution plus the exact frozen context gates selected by the decision: total/controlled burden, duplicate/unexplained loads, unmatched body reads, protocol/failed output, and any token or byte budget. The package defines no universal budget. External authority references remain attestations unless independently verified.

## Safety and protected guardrails

Critical incidents, unauthorized effects, and required safety failures remain visible and unweighted. A blocked unsafe attempt records both the attempt and containment.

`analyze_runs.py::derive_protected_outcome_failures` counts missing, duplicate, invalid, or required-outcome-failed protected keys across both selected treatments and all repeats. Every L2+ contract requires `protected_outcome_failures == 0`. Observed-row filtering cannot shrink this plan.

## Efficiency and slices

Report all-run operational cost and success-conditioned deltas separately. `context_cost` keeps input/output/cache token classes, queue/runtime latency, tool/network calls, retries/rework, requested/effective effort, artifacts/checkpoints/residue, pricing identity, and per-principal/turn/phase/call totals. Failure/recovery overhead has its own class and denominator. A failure that loads less context or exits early is not an efficiency win.

Baseline headroom is a factual prerequisite for a usefulness claim. Complete evidence with insufficient headroom is `inconclusive_ceiling`; it is neither candidate failure nor release support.

`analysis.materiality.minimum_baseline_failure_cases` is the required number of distinct comparator failure cases used by that headroom check. It is not an estimand sample-size declaration; independent-case counts remain explicit in each interval.

Predeclare meaningful routing, domain, difficulty, state, safety, environment, model, modality, and holdout slices. Show `n` and the worst material slice; do not turn many near-duplicate trajectories into independent cases.

## Independence, critique, and grounding

`independence_summary` is derived from principal identity, context mode, rationale/test exposure, model genealogy, evidence sources, and blinded calibration—not from a declared “independent” label. Same-principal review, forked/shared context, shared rationale, or prohibited shared lineage is dependent; missing required facts is unknown/not evaluable.

`critique_summary` keeps detection, acceptance, uptake, repair, and final outcome distinct. A correct critique that is ignored, consensus without independent evidence, or accepted advice without a verified repair cannot self-promote usefulness.

`grounding_summary` requires correct claim, source existence, source support, exact attribution, and freshness. Correct bytes that are stale, or a retrieved source that does not support the claim, fail at their own stage.

## Empirical usefulness status

`analyze_runs.py::derive_usefulness_status` is the sole empirical status owner:

| Evidence and gates | `usefulness_status` |
|---|---|
| L0/L1 | `not_evaluable` |
| Applicability or feasibility does not permit a comparative claim | `not_evaluable` |
| Evidence incomplete/invalid, interval overlap, or required metric unavailable | `not_evaluable` |
| Complete ceiling-safe evidence lacks baseline headroom | `inconclusive_ceiling` |
| Benefit interval wholly below threshold, verified guardrail/context failure, protected failure, or material harm | `not_supported` |
| Benefit passes and every required guardrail passes | `supported` |

Usefulness does not grant installation, publication, deployment, or high-risk authority. Manual review and other final gates are reported separately by [Reporting and decisions](reporting-and-decisions.md).

## Non-compensation boundary

No aggregate, vote, critique, cache hit, partial branch, or concise prose conclusion can compensate for incomplete/invalid evidence, unsupported feasibility, a failed benefit or required module gate, safety/protected harm, unauthorized effect, or blocked manual authority.
