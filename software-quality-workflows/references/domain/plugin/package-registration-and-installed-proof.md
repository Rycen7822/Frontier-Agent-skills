---
{
  "card_id": "sqw.domain.plugin.package-registration-and-installed-proof",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.domain.plugin.package-registration-and-installed-proof",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "domain-plugin-package-registration-and-installed-proof"
  ],
  "max_bytes": 8192
}
---
# Plugin Package, Registration, and Installed Proof

## Decision this card owns
Prove source/build/package, fresh registration/public behavior, and installed provenance as distinct acceptance layers.

## Use when
- Plugin source, generated assets, packaging, registration/discovery, public capabilities, installed layout, or runtime-relative resolution changes.

## Do not use when
- No plugin/package/registration/installed/public surface is implicated.

## Required inputs
- `workflow-intake`; source revision; canonical build/package/install entrypoints; host/runtime/profile/discovery contract; manifests/schemas/templates/migrations/assets/dependencies/permissions; supported variants; intended capabilities; public success/rejection; neutral cwd; isolated config/state; install/effect authority.

## Procedure
1. Record source, build, package, installed, registration, and public layers separately as pass/fail/not-run/not-applicable; lower-layer GREEN never proves a higher layer.
2. Prove source behavior/schemas, build every supported user-facing path, run built entrypoints, and inspect generated/distributable trees independently for entrypoints, metadata, assets, dependencies, permissions, versions, and runtime-relative resolution.
3. Ensure shipped code uses declared package bytes rather than incidental checkout layout and bind `source→build→package→installed→runtime` provenance.
4. Start a fresh supported loader/profile context when discovery is startup-cached. Assert intended presence/absence, detect duplicate or scan-visible backups, and separate stale-process state from registration defects.
5. Exercise one safe public success and designed rejection through the supported entrypoint; compare arguments/schema/errors with package metadata and classify the first failure at source/build/package/registration/public/harness/environment/permission/stale process.
6. If installed behavior is required, use the canonical installer only with authority; otherwise inspect an existing copy read-only and mark install proof unavailable. From neutral cwd/fresh process prove installed tree, assets, discovery, and public behavior independently.
7. Never reinstall repeatedly to hide the first failing layer, test against primary user data, or clean unrelated caches/profiles/plugins. Restore task-owned configuration/state/processes and keep backups outside discovery roots.

## Output contract
- One `domain-plugin-package-registration-and-installed-proof` with per-layer identity/status, file/asset/dependency/provenance matrix, supported variants, fresh-process capability presence/absence/duplicates, public success/rejection, installed authority/action and neutral-cwd proof, first failing layer, restoration/cleanup, gaps, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the highest authorized acceptance layer; never infer installed behavior from source or authorize installation here.
