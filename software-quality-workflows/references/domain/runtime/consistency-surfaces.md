---
{
  "card_id": "sqw.domain.runtime.consistency-surfaces",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "runtime_version_boundary_decision",
    "runtime_surface_inventory",
    "compatibility_contract"
  ],
  "produces": [
    "runtime_consistency_artifact"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Runtime Consistency Surfaces

## Decision this card owns
Reconcile and prove code, configuration, tests, docs, CI, packaging, generated artifacts, installers, and public adapters against one selected runtime contract.

## Use when
- A runtime boundary is selected and applicable surfaces may disagree or retain stale support behavior.

## Do not use when
- The boundary decision is unresolved or no runtime-support surface changes.

## Required inputs
- Selected support/compatibility outcome, exact probes, manifests/lockfiles, code/tests, docs/CI/container, generated/package/installer metadata, examples/templates, public adapters, and consumer inventory.

## Procedure
1. Create a surface matrix and classify each observed value/behavior against the selected contract; local success does not prove consistency, and stale prose alone does not prove runtime failure.
2. For a raised floor, update the canonical declaration plus lock/docs/CI/container/generated/installer checks; prove clear rejection below and first-supported success.
3. For older support, characterize both sides, use one public contract with explicit allowed implementation differences, and exercise errors/serialization/persistence/public adapters.
4. Check CLI preflight/errors, protocol/plugin/service wrappers, user examples/templates, package/distribution metadata, and dormant/generated surfaces.
5. If a required environment is unavailable, record why, strongest static/nearby proof, exact unverified claim, and precise follow-up command/CI requirement without unapproved setup.
6. Report focused, affected, public, and canonical evidence separately; retain compatibility owner/retirement condition and clean task-owned toolchains/artifacts.

## Output contract
- Surface/value matrix, changed declarations, below/at-boundary and compatibility proof, generated/package/public status, unverified environments/follow-up, consumer/retirement state, cleanup, gaps and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at cross-surface consistency evidence; do not redefine the selected version contract here.
