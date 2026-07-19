# Release Notes

## Bundle 2.0.1 implicit-local activation

Bundle 2.0.1 changes the canonical pair's Codex invocation policy from explicit-only shadow operation to `implicit_local_pilot`. Both `agents/openai.yaml` files set `allow_implicit_invocation: true`; `bundle-manifest.json` sets `implicit_routing_default: true`; remote writes remain false.

Activation is no longer overloaded as a release signal. Staging and release package evidence both report `activation_ceiling: implicit_local_pilot`. Only `output_class: release` with matching external `release-evidence/2.0` can satisfy the release gate. Scored L2 evidence, a clean signed source revision, an activation decision, publication, deployment, credentials, and remote writes remain independent prerequisites.

The atomic install and rollback unit remains the exact `writing-plans` 5.0.0 plus `software-quality-workflows` 6.0.0 pair. The bundle and plugin patch version is 2.0.1; skill instruction versions do not change because their workflow contracts and schemas are unchanged.

## Historical bundle 2.0.0 candidate

This candidate atomically pairs `writing-plans` 5.0.0 with `software-quality-workflows` 6.0.0 as `frontier-engineering/6.0.0+5.0.0`. The generated bundle binds both complete skill roots, policy registries, reference-card manifests, and exact cross-skill contracts at schema epoch 2.

The active inventory is exactly 10 Writing Plans cards plus 52 Software Quality Workflows cards. Total card bytes are 171,402, the largest card is 4,526 bytes, and the two entrypoints total 11,665 bytes.

The deterministic route replay executes all 62 cards, 16 entry branches, 62 near misses, 10 protected negatives, and five outcome-linked terminal paths. Entry accuracy, decision precision, decision recall, terminal completion, and protected-negative pass rate are 1.0; unnecessary card loads are zero. This is deterministic diagnostic evidence only.

The checked-in activation level remains `shadow`. Implicit routing and remote writes are false. Source archives, plugin staging, static discovery, and isolated CLI install/remove are model-free release-surface checks and do not authorize a pilot or publication.

## Packaging identity

- Plugin folder and manifest name: `frontier-engineering-plugin`
- Plugin display name: `Frontier Engineering`
- Plugin version: `2.0.1`
- Bundle archive root: `frontier-engineering-bundle`
- Skills-only archive roots: `writing-plans`, `software-quality-workflows`
- Build evidence: `plugin-build-evidence/2.0`
- Release evidence: `release-evidence/2.0`
- Static smoke: `static-plugin-smoke/2.0`
- CLI smoke: `cli-install-smoke/2.0`
- Source archive evidence: `source-archive-evidence/2.0`

Candidate-local P5 evaluation artifacts and P6-named packaging schemas were removed. Scored L2 evidence and activation decisions now exist only in revision-bound external run roots, preventing candidate self-reference.

## Intentional compatibility removals

The writing compatibility layer was removed instead of retained as redirects. The following legacy files no longer exist:

- `writing-plans/references/compatibility-map.json`
- `writing-plans/references/context-compaction-resistant-upgrade-plans.md`
- `writing-plans/references/evidence-backed-standalone-roadmaps.md`
- `writing-plans/references/fillable-requirements-glossary-pattern.md`
- `writing-plans/references/legacy-manifest-diff-compatibility.md`
- `writing-plans/references/local-artifact-cleanup-and-benchmark-fixture-expansion.md`
- `writing-plans/references/plan-absorbed-skill.md`
- `writing-plans/references/research-reference-materials.md`
- `writing-plans/references/result-preserving-optimization-plans.md`
- `writing-plans/references/spike-absorbed-skill.md`
- `writing-plans/scripts/validate_compatibility_stubs.py`
- `writing-plans/scripts/migrate_legacy_plan_ids.py`

No redirect or permanent compatibility stub is provided. Callers must use the current decision IDs, maps, manifests, and state schemas.

## Historical 1.0.0 record

The prior 1.0.0 candidate paired Writing Plans 4.0.0 with Software Quality Workflows 5.0.0 and used P4/P5/P6 promotion labels. Those labels are historical only and do not enter current package behavior, schemas, scripts, or tests.

## Rollback boundary

Rollback restores both installed skill directories from the same pre-install backup; a one-skill rollback is invalid. Merge, release, deploy, credentials, publication, and remote writes retain independent authorization gates.
