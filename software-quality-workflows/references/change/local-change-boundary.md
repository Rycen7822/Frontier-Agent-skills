---
{
  "card_id": "sqw.change.local-change-boundary",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "repository_ownership_evidence",
    "dependency_evidence",
    "requested_outcome",
    "scope_projection"
  ],
  "produces": [
    "owner_seam",
    "change_boundary"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Local Change Boundary

## Decision this card owns
Choose the smallest existing owner seam that can implement the requested behavior coherently.

## Use when
- Direct change cannot identify a defensible owner or dependency boundary.

## Do not use when
- The seam is already established, or the choice changes a public contract.

## Required inputs
- Callers, dependencies, governing policy, tests/contracts, source revision, scope/protected-work projection, and requested observable distinction.

## Procedure
1. Trace the real caller-to-outcome and read the complete owning semantic unit.
2. Identify where governing policy/state currently lives and which callers depend on it.
3. Compare narrow existing seams by coherence, dependency effect, and ability to express the whole distinction.
4. Reject pass-through wrappers, parallel implementations, speculative extension points, and seams requiring hidden public-contract change.
5. Bind source revision, allowed writes/effects, protected/dirty/concurrent surfaces, and smallest affected dependency set.
6. Escalate multi-owner, architecture, migration, or public-contract ambiguity; otherwise record one seam or a typed blocker.

## Output contract
- `owner_seam`, `source_identity`, `allowed_write_effect_surface`, `protected_surface`, `dependency_effect`, `escalation|null`, `evidence_refs`, and `blocker|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after one owner seam and boundary are recorded; reroute from the resulting artifact.
