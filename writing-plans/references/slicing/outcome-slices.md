---
{
  "card_id": "wp.slicing.outcome-slices",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "planning_disposition",
    "canonical_decisions",
    "dependency_scope_evidence"
  ],
  "produces": [
    "typed_outcome_slices",
    "current_frontier"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 8192,
  "neighbors": [
    {
      "edge_id": "slices-to-context-capsules",
      "to_card_id": "wp.slicing.context-capsules",
      "edge_mode": "hard",
      "hard_predicate_id": "cross-context-slice",
      "missing_decision": "A cross-context slice lacks a bounded capsule contract",
      "required_evidence": "Canonical node, dependencies, identities, authority, and proof",
      "evict_when": "Current-node capsule specification is emitted"
    }
  ]
}
---
# Outcome Slices

## Decision this card owns
Form typed, independently judgeable outcome slices and the current conflict-safe frontier from canonical decisions.

## Use when
- Handoff/Program needs dependencies, parallel-safety, migration order, or resumable outcome nodes.

## Do not use when
- A Brief is enough or design/intent/root cause remains unresolved.

## Required inputs
- Ready planning disposition; selected decisions/invariants; source/scope/authority; dependencies/effects/resources; acceptance/proof; rollout/rollback; contract refs when closure applies.

## Procedure
1. Choose vertical, contract-first, risk-first, cleanup-first, compatibility, or verification-only shape by the observable result and risk—not file count.
2. Give each node one objective/completion criterion, stable inputs/outputs/dependencies, owner seam, allowed read/write/resource sets, effects/approval, proof distinction, false-green risk, and rollback/removal condition.
3. Split when required context cannot fit one bounded current-node projection or failure cannot be localized. Avoid horizontal layer batches that delay integration evidence.
4. Add typed control/data/evidence/invariant/effect/resource/approval edges and conservatively detect read/write/resource conflicts before calling nodes parallel-safe.
5. Compute the topologically ready current frontier; leave future fog coarse and candidate strategy exploration in SQW state, never canonical nodes.
6. Under closure, bind node constraint/corner/verifier refs and epoch; semantic contract change requires a new plan/contract epoch.
7. Select the capsule edge only for a slice that crosses a turn, agent, or session.

## Output contract
- Typed nodes/edges, current frontier, conflict/exclusion reasons, proof/rollback, contract refs, fog, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `slices-to-context-capsules` | A cross-context slice lacks a bounded capsule contract | Canonical node, dependencies, identities, authority, and proof | `wp.slicing.context-capsules` | Current-node capsule specification is emitted |

## Stop
Stop when each admitted slice is judgeable and the current frontier is conflict-safe or typed blocked.
