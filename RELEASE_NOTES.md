# Release Notes

## Bundle 1.0.0 candidate

This source candidate contains `writing-plans` 4.0.0 and `software-quality-workflows` 5.0.0 as the indivisible `frontier-engineering/5.0.0+4.0.0` pair. `frontier-engineering.bundle.json` is generated from both skill roots and binds their policy registries, reference-card manifests, and the canonical plan-execution handoff schema. A missing skill, an independent skill-version override, or any bound hash drift rejects the bundle check.

This is not an activated or signed release. The checked-in activation level remains `shadow`; live autonomous closure, multi-candidate execution, and remote writes remain disabled.

Release/canary promotion is blocked until all of the following exist:

- a successful schema-valid P4 live Codex output canary;
- a real P5 paired cohort meeting the 50/50/30/20 minimums and all quality/safety gates;
- a clean signed source revision with explicit release approval.

The checked-in deterministic replay passes 25 curated aligned routes with exact-primary accuracy 100%, M0 median/p95 active reference bytes 3,404/4,044, zero unnecessary loads, and an 88.2% median reference-byte reduction versus the frozen v4/v3 routes. This is route-fixture evidence only: hidden routing, natural model behavior, paired outcome quality, and canary safety remain unrun, so it does not raise the activation ceiling.

The local thin-plugin staging and isolated Codex install/remove smoke are readiness evidence only. They do not satisfy those promotion gates.

## Breaking vNext graph and state changes

The flat owner registry, transitive reference closure, broad reference monoliths, compatibility route/state suites, and online migration readers were removed. Policy IDs now have one owner in each skill's generated policy registry. Model-facing guidance is addressed by exact card ID/path/hash through a generated card manifest, with one primary card and at most one next card per decision boundary.

Workflow and plan state use the vNext schema epoch only. In-flight runs remain pinned to their old complete bundle; they must finish there or be migrated offline before a fresh vNext run is created. New runs never dual-read old and new state. The completed one-shot migration utilities were deliberately deleted from the release source so an installed skill cannot silently reinterpret old state.

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

No redirect or permanent compatibility stub is provided. Callers must use the vNext card IDs, generated manifests, and current state schemas.

## Rollback boundary

Because activation remains shadow, rollback means retaining the current Direct/standard path and discarding non-release staging artifacts. Any pilot installs and rolls back both skills atomically; restoring only one skill is forbidden. Old in-flight artifacts stay with their old bundle and are never opened by the vNext runtime. There is no automatic merge, release, deploy, credential rotation, or production rollback in this bundle.
