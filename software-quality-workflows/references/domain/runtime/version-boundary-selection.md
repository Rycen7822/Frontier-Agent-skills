---
{
  "card_id": "sqw.domain.runtime.version-boundary-selection",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "runtime_support_inventory",
    "boundary_probe_evidence",
    "consumer_requirements"
  ],
  "produces": [
    "runtime_version_boundary_decision"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "runtime-to-consistency",
      "to_card_id": "sqw.domain.runtime.consistency-surfaces",
      "edge_mode": "hard",
      "hard_predicate_id": "runtime-version-boundary-selected",
      "missing_decision": "Runtime boundary is selected but declarations and consumers are not reconciled",
      "required_evidence": "Selected support contract, exact probe versions, and affected surface inventory",
      "evict_when": "Consistency-surface artifact recorded"
    }
  ]
}
---
# Runtime Version-Boundary Selection

## Decision this card owns
Select an explicit supported runtime contract from exact boundary evidence: raise floor, compatible fallback, optional isolation, or honestly unverified.

## Use when
- Declared support may conflict with used API/syntax/module/flag behavior or an adjacent runtime/version boundary must be decided.

## Do not use when
- Runtime support is unaffected or the task only needs to reconcile already-selected declarations.

## Required inputs
- Advertised range, exact local/package-manager versions, repository declarations, questioned feature/path, core/optional/build/public role, old consumers, and exact bad/good/public-path probes if available.

## Procedure
1. Inventory manifests, lock roots, docs, CI, containers, generated clients/packages, installers/adapters, feature availability, and consumers requiring older versions.
2. Probe the exact lowest advertised runtime and nearest known bad/good versions through the real import/parse/build/start/public path; preserve versions, statuses, and failure classes.
3. Keep environment acquisition separate and authority-bound; prefer installed/pinned/container/CI evidence and never download a runtime implicitly for convenience.
4. Select one outcome: raise floor; define/test a semantically bounded compatibility implementation; isolate a genuinely optional feature with observable absence; or `unverified` with exact missing environment/claim.
5. Reject broad dependencies hidden by narrow exceptions. Compatibility requires behavior/errors/performance limits, owner, and retirement condition.
6. Record old/new support, consumer impact, exact evidence, allowed differences, unavailable boundary, cleanup, and whether consistency reconciliation is required.

## Output contract
- Selected outcome/support range, authoritative source/evidence revisions, probe matrix/statuses, consumer impact, compatibility/optional contract, unverified claim/follow-up, cleanup, and `next_edge_id`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `runtime-to-consistency` | Runtime boundary is selected but declarations and consumers are not reconciled | Selected support contract, exact probe versions, and affected surface inventory | `sqw.domain.runtime.consistency-surfaces` | Consistency-surface artifact recorded |

## Stop
Stop after an explicit version-boundary decision; never call an unavailable boundary proven or mutate environments without authority.
