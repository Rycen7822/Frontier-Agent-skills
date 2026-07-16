---
{
  "card_id": "sqw.control.verifier-independence",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "required_oracle_inventory",
    "candidate_change_surface",
    "risk_and_authority_projection"
  ],
  "produces": [
    "verifier_independence_contract"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Verifier Independence

## Decision this card owns
Define which oracles and protected surfaces remain independent of the candidate so its evidence cannot grade or weaken itself.

## Use when
- Autonomous closure or another high-consequence task needs a frozen authoritative oracle set/protected verifier boundary.

## Do not use when
- Ordinary gate selection/execution is sufficient, or full closure verifier qualification is the current controller phase.

## Required inputs
- Contract/source/scope/environment identity, required oracles and risks, candidate write/effect set, existing protected tests/benchmarks/goldens/holdouts/policies/authority, candidate-added tests, and outer/hidden verifier availability for kernel changes.

## Procedure
1. Classify each required oracle's authority and independence from candidate code, data, thresholds, expected outputs, environment, and selection/ranking.
2. Protect contract/verifier locks, controller/policy, authoritative tests, benchmark definitions/thresholds, goldens/holdouts, publication/authority manifests, and counterexample adapters from candidate writes/effects.
3. Treat candidate-added tests as `candidate_supplementary`; they cannot alone satisfy a hard constraint. Promotion requires controller validation, independent review/sensitivity, and test-lifecycle acceptance in a new epoch.
4. A kernel/verifier change needs an outer meta-contract plus independent old/hidden/holdout proof; the changed kernel cannot approve itself.
5. Record invalidation triggers for oracle/threshold/golden/holdout/environment/counterexample/protected-path changes and require dependent candidate/sign-off evidence to requalify.
6. Emit qualification needs/limitations for the controller operator; do not execute generic gates, qualify the closure bundle, promote candidates, or close workflow here.

## Output contract
- Oracle authority/independence map, protected paths/effects, candidate-test status, outer-verifier need, invalidation/epoch rules, qualification requirements, limitations and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at a protected independence contract; an unavailable or self-derived oracle is never counted as pass.
