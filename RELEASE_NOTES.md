# Release Notes

## Bundle 1.0.0 candidate

This source candidate contains `writing-plans` 3.0.0 and `software-quality-workflows` 4.0.0. It is not an activated or signed release. The checked-in activation level remains `shadow`; live autonomous closure, multi-candidate execution, and remote writes remain disabled.

Release/canary promotion is blocked until all of the following exist:

- a successful schema-valid P4 live Codex output canary;
- a real P5 paired cohort meeting the 50/50/30/20 minimums and all quality/safety gates;
- a clean signed source revision with explicit release approval.

The local thin-plugin staging and isolated Codex install/remove smoke are readiness evidence only. They do not satisfy those promotion gates.

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

No redirect or permanent compatibility stub is provided. Callers must use the active 3.0 reference map and stable IDs.

## One-shot state migrations

Both migration tools read a 1.0 source and create new 1.1 state/report files with no-overwrite behavior. They do not rewrite the original source:

```bash
python3 writing-plans/scripts/migrate_plan_state.py \
  <plan-state-1.0.json> \
  --output <plan-state-1.1.json> \
  --report <plan-migration-report.json> \
  --policy-bundle-hash <sha256-hash>

python3 software-quality-workflows/scripts/migrate_workflow_state.py \
  <workflow-state-1.0.json> \
  --output <workflow-state-1.1.json> \
  --report <workflow-migration-report.json> \
  --policy-bundle-hash <sha256-hash>
```

Plan-state migration defaults to `execution_policy=standard` and never invents a Closure Contract. Workflow-state migration is standard-only and never infers autonomous closure from historical nodes.

## Rollback boundary

Because activation remains shadow, rollback means retaining the current Direct/standard path and discarding non-release staging artifacts. Migration rollback is deletion of the newly generated 1.1 output/report while preserving the untouched 1.0 input. There is no automatic merge, release, deploy, credential rotation, or production rollback in this bundle.
