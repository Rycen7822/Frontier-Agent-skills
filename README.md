# Frontier Agent Skills

This repository is the development source of truth for the dual-host `writing-plans` 5.0.0 and `software-quality-workflows` 6.0.0 skills. Installed Codex or Hermes Agent copies are separate deployment directories; editing this repository never mutates an active installation.

## Release identity

The indivisible source pair is `frontier-engineering/6.0.0+5.0.0` in bundle version 2.0.0 and schema epoch 2. `bundle-manifest.json` contains exactly two cross-skill contracts: `plan-to-workflow` and `workflow-plan-change-proposal`.

The checked-in activation policy is exact and fail-closed:

```json
{
  "current_level": "shadow",
  "implicit_routing_default": false,
  "remote_writes": false
}
```

Both `agents/openai.yaml` files require explicit skill invocation. Packaging, archive, static smoke, or CLI installation success does not authorize model execution, a pilot, publication, deployment, or remote writes.

## Design boundary

The skills are optimized for frontier coding agents that already possess broad software-engineering knowledge. Compact entrypoints route to one decision card at a time; deterministic maps, manifests, schemas, and tests carry the contract instead of repeated tutorials.

- `writing-plans` owns intended design, planning profile, decision resolution, slicing, and durable handoff.
- `software-quality-workflows` owns work routing, execution safety, verification, review, and truthful completion classification.

Routine local work stays on the direct path. Material ambiguity, unknown causes, recovery, public contracts, migration, and other risk surfaces enter their explicit owners without expanding user authority.

## Deterministic validation

Run the standalone suites from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s writing-plans/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s software-quality-workflows/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Verify every generated identity before packaging:

```bash
PYTHONDONTWRITEBYTECODE=1 writing-plans/scripts/build_reference_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 software-quality-workflows/scripts/build_reference_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 bundle/build_bundle_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 scripts/evaluate_offline_route_replay.py --check
```

Extended long-document cases require `LONG_DOCUMENT_SKILL_ROOT=<installed-skill-root>`; without it, only those external-integration cases skip.

## Source archives

Use absent outputs under a task-owned evidence root. The builder is no-overwrite, rejects symlinks and source drift, normalizes ZIP bytes, and emits a content-bound evidence file.

```bash
scripts/build_source_archive.py \
  --source-root . \
  --layout bundle \
  --output <evidence-root>/frontier-engineering-bundle-2.0.0.zip \
  --evidence-output <evidence-root>/frontier-engineering-bundle-2.0.0.evidence.json

scripts/build_source_archive.py \
  --source-root . \
  --layout skills_only \
  --output <evidence-root>/frontier-engineering-skills-2.0.0.zip \
  --evidence-output <evidence-root>/frontier-engineering-skills-2.0.0.evidence.json
```

The bundle layout uses root `frontier-engineering-bundle`. The skills-only layout contains exactly the two skill roots.

## Isolated plugin staging

The plugin identity is `frontier-engineering-plugin` version 2.0.0 with display name `Frontier Engineering`. Build only into an absent task-owned marketplace destination:

```bash
scripts/build_codex_plugin.py \
  --source-root . \
  --output <marketplace-root>/plugins/frontier-engineering-plugin \
  --evidence-output <evidence-root>/plugin-build-evidence.json

scripts/smoke_codex_plugin.py \
  --plugin-root <marketplace-root>/plugins/frontier-engineering-plugin \
  --build-evidence <evidence-root>/plugin-build-evidence.json \
  --output <evidence-root>/static-plugin-smoke.json
```

The builder uses `<evidence-root>/plugin-build-staging` and atomically renames a validated tree to the absent destination on the same filesystem. A failed build leaves the staging directory intact and leaves the destination absent. Staging evidence records `activation_ceiling: shadow` and `release_evidence_hash: null`.

The isolated CLI smoke requires a task-owned marketplace created by the installed `plugin-creator`, with source `./plugins/frontier-engineering-plugin`, installation policy `AVAILABLE`, authentication policy `ON_INSTALL`, and category `Developer Tools`. The smoke rehomes all Codex configuration under its work root, strips credential-bearing environment variables, validates staged and installed bytes, removes the plugin and marketplace from the isolated configuration, and never invokes a model.

Release-mode plugin output additionally requires external `release-evidence/2.0` bound to a clean signed source revision, the deterministic replay, a scored L2 report, and an activation decision. No such evidence is stored in the candidate repository.

## Evaluation boundary

`evaluation/offline-route-replay.json` is a deterministic diagnostic, not an L2 usefulness result. Scored L2 specifications, fixtures, holdouts, receipts, and activation decisions belong only to revision-bound external run roots. See [evaluation/README.md](evaluation/README.md).
