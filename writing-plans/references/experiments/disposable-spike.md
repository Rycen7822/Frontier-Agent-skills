---
{
  "card_id": "wp.experiments.disposable-spike",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "plan_route",
    "feasibility_question",
    "source_evidence"
  ],
  "produces": [
    "spike_verdict"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Disposable Feasibility Spike

## Decision this card owns
Answer one source-bound feasibility question with a disposable experiment; never authorize production integration.

## Use when
- Source inspection cannot settle one falsifiable fact that blocks profile selection or Closure Contract freeze.
- Closure Admission identifies one bounded feasibility fact that must be resolved before contract compilation.
- The user explicitly asks to compare or de-risk an idea before committing to a production build.

## Do not use when
- Current source or documentation already answers the question.
- The requested work is production implementation, or several coupled questions require a Program investigation.

## Required inputs
- One stable spike ID, the decision it unlocks, a Given/When/Then criterion, fresh source/runtime evidence, authority, and cleanup boundary.

## Procedure
1. Put the highest idea-killing risk first and state one observable falsification criterion.
2. Inspect only enough current evidence to select a meaningful experiment.
3. Build the smallest isolated probe and exercise the happy path plus the most discriminating edge case.
4. Record commands, artifacts, observations, constraints, and surprises.
5. Return exactly one verdict: `validated`, `partial`, or `invalidated`; `partial` names the unresolved condition.
6. Delete the probe or retain it only in an explicitly task-owned disposable location.
7. Require a fresh production plan and SQW proof before any promotion.

## Output contract
- One `spike_verdict` containing spike ID, decision unlocked, criterion, evidence refs, experiment boundary, verdict, constraints, and cleanup/promotion disposition.
- Silent promotion is forbidden: spike code, fixtures, mocks, candidate state, and inferred authority are never production inputs by default.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when evidence answers the single question or the bounded experiment cannot proceed; do not expand into implementation.
