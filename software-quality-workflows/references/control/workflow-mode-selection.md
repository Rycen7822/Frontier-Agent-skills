---
{
  "card_id": "sqw.control.workflow-mode-selection",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "request_mode",
    "route_facts",
    "authority_projection",
    "scope_projection",
    "recovery_need"
  ],
  "produces": [
    "workflow_mode_decision"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Workflow Mode Selection

## Decision this card owns
Choose the lightest execution mode, M0 through M3, that preserves authority, proof, recovery, and auditability for the current boundary.

## Use when
- Route facts show a possible durable-state, recovery, delegation, external-effect, or multi-session boundary.
- A current mode may need an evidence-backed upgrade or downgrade.

## Do not use when
- A fresh mode decision already covers the unchanged source, scope, authority, and recovery facts.
- The question concerns state transitions, event acceptance, retry, locks, or closure; those are controller-owned operator decisions.

## Required inputs
- Request mode, route facts, authority and scope projections, proof cost, failure locality, recovery horizon, external-state seams, and shared-state evidence.

## Procedure
1. Select M0 for a same-session, local and reversible change with a known owner seam and focused proof.
2. Select M1 only when an append-only observed trace adds evaluation value; never predeclare an execution graph.
3. Select M2 for independently recoverable or costly boundaries such as delegated slices, public contracts, expensive gates, approvals, external state, dirty concurrency, or durable handoff.
4. Select M3 for multi-session migration, release, destructive recovery, shared mutable state, repeated real-runtime stability work, or strong audit and resume needs.
5. Upgrade only when authority, source, hidden or shared state, conflict, failure locality, or proof assumptions invalidate the lighter mode.
6. Downgrade when the risky boundary is closed and retained state no longer adds recovery value.
7. Never use file count, token count, available workers, or subjective complexity alone as an upgrade signal.
8. Return the selected mode and stable reason codes without granting new authority.

## Output contract
- `workflow_mode_decision`: `mode`, source/scope/authority bindings, stable reason codes, upgrade and downgrade triggers, retention boundary, and unresolved blocker if any.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when the lightest justified mode is selected or required route evidence is missing; emit a typed blocker instead of guessing an unsafe fact.
