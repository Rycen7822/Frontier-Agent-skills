---
{
  "card_id": "sqw.test.patterns.native-rewrite-parity",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "old_new_runtime_contract",
    "approved_difference_inventory",
    "parity_fixtures_and_budgets"
  ],
  "produces": [
    "native_rewrite_parity_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Native Rewrite Parity Pattern

## Decision this card owns
Prove a replacement runtime/native implementation preserves the approved public contract and resource behavior independently of the old runtime.

## Use when
- A runtime/native rewrite replaces an implementation while compatibility/parity remains required.

## Do not use when
- The approved goal intentionally changes behavior without a compatibility obligation.

## Required inputs
- Versioned old-surface inventory, approved differences, representative fixtures, errors/state/cache/budget contracts, resource constraints, and rollback boundary.

## Procedure
1. Baseline commands/endpoints, validation/errors, caches, persistence, budgets, evaluation fixtures, and dormant help/subcommand/tool/low-budget/malformed paths.
2. Freeze allowed differences before implementation and add parity REDs one behavior group at a time.
3. Exercise the new implementation directly; it must not call the old runtime when independence is required.
4. Compare deterministic paths exactly and nondeterministic paths under predeclared tolerances; measure performance/resources when part of the goal.
5. Run focused new-runtime proof, cross-implementation fixtures, affected public smokes, and selected compatibility gates.
6. Report allowed differences separately from regressions; retain a bounded rollback until parity, then remove only task-owned build/cache artifacts.

## Output contract
- Baseline/new identities, fixture and command evidence, parity matrix, allowed differences, resource results, public/dormant coverage, rollback state, cleanup, and residual risk.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at native parity evidence; do not weaken equivalence or route through the old runtime to manufacture success.
