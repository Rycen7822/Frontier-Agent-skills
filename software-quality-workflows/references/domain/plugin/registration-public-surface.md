---
{
  "card_id": "sqw.domain.plugin.registration-public-surface",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "plugin_source_package_artifact",
    "registration_and_public_contract",
    "host_runtime_context"
  ],
  "produces": [
    "plugin_registration_public_artifact"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 8192,
  "neighbors": [
    {
      "edge_id": "plugin-registration-to-installed",
      "to_card_id": "sqw.domain.plugin.installed-surface-proof",
      "edge_mode": "hard",
      "hard_predicate_id": "installed-surface-required",
      "missing_decision": "Registration change requires fresh installed-process proof",
      "required_evidence": "Registered package identity, discovery/profile contract, and representative public smoke",
      "evict_when": "Fresh installed-surface proof recorded"
    }
  ]
}
---
# Plugin Registration and Public Surface

## Decision this card owns
Prove fresh-process discovery/registration and representative supported public success/rejection behavior without duplicate or stale capabilities.

## Use when
- Loader/registry/profile metadata, commands/tools/skills/hooks/UI, discovery, enablement, cache/reload, or public schemas change.

## Do not use when
- Source/package is not yet proven or no registration/public surface is implicated.

## Required inputs
- Source/package identity, intended present/absent capabilities, host/runtime/profile/discovery contract, registration metadata, public schemas/entrypoint, safe success/error probes, and side-effect authority.

## Procedure
1. Start a fresh supported process/loader context when discovery is startup-cached and bind it to the intended package/profile/discovery identity.
2. Assert intended presence and absence, detect duplicate/scan-visible backups, and separate stale current-process state from registration defect.
3. Exercise a representative read-only/isolated public success and designed rejection through the supported user entrypoint, not internal imports.
4. Compare public arguments/schema/errors with packaged metadata and classify failures at source, build, package, registration, public contract, harness, environment, permission, or stale process.
5. Reproduce at the lowest failing layer and verify any external/host side effect via returned identity/status; restore task-owned temporary configuration/state.
6. Require installed proof when registration behavior changed or source checkout could mask discovery/layout/provenance.

## Output contract
- Fresh-process/host/profile/package identity, present/absent/duplicate capability evidence, public success/error outcomes, failure layer, side-effect/restoration status, installed-proof need, gaps and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `plugin-registration-to-installed` | Registration change requires fresh installed-process proof | Registered package identity, discovery/profile contract, and representative public smoke | `sqw.domain.plugin.installed-surface-proof` | Fresh installed-surface proof recorded |

## Stop
Stop at registration/public evidence; do not reinstall repeatedly to hide the first failing layer.
