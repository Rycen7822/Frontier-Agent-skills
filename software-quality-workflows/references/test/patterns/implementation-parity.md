---
{
  "card_id": "sqw.test.patterns.implementation-parity",
  "card_version": 2,
  "kind": "recipe",
  "decision_id": "sqw.select.test.patterns.implementation-parity",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "test-patterns-implementation-parity"
  ],
  "max_bytes": 8192
}
---
# Implementation Parity Pattern

## Decision this card owns
Prove independently executed language, runtime, native, extracted, or replacement implementations preserve one approved observable contract and its resource behavior.

## Use when
- `workflow-intake` requires compatibility or parity across implementations, including a native/runtime rewrite.

## Do not use when
- Contracts intentionally differ without a compatibility obligation or shared fixtures would hide legitimate platform semantics.

## Required inputs
- `workflow-intake`; characterized public behavior for every implementation; old/new and per-language identities; versioned data-only fixtures/schema; inputs, outputs, errors, state, cache and budget contracts; representative dormant and malformed paths; predeclared allowed differences and normalization/tolerances; resource constraints; and rollback boundary.

## Procedure
1. Inventory commands/endpoints, validation/errors, state/caches/persistence, budgets and dormant help/subcommand/tool/low-budget/malformed paths for every implementation. Freeze allowed platform or migration differences before changes.
2. Encode shared inputs, outputs and error cases in a versioned data-only fixture. Load and execute it natively in every language/runtime; when independence is required, the new implementation cannot call or route through the old one.
3. Add one behavior RED per affected implementation and behavior group, then refactor language/runtime-local helpers and callers in bounded slices.
4. Compare deterministic outcomes and serialized errors exactly under the canonical normalization rule. Compare nondeterministic or resource behavior only under predeclared tolerances; record intentional differences outside fixture execution code.
5. Run focused native tests, cross-implementation fixtures, affected public and installed smokes, dormant-path checks, selected compatibility gates, and performance/resource proof when required.
6. Report allowed differences separately from regressions. Retain the prior implementation or bounded rollback until parity and consumer gates pass, then remove only task-owned build/cache/fixture wiring.

## Output contract
- One `test-patterns-implementation-parity` with implementation identities, fixture/schema revision, per-implementation command/status evidence, normalized outcome/error and resource matrix, allowed differences, public/installed/dormant coverage, rollback state, cleanup, and residual risk.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at independent parity evidence; do not weaken equivalence, erase intentional differences, or route through another/old implementation to manufacture success.
