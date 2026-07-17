---
{
  "card_id": "sqw.delegation.fan-in-and-integration",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.delegation.fan-in-and-integration",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "delegation-fan-in-and-integration"
  ],
  "max_bytes": 8192
}
---
# Delegation Fan-In and Integration

## Decision this card owns
Validate delegated results against actual state, reconcile them in dependency order, and emit one controller-owned integration handoff.

## Use when
- One or more delegated result envelopes exist and the controller must accept, reject, serialize, or integrate their bounded outputs.

## Do not use when
- Work is still pending, result identity is unavailable, write/reconciliation authority is absent, or review/verification/publication is the current decision.

## Required inputs
- `workflow-intake`; slice manifests/dependency order; result envelopes and durable artifacts; current revision/scope/state; actual worktree/diff or remote handles; protected surfaces; integration seams; and downstream proof needs.

## Procedure
1. Re-observe source/scope/state and classify every result as current, stale, malformed, overlapping, out-of-scope, incomplete, or candidate-valid.
2. Inspect actual files/diffs/artifacts and independently verify consequential claims; worker summaries and reported tests are evidence proposals, not proof.
3. Reject authority expansion, undeclared side effects, protected-surface changes, shared-writer collisions, and results whose stable identity cannot be read back.
4. Reconcile accepted candidates serially in dependency order, preserving unrelated work and checking cross-slice contracts, dormant/generated/package surfaces, and canonical artifact ownership.
5. For read-only results, validate anchors and coverage, resolve conflicts, and synthesize only confirmed evidence; do not concatenate worker context or let children edit the canonical report concurrently.
6. Recompute the actual integrated change/evidence projection and list affected domain, review-tier, and verification needs for Router reselection.
7. Emit stale/retry/narrow-controller fallback decisions explicitly. Do not hide unresolved blockers or background-pending work behind partial integration.

## Output contract
- One `delegation-fan-in-and-integration` with per-slice disposition and evidence, validated candidate/artifact identities, reconciliation order and actual integrated diff/synthesis, conflicts/deviations, refreshed source/scope/state, affected-surface and downstream proof/review handoff, blockers, and residual risk.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the controller-owned integration handoff. Do not self-sign off, publish, or claim workflow completion.
