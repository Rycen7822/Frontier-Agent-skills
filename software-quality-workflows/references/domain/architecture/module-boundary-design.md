---
{
  "card_id": "sqw.domain.architecture.module-boundary-design",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "architecture_change_pressure",
    "current_ownership_and_callers",
    "design_constraints"
  ],
  "produces": [
    "module_boundary_contract",
    "missing_architecture_decision"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "architecture-to-dependency-boundary",
      "to_card_id": "sqw.domain.architecture.dependency-boundary-design",
      "edge_mode": "semantic",
      "missing_decision": "Dependency direction, ownership, or cycle is unresolved",
      "required_evidence": "Current dependency graph, policy owners, failure and lifecycle boundaries",
      "evict_when": "Dependency boundary contract recorded"
    },
    {
      "edge_id": "architecture-to-alternatives",
      "to_card_id": "sqw.domain.architecture.alternative-decision",
      "edge_mode": "semantic",
      "missing_decision": "Multiple material module designs remain viable",
      "required_evidence": "Current/status-quo design, constraints, callers, and dependency facts",
      "evict_when": "Alternative decision recorded"
    }
  ]
}
---
# Module-Boundary Design

## Decision this card owns
Place the smallest coherent internal module seam that improves real policy ownership, caller knowledge, and change locality.

## Use when
- A change creates/splits/merges modules, adapters, extension points, or internal ownership seams.

## Do not use when
- The contract is externally/cross-team consumed, or only formatting/file layout changes without independent ownership pressure.

## Required inputs
- Outcome/change pressure, current policy/invariant/side-effect owners, direct/effective callers, constraints, existing language/conventions, and caller-observable proof.

## Procedure
1. Inventory the effective interface: names/types/defaults/invariants; errors/retry/partial/cancel/cleanup; ordering/idempotency/concurrency/state; construction/lifecycle; side effects; material resource behavior.
2. Identify concrete pressure now: observed independent changes, duplicated policy, defects, trust/process boundaries, shared-state coordination, or migration need. Do not start from a preferred pattern.
3. Evaluate leverage, locality, and coherence. Apply deletion/distribution tests: what policy/volatility disappears with the seam, and where would one representative policy change require edits?
4. Place a narrow seam only around real external/trust/process/persistence/lifecycle/ownership boundaries; avoid pass-through, test-only, hypothetical, vendor-leaking, or incidental orchestration interfaces.
5. Discover domain language from code/schema/tests/callers and scenario-test ambiguous terms before naming the boundary.
6. Record outcome, ownership, callers, pressures, constraints, proposed interface, hidden knowledge, proof, transition/temporary-path needs, and unresolved dependency/alternative decision.

## Output contract
- Module-boundary contract with owner/interface/callers, pressure, leverage/locality evidence, constraints, language, seam/deletion/distribution results, proof needs, transition, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `architecture-to-dependency-boundary` | Dependency direction, ownership, or cycle is unresolved | Current dependency graph, policy owners, failure and lifecycle boundaries | `sqw.domain.architecture.dependency-boundary-design` | Dependency boundary contract recorded |
| `architecture-to-alternatives` | Multiple material module designs remain viable | Current/status-quo design, constraints, callers, and dependency facts | `sqw.domain.architecture.alternative-decision` | Alternative decision recorded |

## Stop
Stop at one module-boundary decision or one missing decision; do not implement, migrate, or claim architecture completion.
