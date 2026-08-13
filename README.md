# Frontier Agent Skills

This repository is the development source of truth for the dual-host `frontier-engineering/8.0.0` bundle. It contains exactly four skills: `long-document-segmented-writing` 2.0.0, `skill-evaluator` 5.0.0, `software-quality-workflows` 11.0.0, and `writing-plans` 8.4.0. Installed Codex or Hermes Agent copies are separate deployment directories; editing this repository leaves active installations unchanged.

## Release identity

The indivisible release unit is bundle version 8.0.0 at schema epoch 7. Its manifest records the four exact versions and mixed activation matrix:

```json
{
  "long-document-segmented-writing": true,
  "skill-evaluator": false,
  "software-quality-workflows": false,
  "writing-plans": true
}
```

`true` permits implicit local selection; `false` is explicit-only and its prompt retains the exact `$skill-name`. The bundle ceiling remains `implicit_local_pilot`, and `remote_writes` is false. Bundle 8.0.0 requires a signed, clean source candidate plus the repository's deterministic source, schema, bundle, plugin, archive, and test gates. Those local gates establish source completeness; installation, publication, deployment, and external effects retain their own authority boundaries.

## Design boundary

The skills assume a capable coding agent and keep the common path compact. SQW loads optional references only for a concrete specialist risk; Writing Plans is self-contained.

- `software-quality-workflows` is explicit-only while current Host qualification treats its native overlap as a bounded limit. Once selected, it keeps known-seam work direct, escalates only to conclusion-changing evidence, classifies failure ownership before another edit, and separates implementation, verification, and release truth.
- `writing-plans` is implicit-eligible when the user requests a software implementation plan, Handoff, or multi-session Program. It compiles settled decisions into one source-bound Handoff or update-in-place Program Markdown, binds the root once, states each fact once, batches compatible evidence checks, separates resume preflight from the first source-changing action, leaves same-session plans model-native, and returns unresolved facts to the caller or owning process.
- `long-document-segmented-writing` owns long-corpus drafting, bounded scratch state, deterministic assembly, and final confidence repair.
- `skill-evaluator` is explicit-only and owns L0–L4 evaluation claim ceilings, package audit, scored analysis, controlled revision closure, model-transition classification, and evidence interpretation.

SQW creates durable state or a digest only for a cross-context consumer, external effect, staged release, or multiple writers. It prefers existing Host or repository state and otherwise uses one fallback ledger.

Development is distinction-first: each behavior change needs a deciding inspection, example, test, smoke, property, benchmark, or runtime proof, but strict RED is not mandatory. Stable contracts, regressions, and material risk boundaries remain; probes, duplicates, and retired-behavior tests are removed.

## Evidence and digest policy

Evidence remains readable and source-bound: a digest establishes byte equality across a real ownership, process, retention, package, or external-data boundary; semantic payload, coverage, producer, command/status, oracle authority, freshness, limitations, and raw-evidence references establish meaning. Direct same-context work stays model-native. Cross-context work keeps one durable frontier and one canonical copy of non-replayable evidence. Machine integrity uses one digest per independently consumed byte object at its real boundary, while readable names carry semantic identity.

Every retained digest has one producer, one named validating consumer, a bounded mismatch action, the same lifecycle as its bytes, and machine-only visibility by default. Missing readable evidence fails a claim even when a digest matches; missing a required external/raw binding fails byte-integrity even when the prose is readable.

## Verification boundary

Bundle 8.0.0 uses model-free repository tests, validators, canonical generated identities, live static checking, and plugin smoke as local source-complete gates. Scored usefulness remains a separate evaluator claim. A canonical `release-authorization/3` binds one current `model-qualification/3`, the signed source, staged plugin, live static-gate result, and release-owner attestation; external release still requires its own authority.

## Model evolution qualification

The tracked `evaluation/model-evolution/` corpus defines six inert Host probes and one non-ready sentinel suite for each Skill. The suites contain public scenarios, deterministic verifiers, suite-quality proof, and calibration gold contracts; they contain no live Host identity, provider output, ratings, or holdout payload. `scripts/build_model_evolution_sentinels.py --check` verifies all generated bindings without contacting a provider.

`scripts/model_evolution.py` owns one bounded external campaign. It binds a signed source identity, project-wide budget, observed Host, existing Skill Evaluator plans and reports, at most one allowlisted candidate, and a deterministic qualification. A campaign-scoped non-blocking operation lock gives the probe stage one process owner; read-only status reports that owner and emits the canonical `systemd-run --user` command for an exact current budget approval. Model qualification establishes model support, while `release-authorization/3` binds that exact qualification to release identity and authority; both are required for a model-support release claim.

## Source archives

The source archive uses root `frontier-engineering-bundle`; the skills-only archive contains exactly the four canonical skill roots. Build both layouts with `scripts/build_source_archive.py` into a new temporary output directory, verify reproducible bytes and schema-valid evidence, and inspect the member list before publication. The builder excludes `.work`, worktrees, caches, local paths, credentials, and historical run artifacts; it does not publish the archive.

## Plugin staging

The plugin identity is `frontier-engineering-plugin` version 8.0.0 with display name `Frontier Engineering`. Its release layout is:

```text
frontier-engineering-plugin/
  .codex-plugin/plugin.json
  skills/
    long-document-segmented-writing/
    skill-evaluator/
    software-quality-workflows/
    writing-plans/
```

Use `scripts/build_codex_plugin.py` to create a new staging tree and build evidence, then validate the staged tree and run `scripts/smoke_codex_plugin.py`. These commands copy the four complete skill directories into a local staging output and preserve external deployment state.

A release build additionally requires the current `model-qualification/3` and a canonical `release-authorization/3` created by `scripts/create_release_authorization.py` from that qualification, the signed-clean source revision, verified staged plugin, live static gate, and release-owner attestation. Release mode validates the qualification's Host identity and validity interval and binds the authorization digest; staging mode remains a local source-completeness build.

Release mode also requires `--marketplace-root` and `--marketplace-archive-output`. The deterministic ZIP has `.agents/plugins/marketplace.json` and `plugins/frontier-engineering-plugin/` at its root, preserves canonical file modes, and is verified against the same release plugin tree before publication. Staging mode rejects both marketplace outputs.

## Same-thread Codex skill reload supervisor

This optional developer tool sits outside the Bundle 8.0.0 source-complete and release path. `scripts/codex_skill_reload_supervisor.py` keeps one exact Codex thread across local plugin reinstall cycles through a local Unix-socket app-server and launches each replacement TUI with `danger-full-access` plus approval policy `never`; use it only where that permission boundary is intentional.

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

The [Skill Evaluator entrypoint](skill-evaluator/SKILL.md) remains an explicit-only product for structured Skill evaluation. Bundle 8.0.0 source-completeness uses deterministic local gates; scored runtime evaluation and model-evolution qualification remain explicit evaluator operations. The offline comparator consumes explicitly supplied immutable cycle capsules and reports only the comparison claim they support.

Rollback uses an ordinary revert to a selected signed predecessor. Installed rollback uses a separately verified predecessor plugin or archive under the same deployment authority boundary.
