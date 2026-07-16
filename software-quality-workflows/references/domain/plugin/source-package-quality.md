---
{
  "card_id": "sqw.domain.plugin.source-package-quality",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "plugin_source_build_package_inventory",
    "acceptance_layer_matrix",
    "change_scope"
  ],
  "produces": [
    "plugin_source_package_artifact",
    "missing_plugin_layer"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "plugin-to-registration",
      "to_card_id": "sqw.domain.plugin.registration-public-surface",
      "edge_mode": "hard",
      "hard_predicate_id": "plugin-registration-implicated",
      "missing_decision": "Loader, registry, discovery, or public capability is implicated",
      "required_evidence": "Registration metadata, expected capability surface, host/runtime versions, and public entrypoint",
      "evict_when": "Registration/public-surface artifact recorded"
    },
    {
      "edge_id": "plugin-to-installed-surface",
      "to_card_id": "sqw.domain.plugin.installed-surface-proof",
      "edge_mode": "hard",
      "hard_predicate_id": "installed-surface-required",
      "missing_decision": "Installed behavior is an acceptance surface and proof is absent",
      "required_evidence": "Built/package identity, authorized install boundary, discovery root, and smoke contract",
      "evict_when": "Fresh installed-surface proof recorded"
    }
  ]
}
---
# Plugin Source and Package Quality

## Decision this card owns
Prove plugin source, built output, and distributable/package as distinct artifacts and select the first unresolved higher acceptance layer.

## Use when
- Plugin source, build, packaging, generated assets, runtime dependencies, or shipped file layout changes.

## Do not use when
- Only registration/public invocation or an already-built installed copy is under test.

## Required inputs
- Public surface/host-runtime inventory, canonical build/package paths, source revision, schemas/assets/dependencies/metadata, supported variants, acceptance matrix, and change authority.

## Procedure
1. Record source, built output, package, installed, registration, and public layers separately as pass/fail/not-run/not-applicable; a lower green layer never proves a higher one.
2. Prove source behavior/schemas, then build every supported user-facing path and run the built entrypoint.
3. Inspect generated tree and distributable independently for entrypoints, manifests, schemas, templates, migrations/static assets, permissions, versions, dependency/module strategy, and runtime-relative resolution.
4. Ensure shipped code uses only declared package assets/dependencies rather than source-checkout layout; verify every supported asset variant.
5. Preserve source/build/package provenance and classify the first failure boundary without exposing private machine details.
6. If registration is implicated, choose it before installed proof. Otherwise choose installed only when it is the acceptance surface and its contract is ready.

## Output contract
- Per-layer status/evidence through package, file/asset/dependency/provenance matrix, supported build paths, first failing boundary, registration/installed implication, cleanup, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `plugin-to-registration` | Loader, registry, discovery, or public capability is implicated | Registration metadata, expected capability surface, host/runtime versions, and public entrypoint | `sqw.domain.plugin.registration-public-surface` | Registration/public-surface artifact recorded |
| `plugin-to-installed-surface` | Installed behavior is an acceptance surface and proof is absent | Built/package identity, authorized install boundary, discovery root, and smoke contract | `sqw.domain.plugin.installed-surface-proof` | Fresh installed-surface proof recorded |

## Stop
Stop at source/package evidence and one unresolved layer; do not install or infer shipped behavior from source tests.
