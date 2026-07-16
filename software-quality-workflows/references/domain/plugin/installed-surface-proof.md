---
{
  "card_id": "sqw.domain.plugin.installed-surface-proof",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "plugin_build_package_identity",
    "authorized_install_or_existing_copy",
    "installed_smoke_contract"
  ],
  "produces": [
    "plugin_installed_surface_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Plugin Installed-Surface Proof

## Decision this card owns
Prove installed/copied layout, provenance, assets/dependencies, fresh discovery, and public entrypoint independently of the source checkout.

## Use when
- Installed behavior is an acceptance surface and source/build/package evidence cannot prove actual layout/discovery/runtime resolution.

## Do not use when
- Installation/configuration mutation is unauthorized or source/package proof is incomplete.

## Required inputs
- Canonical build/package/install entrypoints, source/worktree/build/package identity, host discovery/profile/cache contract, neutral cwd, isolated config/state, exact public smoke/error, and side-effect ceiling.

## Procedure
1. Inspect staging/package for declared entrypoints, metadata, schemas/templates/migrations/assets/dependencies; run a built-artifact smoke before installation.
2. If installation is authorized, use the canonical installer; otherwise inspect an existing copy read-only and mark install proof unavailable.
3. Inspect installed tree/provenance independently and prove runtime asset resolution `source→build→package→installed→runtime` without incidental source files.
4. From a neutral cwd and fresh process, inspect identity/capabilities; run one safe public success and designed rejection.
5. Localize built/package/installed/discovery/public/stale-process failures; do not clean unrelated caches/profiles/plugins or test against primary data.
6. Restore and verify temporary configuration, remove only task-owned state/processes, and keep backups outside discovery roots.

## Output contract
- Source/build/package/installed identities, asset/dependency path matrix, neutral-cwd/fresh-process discovery, public outcomes, first failing layer, install authority/action, restoration/cleanup and gaps.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at fresh installed evidence; never authorize installation or infer provenance from the source tree.
