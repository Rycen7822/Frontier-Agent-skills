# Frontier Agent Skills

This repository is the development source of truth for the dual-host `writing-plans` and `software-quality-workflows` skills. Copies installed under `$CODEX_HOME/skills/` or `$HERMES_HOME/skills/` are separate deployment directories, not symlinks: editing this repository does not change an active Codex or Hermes Agent installation until an operator explicitly synchronizes the validated skill directories and starts a fresh host session.

## Design target

These skills are purpose-built for frontier-grade coding agents, especially `gpt-5.6-sol` at `max` reasoning effort and models with comparable planning, tool-use, and long-horizon execution capabilities. They assume the model already possesses broad software-engineering knowledge; the skills focus on the small set of high-leverage constraints, decision points, and verification contracts needed to complete complex development tasks reliably.

The design goal is maximum execution guidance with minimum context burden. Compact entrypoints route the model to progressively disclosed references and deterministic checks only when they are relevant, avoiding exhaustive tutorials and repeated generic advice while preserving enough structure for planning, implementation, recovery, and evidence-backed closure.

The repository also owns the deterministic validation, evaluation, archive, and non-release plugin-readiness tooling for the two-skill closure bundle. The archive root prefix remains `software-engineering-closure-bundle` for compatibility with the existing artifact schema; the Git repository name does not redefine that package contract.

## Closure bundle

Candidate changes, intentional compatibility removals, atomic old-run handling, and the current shadow blockers are recorded in [RELEASE_NOTES.md](RELEASE_NOTES.md). The release-generated [bundle identity](frontier-engineering.bundle.json) binds the exact SQW 5.0.0 + Writing Plans 4.0.0 pair; neither skill is independently overridable.

This bundle coordinates two independent skills without adding a third policy owner:

- `writing-plans` owns intended design, the frozen Closure Contract, and plan handoff.
- `software-quality-workflows` owns actual execution, verification, controller transitions, sign-off, and terminal certificates.

Routine low-risk work remains on the Direct path. Autonomous closure is an explicitly admitted M2/M3 execution policy and never expands user authority or publication rights.

## Validation

Run the three standalone profiles from this directory:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s writing-plans/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s software-quality-workflows/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Before packaging, verify generated navigation and release identities:

```bash
PYTHONDONTWRITEBYTECODE=1 writing-plans/scripts/build_reference_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 software-quality-workflows/scripts/build_reference_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 bundle/build_bundle_manifest.py --check
PYTHONDONTWRITEBYTECODE=1 scripts/evaluate_offline_route_replay.py --check
```

Extended long-document integration is optional. Set `LONG_DOCUMENT_SKILL_ROOT` to an installed skill root before running the same commands; without it, extended-only cases skip.

Build deterministic source archives from a clean allowlisted staging copy, never by recursively zipping the development directory:

```bash
scripts/build_source_archive.py \
  --source-root . \
  --layout bundle \
  --output ../software-engineering-closure-bundle.zip \
  --evidence-output ../software-engineering-closure-bundle.zip.evidence.json

scripts/build_source_archive.py \
  --source-root . \
  --layout skills_only \
  --output ../hermes-writing-plans-and-software-quality-workflows.zip \
  --evidence-output ../hermes-writing-plans-and-software-quality-workflows.zip.evidence.json
```

Both layouts normalize ZIP timestamps and modes, reject symlinks/source drift/no-overwrite conflicts, exclude generated cache/runtime paths, and emit a per-file hash inventory. `skills_only` contains exactly the two top-level skill directories. Archive evidence deliberately records `source_revision_verified=false`; a reproducible allowlisted snapshot is not a signed Git revision.

The plugin builder creates an isolated staging tree only. It does not install, activate, publish, merge, release, or deploy anything.

## Non-release plugin readiness smoke

Use an absent task-owned staging path; the builder and evidence outputs are no-overwrite. This sequence builds and statically checks the thin plugin without entering `dist/`:

```bash
scripts/build_codex_plugin.py \
  --source-root . \
  --output ../tmp/p6-staging/software-engineering-closure-plugin \
  --evidence-output ../tmp/p6-staging/build-evidence.json

scripts/smoke_codex_plugin.py \
  --plugin-root ../tmp/p6-staging/software-engineering-closure-plugin \
  --build-evidence ../tmp/p6-staging/build-evidence.json \
  --output ../tmp/p6-staging/static-smoke.json
```

For the optional real CLI install/remove smoke, start from an absent `../tmp/p6-cli-marketplace` and use the installed `plugin-creator` helper to create the required repo-local layout. Replace only the task-owned scaffold with the already hashed staging tree, then run the smoke:

```bash
MARKETPLACE_ROOT=../tmp/p6-cli-marketplace
python3 "$HOME/.codex/skills/.system/plugin-creator/scripts/create_basic_plugin.py" \
  software-engineering-closure-plugin \
  --path "$MARKETPLACE_ROOT/plugins" \
  --with-skills \
  --with-marketplace \
  --marketplace-path "$MARKETPLACE_ROOT/.agents/plugins/marketplace.json" \
  --marketplace-name closure-shadow-local \
  --install-policy AVAILABLE
rm -rf "$MARKETPLACE_ROOT/plugins/software-engineering-closure-plugin"
cp -a ../tmp/p6-staging/software-engineering-closure-plugin \
  "$MARKETPLACE_ROOT/plugins/software-engineering-closure-plugin"

scripts/smoke_codex_cli_install.py \
  --plugin-root "$MARKETPLACE_ROOT/plugins/software-engineering-closure-plugin" \
  --build-evidence ../tmp/p6-staging/build-evidence.json \
  --static-smoke ../tmp/p6-staging/static-smoke.json \
  --marketplace-root "$MARKETPLACE_ROOT" \
  --work-root ../tmp \
  --plugin-validator "$HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py" \
  --output ../tmp/p6-staging/codex-cli-smoke.json
```

The CLI smoke creates a temporary HOME/CODEX_HOME/XDG tree under `--work-root`, removes credential-bearing environment variables, performs local marketplace add/list/install/list/remove/list/marketplace-remove, verifies the installed cache byte-for-byte, and deletes the isolated HOME. It never calls `codex exec`, invokes a model, or writes remotely. The current report must mark explicit skill invocation and implicit routing as `not_run_gate_blocked`: P8 still lacks a successful live-output canary and real paired cohort, and this non-release staging build is not a verified clean signed revision. Successful installation is not release or canary evidence.

## Activation and evaluation

The checked-in activation level is `shadow`. Live autonomous closure, multi-candidate search, and remote writes are false in `bundle-manifest.json`. The deterministic offline replay and the retained paired-evaluation interface are documented in [evaluation/README.md](evaluation/README.md). Curated offline routing passes its bounded gates, but hidden routing and real Sol `max` outcomes are not run; the promotion report therefore remains `remain_shadow` because there is no live paired or historical cohort and the 50/50/30/20 minimums are not met.

A successful deterministic or synthetic evaluator test proves only that its gates work. It is not P8 effect evidence. Only a schema-valid real cohort bound to the current bundle/controller may authorize an explicit local pilot; implicit M0 and M2/M3 local-write canaries require their later independent gates. The builder must continue to reject `dist/` release output without separate passed release evidence.
