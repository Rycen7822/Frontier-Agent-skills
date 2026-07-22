# Frontier Agent Skills

This repository is the development source of truth for the dual-host `frontier-engineering/5.0.0` bundle. It contains exactly four skills: `long-document-segmented-writing` 1.0.0, `skill-evaluator` 2.0.0, `software-quality-workflows` 9.0.0, and `writing-plans` 8.0.0. Installed Codex or Hermes Agent copies are separate deployment directories; editing this repository never mutates an active installation.

## Release identity

The indivisible release unit is bundle version 5.0.0 at schema epoch 4. The generated identity binds the four exact versions, root hashes, and mixed activation matrix:

```json
{
  "long-document-segmented-writing": true,
  "skill-evaluator": false,
  "software-quality-workflows": false,
  "writing-plans": false
}
```

`true` permits implicit local selection; `false` is explicit-only and its prompt retains the exact `$skill-name`. The bundle ceiling remains `implicit_local_pilot`, and `remote_writes` is false. Packaging, archive, static smoke, or CLI installation does not satisfy the independent scored-L2, longitudinal, signed-source, release, publication, deployment, credential, or remote-write gates.

## Design boundary

The skills assume a capable coding agent and keep the common path compact. Optional references load only for a concrete specialist risk.

- `software-quality-workflows` defaults to Direct execution for authorized, local, reversible same-session work. Direct creates no workflow protocol calls, JSON receipts, router/card state, or fallback ledger.
- `writing-plans` is explicit-only and compiles settled decisions into a Brief, one executable Handoff, or one resumable Program Markdown. Unresolved intent, cause, architecture, authority, or feasibility returns to SQW.
- `long-document-segmented-writing` owns long-corpus drafting, bounded scratch state, deterministic assembly, and final confidence repair.
- `skill-evaluator` is explicit-only and owns L0–L4 evaluation claim ceilings, package audit, scored analysis, and evidence interpretation.

SQW uses one fallback Markdown ledger only when the host and repository have no durable owner and one of five conditions exists: cross-context recovery, destructive or external effects, staged migration/release/rollout, multiple writers, or an explicitly requested recoverable audit trail. It never creates a second state projection.

Development is distinction-first: each behavior change needs an observable test, probe, smoke, property, benchmark, or runtime proof, but strict RED is not mandatory. Closeout classifies only tests added or materially changed in the current diff as `durable_contract`, `regression`, `risk_boundary`, `migration_temporary`, `temporary_probe`, `duplicate`, or `implementation_coupled`; temporary and duplicate protection is removed, while migration tests carry a deterministic removal contract.

## Deterministic validation

Run the three distinct profiles from the repository root. Quick is model-free and must remain under its cold-start budget:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s software-quality-workflows/tests -p 'test_quick_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s writing-plans/tests -p 'test_quick_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 long-document-segmented-writing/tests/test_workflow_contract.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_quick_*.py' -v
```

Extended owns runtime lifecycle, tampering, large fixtures, analyzer matrices, archive reproducibility, and plugin atomicity:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s software-quality-workflows/tests -p 'test_extended_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 long-document-segmented-writing/tests/test_assemble_markdown.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_extended_*.py' -v
```

Release runs only `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_release_cli_install.py -v` after all external paths and signed evidence are frozen. Verify generated identities with `python3 bundle/build_bundle_manifest.py --check` and `python3 scripts/evaluate_static_contracts.py --check`.

## Source archives

Use absent outputs under a task-owned evidence root. The builder is no-overwrite, rejects symlinks and source drift, normalizes ZIP bytes, and emits a content-bound evidence file.

```bash
scripts/build_source_archive.py \
  --source-root . \
  --layout bundle \
  --output <evidence-root>/frontier-engineering-bundle-5.0.0.zip \
  --evidence-output <evidence-root>/frontier-engineering-bundle-5.0.0.evidence.json

scripts/build_source_archive.py \
  --source-root . \
  --layout skills_only \
  --output <evidence-root>/frontier-engineering-skills-5.0.0.zip \
  --evidence-output <evidence-root>/frontier-engineering-skills-5.0.0.evidence.json
```

The bundle layout uses root `frontier-engineering-bundle`. The skills-only layout contains exactly the four canonical skill roots.

## Isolated plugin staging

The plugin identity is `frontier-engineering-plugin` version 5.0.0 with display name `Frontier Engineering`. Build only into an absent task-owned marketplace destination:

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

The builder uses `<evidence-root>/plugin-build-staging` and atomically renames a validated tree to the absent destination on the same filesystem. A failed build leaves the staging directory intact and the destination absent. Build evidence binds the exact mixed activation matrix. Staging records `release_evidence_hash: null`; only an explicit `--release-evidence` argument enables release-mode validation.

The isolated CLI smoke requires a task-owned marketplace created by the installed `plugin-creator`, with source `./plugins/frontier-engineering-plugin`, installation policy `AVAILABLE`, authentication policy `ON_INSTALL`, and category `Developer Tools`. The smoke rehomes all Codex configuration under its work root, strips credential-bearing environment variables, validates staged and installed bytes, removes the plugin and marketplace from the isolated configuration, and never invokes a model.

Release-mode output requires external `release-evidence/3.0` bound to a clean signed source revision, the tracked static diagnostic, both scored L2 reports and their aggregate, the longitudinal report, an unblocked activation decision, one candidate source identity, and the staged plugin tree hash. The builder recomputes every content and self-hash; no case, fixture, receipt, longitudinal run, or activation decision is stored in the candidate repository.

## Same-thread Codex skill reload supervisor

`scripts/codex_skill_reload_supervisor.py` keeps one exact Codex thread across local plugin reinstall cycles. It never calls `fork`, never selects `--last`, never edits global Codex configuration, and never drives the TUI with synthesized keystrokes. It owns a local Unix-socket app-server and launches every TUI with `danger-full-access` plus approval policy `never`; use it only where that permission boundary is intentional.

The protocol is fail-closed and pinned to `codex-cli 0.144.6`. Validate the CLI schema and local Unix WebSocket transport before the first run:

```bash
scripts/codex_skill_reload_supervisor.py validate --probe-cwd "$PWD"
```

Exit the previously unsupervised TUI once, then start the exact existing session from an ordinary shell. A session UUID is mandatory; names, pickers, `--last`, and forked sessions are rejected.

```bash
scripts/codex_skill_reload_supervisor.py run \
  --thread-id <exact-session-uuid> \
  --cwd "$PWD"
```

The supervisor injects `CODEX_SKILL_RELOAD_STATE` into app-server, the TUI, and agent shell commands. After the agent completes the normal local plugin build/reinstall and byte checks, its final shell step for that turn is:

```bash
scripts/codex_skill_reload_supervisor.py checkpoint \
  --plugin frontier-engineering-plugin@local-personal \
  --continue-skill frontier-engineering-plugin:software-quality-workflows
```

`checkpoint` resolves the exact enabled local plugin version, compares every source skill tree with the installed cache, and stores only their paths and hashes. `--continue-skill` selects the one to three verified skills attached to the automatic continuation turn; it does not weaken full-plugin verification. For one standalone `--skill NAME=/absolute/path/to/SKILL.md`, that sole skill is selected automatically.

Codex's `agent-turn-complete` notifier changes the pending checkpoint only after the current turn finishes. The supervisor then snapshots the persisted goal, closes the old TUI and app-server, starts a new app-server, resumes the exact thread with full access, forces a disk skill rescan, verifies the exact skill paths and tree hashes, and opens the replacement TUI. It sends the continuation turn through `turn/start` with an explicit skill input only after every proof passes.

A goal is set back to `active` only when it was `active` immediately before this reload boundary and is `paused` or `blocked` after resume. An intentionally paused, intentionally blocked, completed, usage-limited, or budget-limited goal is never activated and receives no automatic continuation turn. Initial adoption does not infer prior goal intent.

The runtime keeps one compact private JSON state file plus one transient Unix socket; it does not create per-turn receipts or history files. `status` prints a redacted summary:

```bash
scripts/codex_skill_reload_supervisor.py status
```

Any CLI version drift, schema drift, thread/cwd mismatch, permission mismatch, plugin/cache mismatch, skill error, hash drift, or non-resumable goal transition stops the cycle before an automatic turn. Update the pin and contract tests deliberately when Codex changes the experimental app-server protocol.

## Evaluation boundary

`evaluation/static-contract-diagnostic.json` proves only the checked source/package contract: exact paths, links, versions, activation, entry budgets, profile hashes, package size, and absence of retired runtime owners. It does not replay routing and cannot prove model behavior, usefulness, token efficiency, longitudinal test retention, release authority, or deployment readiness.

Scored L2 specifications, cases, fixtures, graders, run records, receipts, aggregate reports, longitudinal L4 artifacts, and activation decisions remain in a revision-bound external run root. Release evidence binds their hashes without copying them into the candidate. A smaller static package is not evidence of model usefulness or lower host tokens. See [evaluation/README.md](evaluation/README.md).

Version 4 workflow/card/plan state is not read, migrated, aliased, or dual-written. Finish an active 4.x task under 4.x, or terminate it explicitly and restart from current repository truth.
