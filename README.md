# Frontier Agent Skills

This repository is the development source of truth for the dual-host `frontier-engineering/6.3.0` bundle. It contains exactly four skills: `long-document-segmented-writing` 1.1.0, `skill-evaluator` 3.3.3, `software-quality-workflows` 9.0.2, and `writing-plans` 8.2.4. Installed Codex or Hermes Agent copies are separate deployment directories; editing this repository never mutates an active installation.

## Release identity

The indivisible release unit is bundle version 6.3.0 at schema epoch 5. Its manifest records the four exact versions and mixed activation matrix:

```json
{
  "long-document-segmented-writing": true,
  "skill-evaluator": false,
  "software-quality-workflows": false,
  "writing-plans": false
}
```

`true` permits implicit local selection; `false` is explicit-only and its prompt retains the exact `$skill-name`. The bundle ceiling remains `implicit_local_pilot`, and `remote_writes` is false. Bundle 6.3.0 requires a signed, clean source candidate plus the repository's deterministic source, schema, bundle, plugin, archive, and test gates. Passing those local gates establishes source completeness only; it never grants installation, publication, deployment, or other external authority.

## Design boundary

The skills assume a capable coding agent and keep the common path compact. SQW loads optional references only for a concrete specialist risk; Writing Plans is self-contained.

- `software-quality-workflows` defaults to Direct execution for authorized, local, reversible same-session work. Direct creates no workflow protocol calls, JSON receipts, router/card state, or fallback ledger.
- `writing-plans` is explicit-only and compiles settled decisions into one source-bound Handoff or update-in-place Program Markdown. It binds the root once, states each fact once, batches compatible evidence checks, separates resume preflight from the first source-changing action, leaves same-session plans model-native, and returns unresolved facts to the caller or owning process.
- `long-document-segmented-writing` owns long-corpus drafting, bounded scratch state, deterministic assembly, and final confidence repair.
- `skill-evaluator` is explicit-only and owns L0–L4 evaluation claim ceilings, package audit, scored analysis, controlled revision closure, model-transition classification, and evidence interpretation.

SQW uses one fallback Markdown ledger only when the host and repository have no durable owner and one of five conditions exists: cross-context recovery, destructive or external effects, staged migration/release/rollout, multiple writers, or an explicitly requested recoverable audit trail. It never creates a second state projection.

Development is distinction-first: each behavior change needs an observable test, probe, smoke, property, benchmark, or runtime proof, but strict RED is not mandatory. Closeout classifies only tests added or materially changed in the current diff as `durable_contract`, `regression`, `risk_boundary`, `migration_temporary`, `temporary_probe`, `duplicate`, or `implementation_coupled`; temporary and duplicate protection is removed, while migration tests carry a deterministic removal contract.

## Verification boundary

Bundle 6.3.0 uses model-free repository tests, validators, canonical generated identities, and static smoke as local source-complete gates. Scored evaluator runs, graders, providers, and reviewer campaigns are not triggered by this release path. Deterministic local evidence can block a candidate but cannot authorize an external release. A canonical `release-authorization/1` binds the signed source, staged plugin, and static diagnostic to a human release-owner approval; it is identity authorization only, never scored usefulness evidence.

## Model evolution qualification

The tracked `evaluation/model-evolution/` corpus defines six inert Host probes and one non-ready sentinel suite for each Skill. The suites contain public scenarios, deterministic verifiers, suite-quality proof, and calibration gold contracts; they contain no live Host identity, provider output, ratings, or holdout payload. `scripts/build_model_evolution_sentinels.py --check` verifies all generated bindings without contacting a provider.

`scripts/model_evolution.py` owns one bounded external campaign. It freezes a signed source identity, project-wide budget, observed Host, existing Skill Evaluator plans and reports, at most one allowlisted candidate, and a deterministic qualification. A campaign-scoped non-blocking operation lock gives the probe stage one process owner; read-only status reports that owner and emits the sole canonical `systemd-run --user` command for an exact current budget approval. The controller never implements grading, optimization, worker supervision, reviewer selection, release authorization, installation, or publication. A model qualification and a separate `release-authorization/1` are both required for a model-support release claim; neither can substitute for the other.

## Source archives

The source archive uses root `frontier-engineering-bundle`; the skills-only archive contains exactly the four canonical skill roots. Build both layouts with `scripts/build_source_archive.py` into a new temporary output directory, verify reproducible bytes and schema-valid evidence, and inspect the member list before publication. The builder excludes `.work`, worktrees, caches, local paths, credentials, and historical run artifacts; it does not publish the archive.

## Plugin staging

The plugin identity is `frontier-engineering-plugin` version 6.3.0 with display name `Frontier Engineering`. Its release layout is:

```text
frontier-engineering-plugin/
  .codex-plugin/plugin.json
  skills/
    long-document-segmented-writing/
    skill-evaluator/
    software-quality-workflows/
    writing-plans/
```

Use `scripts/build_codex_plugin.py` to create a new staging tree and build evidence, then validate the staged tree and run `scripts/smoke_codex_plugin.py`. These commands copy the four complete skill directories and perform no global install, provider call, publication, or deployment.

A release build additionally requires a canonical `release-authorization/1` file created by `scripts/create_release_authorization.py` from the signed-clean source revision, the verified staged plugin, the deterministic static report, and a non-empty release-owner attestation. Staging builds reject this authorization; release builds require and identity-check it. Scored evaluation reports are not packaging authorization.

Release mode also requires `--marketplace-root` and `--marketplace-archive-output`. The deterministic ZIP has `.agents/plugins/marketplace.json` and `plugins/frontier-engineering-plugin/` at its root, preserves canonical file modes, and is verified against the same release plugin tree before publication. Staging mode rejects both marketplace outputs.

## Same-thread Codex skill reload supervisor

This optional developer tool is not used by the Bundle 6.3.0 source-complete or release path. `scripts/codex_skill_reload_supervisor.py` keeps one exact Codex thread across local plugin reinstall cycles. It never calls `fork`, never selects `--last`, never edits global Codex configuration, and never drives the TUI with synthesized keystrokes. It owns a local Unix-socket app-server and launches every TUI with `danger-full-access` plus approval policy `never`; use it only where that permission boundary is intentional.

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

The [Skill Evaluator entrypoint](skill-evaluator/SKILL.md) remains an explicit-only product for users who deliberately request structured Skill evaluation. Its runtime evaluator and model-evolution sentinels are not invoked by ordinary development or the Bundle 6.3.0 source-complete path. The offline comparator consumes only explicitly supplied immutable cycle capsules and makes no scored usefulness, installation, or deployment claim on behalf of this bundle.

For the Bundle 6.3 / Skill Evaluator 3.3 upgrade, source rollback restores bundle 6.2.0 / Skill Evaluator 3.2.0 semantics at signed commit `9687f6d0590a229c5e082b09ab548c397f27cad3` through an ordinary revert; do not use a destructive worktree reset. Installed rollback requires a separately verified bundle-6.2 staged plugin/archive and never implies publication or deployment authority.

Version 4 workflow/card/plan state is not read, migrated, aliased, or dual-written. Finish an active 4.x task under 4.x, or terminate it explicitly and restart from current repository truth.
