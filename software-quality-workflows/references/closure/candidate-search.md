---
{
  "card_id": "sqw.closure.candidate-search",
  "card_version": 1,
  "kind": "phase",
  "consumes": [
    "search_phase_projection",
    "frozen_contract_projection",
    "qualified_baseline_projection",
    "qualified_verifier_projection",
    "budget_projection"
  ],
  "produces": [
    "candidate_search_proposal"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Candidate Search

## Decision this card owns
Generate, evaluate, prune, repair, and propose promotion of bounded candidates under frozen contract/verifier identities and controller-owned budgets.

## Use when
- Controller projects `SEARCHING` with a qualified baseline/verifier bundle and remaining authorized search budget.

## Do not use when
- Contract, source, baseline, verifier, protected surface, authority, or budget identity is stale or unfrozen.

## Required inputs
- Current incumbent and comparator projection, contract constraints/corners, qualified verifier cascade, candidate/worktree leases, allowed/protected read/write/effect sets, strategy/parent/counterexample identity, resource limits, and remaining budget.

## Procedure
1. Create each writable candidate in one isolated worktree with exact allowed/protected surfaces, parent, strategy, target counterexamples, and idempotent cleanup identity.
2. Use parallel writers only when write/resource sets are disjoint and evaluation capacity makes parallelism net-positive; availability alone is not activation.
3. Evaluate candidates through the frozen cost-increasing cascade, preserving original results and classifying product, harness, environment, permission, stochastic, and contract failures.
4. Convert product failures into replayable contract-preserving counterexamples; minimize irrelevant dimensions without weakening corners, thresholds, or public entrypoints.
5. Repair only candidate-local failures within the proven invalidation slice. Hidden/shared state, root-assumption, protected-oracle, non-local, or authority changes require global escalation or plan revision.
6. Apply the controller-defined strict lexicographic comparator; do not self-promote, erase failed candidates, or launder skipped gates.
7. Record budget consumption, candidate/evaluation hashes, pruning reasons, residual alternatives, cleanup status, and the proposed incumbent or typed non-convergence disposition.

## Output contract
- `candidate_search_proposal`: candidate/evaluation/counterexample refs, comparator trace, proposed incumbent|null, invalidation scope, budget state, skipped tiers, cleanup, limitations, disposition, and evidence refs.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop on stale bindings, unsafe isolation, exhausted budget, non-local invalidation, no eligible candidate, or proposed promotion; never change durable phase or incumbent directly.
