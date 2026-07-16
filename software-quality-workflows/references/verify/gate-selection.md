---
{
  "card_id": "sqw.verify.gate-selection",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "change_surface",
    "available_gates",
    "risk_projection"
  ],
  "produces": [
    "verification_plan",
    "gate_scope"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Verification Gate Selection

## Decision this card owns
Select the focused, affected, public-surface, and canonical proof required for the bounded change.

## Use when
- Direct change lacks a defensible proof scope or nearby behavior can regress.

## Do not use when
- Required gates and their applicability are already recorded and fresh.

## Required inputs
- Change surface, callers, public surfaces, repository commands, risk, and baseline evidence.

## Procedure
1. Select valid RED evidence for behavior changes when a meaningful before/after distinction exists; syntax, import, environment, broken-fixture, or implementation-invented-helper failures do not count.
2. Choose the smallest focused gate that proves the changed contract, then add affected-area gates only for real dependent seams.
3. Add public-surface proof for APIs, schemas, protocols, CLIs, UIs, packages, generated clients, registration, installed copies, or fresh-process behavior.
4. Add risk-specific negative proof and rollback/operational evidence for security, data migration, release, or installed-runtime changes.
5. Preserve the repository-, plan-, CI-, verifier-, or user-named canonical command when applicable; do not invent a full-suite requirement solely from generic process language.
6. Record every inapplicable or infeasible gate with reason and the narrower evidence that remains available.
7. Bind each gate to source, scope, environment, expected distinction, and evidence artifact type.

## Output contract
- `red_gate|null`, `focused_gate`, `affected_gates`, `public_surface_gate|null`, `canonical_gate|null`, `risk_negative_gates`, `not_run`, and `baseline_ref|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when the proof plan is proportionate, executable, and identity-bound.
