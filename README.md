# Frontier Agent Skills

This repository is the development source of truth for the dual-host `frontier-engineering/6.0.0` bundle. It contains exactly four skills: `long-document-segmented-writing` 1.0.0, `skill-evaluator` 3.0.0, `software-quality-workflows` 9.0.0, and `writing-plans` 8.1.0. Installed Codex or Hermes Agent copies are separate deployment directories; editing this repository never mutates an active installation.

## Release identity

The indivisible release unit is bundle version 6.0.0 at schema epoch 5. Its manifest records the four exact versions and mixed activation matrix:

```json
{
  "long-document-segmented-writing": true,
  "skill-evaluator": false,
  "software-quality-workflows": false,
  "writing-plans": false
}
```

`true` permits implicit local selection; `false` is explicit-only and its prompt retains the exact `$skill-name`. The bundle ceiling remains `implicit_local_pilot`, and `remote_writes` is false. Bundle 6.0.0 is accepted through direct human-readable source review and ordinary signed release operations; the repository's evaluator, hash, smoke, and benchmark tooling is not a release gate for this version.

## Design boundary

The skills assume a capable coding agent and keep the common path compact. SQW loads optional references only for a concrete specialist risk; Writing Plans is self-contained.

- `software-quality-workflows` defaults to Direct execution for authorized, local, reversible same-session work. Direct creates no workflow protocol calls, JSON receipts, router/card state, or fallback ledger.
- `writing-plans` is explicit-only and compiles settled decisions into one source-bound Handoff or update-in-place Program Markdown. It binds the root once, states each fact once, batches compatible evidence checks, separates resume preflight from the first source-changing action, leaves same-session plans model-native, and returns unresolved facts to the caller or owning process.
- `long-document-segmented-writing` owns long-corpus drafting, bounded scratch state, deterministic assembly, and final confidence repair.
- `skill-evaluator` is explicit-only and owns L0–L4 evaluation claim ceilings, package audit, scored analysis, and evidence interpretation.

SQW uses one fallback Markdown ledger only when the host and repository have no durable owner and one of five conditions exists: cross-context recovery, destructive or external effects, staged migration/release/rollout, multiple writers, or an explicitly requested recoverable audit trail. It never creates a second state projection.

Development is distinction-first: each behavior change needs an observable test, probe, smoke, property, benchmark, or runtime proof, but strict RED is not mandatory. Closeout classifies only tests added or materially changed in the current diff as `durable_contract`, `regression`, `risk_boundary`, `migration_temporary`, `temporary_probe`, `duplicate`, or `implementation_coupled`; temporary and duplicate protection is removed, while migration tests carry a deterministic removal contract.

## Verification boundary

Bundle 6.0.0 does not use repository tests, evaluator runs, graders, validators, generated identities, or hash chains as release evidence. Existing test and evaluator sources remain developer tools and product fixtures, but they do not authorize, block, or describe this release. The release record states only facts confirmed by direct reading and ordinary version-control operations.

## Source archives

The source archive uses root `frontier-engineering-bundle`; the skills-only archive contains exactly the four canonical skill roots. Assemble either archive with ordinary file copies and ZIP tooling, exclude `.work`, worktrees, caches, local paths, credentials, and historical run artifacts, then read the archive file list before publication. Do not invoke the historical evidence-producing archive builder for this release.

## Plugin staging

The plugin identity is `frontier-engineering-plugin` version 6.0.0 with display name `Frontier Engineering`. Its release layout is:

```text
frontier-engineering-plugin/
  .codex-plugin/plugin.json
  skills/
    long-document-segmented-writing/
    skill-evaluator/
    software-quality-workflows/
    writing-plans/
```

Create `plugin.json` from `packaging/codex-plugin/plugin.json.template` with version `6.0.0`, copy the four complete skill directories, and inspect the resulting tree directly. Do not call the historical plugin builder, smoke runner, release-evidence validator, or isolated-install harness for this release.

## Same-thread Codex skill reload supervisor

This optional developer tool is not used by the Bundle 6.0.0 manual completion or release path. `scripts/codex_skill_reload_supervisor.py` keeps one exact Codex thread across local plugin reinstall cycles. It never calls `fork`, never selects `--last`, never edits global Codex configuration, and never drives the TUI with synthesized keystrokes. It owns a local Unix-socket app-server and launches every TUI with `danger-full-access` plus approval policy `never`; use it only where that permission boundary is intentional.

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

The [Skill Evaluator entrypoint](skill-evaluator/SKILL.md) remains an explicit-only product for users who deliberately request structured Skill evaluation. Its schemas, scripts, examples, and historical `evaluation/` fixtures are not invoked by ordinary development and are not release evidence for Bundle 6.0.0. This release makes no scored usefulness, token-efficiency, longitudinal, installation, or deployment claim.

For the Skill Evaluator 3.0 upgrade, source rollback restores bundle 5.0.0 / Skill Evaluator 2.0.0 semantics at commit `d3824cfeb05ea8e37ec2c9013570b8405530bc89` through an ordinary revert or the frozen source archive; do not use a destructive worktree reset. Installed rollback uses only a verified bundle-5 staged plugin/archive through the isolated remove/install path and never implies publish or deploy authority.

Version 4 workflow/card/plan state is not read, migrated, aliased, or dual-written. Finish an active 4.x task under 4.x, or terminate it explicitly and restart from current repository truth.
