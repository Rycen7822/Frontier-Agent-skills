# Frontier Agent Skills

This repository is the development source of truth for the dual-host Frontier Engineering skill bundle: `brainstorming` 1.0.0, `long-document-segmented-writing` 1.0.0, `skill-evaluator` 1.0.0, `software-quality-workflows` 8.0.0, and `writing-plans` 7.0.0. Installed Codex or Hermes Agent copies are separate deployment directories; editing this repository never mutates an active installation.

## Release identity

The indivisible release unit is `frontier-engineering/4.0.0` in bundle version 4.0.0 and schema epoch 3. The generated identity binds all five exact skill versions and root hashes; only the two card-driven skills carry policy-registry and reference-card components. `bundle-manifest.json` still contains exactly two cross-skill contracts: `plan-to-workflow` and `workflow-plan-change-proposal`.

The checked-in activation policy is exact and fail-closed:

```json
{
  "current_level": "implicit_local_pilot",
  "implicit_routing_default": true,
  "remote_writes": false
}
```

All five `agents/openai.yaml` files permit implicit selection while retaining explicit `$skill-name` invocation. This activation authorizes local host routing only. Packaging, archive, static smoke, or CLI installation success does not satisfy the independent scored-L2, signed-source, release, publication, deployment, credential, or remote-write gates.

## Design boundary

The skills are optimized for frontier coding agents that already possess broad software-engineering knowledge. Compact entrypoints and explicit owner links keep optional resources unloaded until selected; deterministic maps, manifests, schemas, CLIs, and tests carry durable contracts instead of repeated tutorials.

- `brainstorming` owns proportionate design exploration and leaves its visual companion and delegated reviewer unloaded unless explicitly selected.
- `long-document-segmented-writing` owns compact/full long-corpus drafting, one scratch root, deterministic assembly, and final confidence repair.
- `skill-evaluator` owns L0–L4 evaluation claim ceilings, bounded audit triage, package tests, and evidence interpretation.
- `writing-plans` owns intended design, planning profile, decision resolution, slicing, and durable handoff.
- `software-quality-workflows` owns work routing, execution safety, verification, review, and truthful completion classification.

Routine local work stays on the direct path. Material ambiguity, unknown causes, recovery, public contracts, migration, and other risk surfaces enter their explicit owners without expanding user authority.

## Deterministic validation

Run the standalone suites from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s writing-plans/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s software-quality-workflows/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s long-document-segmented-writing/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Verify every generated identity before packaging:

```bash
PYTHONDONTWRITEBYTECODE=1 writing-plans/scripts/build_reference_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 software-quality-workflows/scripts/build_reference_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 bundle/build_bundle_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 scripts/evaluate_offline_route_replay.py --check
```

The long-document and evaluator suites use only repository-owned package roots. No installed-skill environment variable or parent-repository delivery script is part of deterministic validation.

## Source archives

Use absent outputs under a task-owned evidence root. The builder is no-overwrite, rejects symlinks and source drift, normalizes ZIP bytes, and emits a content-bound evidence file.

```bash
scripts/build_source_archive.py \
  --source-root . \
  --layout bundle \
  --output <evidence-root>/frontier-engineering-bundle-4.0.0.zip \
  --evidence-output <evidence-root>/frontier-engineering-bundle-4.0.0.evidence.json

scripts/build_source_archive.py \
  --source-root . \
  --layout skills_only \
  --output <evidence-root>/frontier-engineering-skills-4.0.0.zip \
  --evidence-output <evidence-root>/frontier-engineering-skills-4.0.0.evidence.json
```

The bundle layout uses root `frontier-engineering-bundle`. The skills-only layout contains exactly the five canonical skill roots.

## Isolated plugin staging

The plugin identity is `frontier-engineering-plugin` version 4.0.0 with display name `Frontier Engineering`. Build only into an absent task-owned marketplace destination:

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

The builder uses `<evidence-root>/plugin-build-staging` and atomically renames a validated tree to the absent destination on the same filesystem. A failed build leaves the staging directory intact and leaves the destination absent. Staging evidence records `activation_ceiling: implicit_local_pilot` and `release_evidence_hash: null`. The activation ceiling is identical for staging and release outputs; `output_class` plus the release-evidence hash alone determine release eligibility.

The isolated CLI smoke requires a task-owned marketplace created by the installed `plugin-creator`, with source `./plugins/frontier-engineering-plugin`, installation policy `AVAILABLE`, authentication policy `ON_INSTALL`, and category `Developer Tools`. The smoke rehomes all Codex configuration under its work root, strips credential-bearing environment variables, validates staged and installed bytes, removes the plugin and marketplace from the isolated configuration, and never invokes a model.

Release-mode plugin output additionally requires external `release-evidence/2.0` bound to a clean signed source revision, the deterministic replay, a scored L2 report, and an activation decision. No such evidence is stored in the candidate repository.

## Evaluation boundary

`evaluation/offline-route-replay.json` is a deterministic diagnostic, not an L2 usefulness result. Scored L2 specifications, fixtures, holdouts, receipts, and activation decisions belong only to revision-bound external run roots. See [evaluation/README.md](evaluation/README.md).

`skill-evaluator` uses schema v3 specifications, one receipt index, and hash-bound receipt artifacts. Analyzer exit 3 means evidence is incomplete, invalid, or inconclusive; it is not a successful usefulness result. Its public placeholders are not live evidence. Routine L0 audit emits a bounded zero-file triage summary, while complete JSON is reserved for a frozen evaluation or an external machine consumer.
