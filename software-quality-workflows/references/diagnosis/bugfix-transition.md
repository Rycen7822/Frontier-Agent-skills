---
{
  "card_id": "sqw.diagnosis.bugfix-transition",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "supported_cause_artifact",
    "request_mode",
    "change_authority",
    "scope_projection",
    "existing_patch_projection"
  ],
  "produces": [
    "change_handoff_or_diagnosis_closeout"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Bugfix Transition

## Decision this card owns
Decide whether a supported cause closes diagnosis, enters planning, or becomes an authorized change handoff to Direct.

## Use when
- A fresh supported-cause artifact exists and request mode plus change authority are known.

## Do not use when
- Root cause is only plausible, reproduction is stale, or an implementation probe is being mistaken for a final repair.

## Required inputs
- Supported cause and evidence, original reproduction, affected owner seam, current patch/worktree projection, request mode, scope, change authority, public/architecture/migration implications, and proof need.

## Procedure
1. For diagnose-only work, emit the supported cause, confidence boundary, limitations, and no-change closeout.
2. Preserve and characterize any existing patch; never discard user or concurrent work to recreate a preferred test order.
3. Identify the smallest owner seam that can correct the supported cause without bundling unrelated cleanup.
4. Route architecture, ownership, public-contract, migration, schema, or multi-component repair scope to the applicable planning/design boundary.
5. For an authorized local repair, define a meaningful regression distinction that fails for the supported gap rather than a fixture, import, harness, or setup error.
6. Bind the original reproduction, focused proof, affected/public proof needs, protected surfaces, and residual alternatives into the handoff.
7. Emit a change handoff; implementation, GREEN/refactor, gate selection, and completion remain owned by Direct, test, and verification cards.

## Output contract
- Either `diagnosis_closeout` or `change_handoff` containing supported cause/evidence, owner seam, observable regression distinction, allowed/protected surfaces, original reproduction, proof needs, route target (`planning` or `sqw.entry.direct-change`), and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when change authority is absent, repair scope exceeds the current boundary, or the cause is unsupported; never implement from this transition card.
