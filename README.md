# Frontier Agent Skills

This repository is the development source for the `frontier-engineering/11.2.0` bundle. One `frontier-engineering-plugin` contains ten skills for Codex and Hermes Agent, and the same repository carries a Qoder plugin shell at [`.qoder-plugin/plugin.json`](.qoder-plugin/plugin.json) so a checkout is directly installable in Qoder. Installed copies are separate from source; local edits take effect after rebuilding and reinstalling.

Bundle 11.2.0 adds the Qoder plugin shell and keeps every skill unchanged: the ten skill versions, the activation matrix and the compatible schema epoch 9 stay as they were in 11.1.0, which published `code-simplifier` 1.2.0 with conditional structural-simplification and validation references. See [the Qoder host note](docs/qoder-plugin.md) and [the component maintenance note](docs/code-simplifier-1.2.0.md).

## Skill entrypoints

| Skill | Use for | Version |
|---|---|---|
| [software-quality-workflows](software-quality-workflows/SKILL.md) | Feature implementation, known-cause fixes, testing and general development | 13.0.0 |
| [codebase-investigation](codebase-investigation/SKILL.md) | Explain implementation, design history or previous project work | 1.1.0 |
| [software-design](software-design/SKILL.md) | Resolve requirements, ownership, API, data-model or migration choices | 1.1.0 |
| [debugging](debugging/SKILL.md) | Diagnose failures, regressions and performance problems without an established cause | 1.1.0 |
| [code-review](code-review/SKILL.md) | Assess changes, scoped snapshots, review comments and evidence records | 2.0.2 |
| [code-simplifier](code-simplifier/SKILL.md) | Simplify selected code while preserving intended behavior | 1.2.0 |
| [runtime-verification](runtime-verification/SKILL.md) | Establish missing evidence through actual runtime or installed behavior | 1.1.0 |
| [writing-plans](writing-plans/SKILL.md) | Plan implementation after design and diagnosis are settled | 9.1.0 |
| [long-document-segmented-writing](long-document-segmented-writing/SKILL.md) | Produce long, source-grounded documents with recoverable state | 3.1.0 |
| [skill-evaluator](skill-evaluator/SKILL.md) | Assess skill effectiveness and selected historical trajectories | 5.0.1 |

SQW retains concise guidance throughout development. Specialized skills can be selected directly and do not require loading SQW first. No mandatory pipeline, model assignment, delegation or external plugin is needed. References provide conditional detail within each task.

## Release identity

Bundle 11.2.0 uses schema epoch 9. `software-quality-workflows` and `skill-evaluator` are explicit-only; the other eight skills remain eligible for implicit local selection. Invocation prompts retain `$skill-name`; eligibility does not guarantee model selection. The activation ceiling is `implicit_local_pilot` and `remote_writes` remains false.

The code-review skill ships a bounded review helper: `scripts/review_support.py` captures one review scope into a packet (`scope`) or checks a machine-readable record against that packet (`check`). It requires POSIX, Python 3.11 or later, Git 2.41 or later, and the `jsonschema` package in the environment that runs it; installing the plugin does not install Python packages. A packet or record is optional for ordinary reviews. See [the v11 migration note](docs/fas-v11-migration.md).

The bundle ships as one unit. Existing visual design tools belong to their respective task skills. Adopted source terms travel with the skills: pstack guidance is MIT; adapted Anthropic code-simplifier guidance is Apache-2.0. There is no separate simplifier plugin dependency.

## Evidence and digest policy

Evidence remains readable and source-bound: a digest establishes byte equality across a real ownership, process, retention, package, or external-data boundary; semantic payload, coverage, producer, command/status, oracle authority, freshness, limitations, and raw-evidence references establish meaning. Direct same-context work stays model-native. Cross-context work keeps one durable frontier and one canonical copy of non-replayable evidence. Machine integrity uses one digest per independently consumed byte object at its real boundary, while readable names carry semantic identity.

Every retained digest has one producer, one named validating consumer, a bounded mismatch action, the same lifecycle as its bytes, and machine-only visibility by default. Missing readable evidence fails a claim even when a digest matches; missing a required external/raw binding fails byte-integrity even when the prose is readable.

## Verification boundary

Ordinary maintenance does not require model reevaluation. Non-behavioral documentation, version/hash updates, and editorial changes judged to preserve meaning use zero model calls; a historical report is not a prerequisite. Run `python3 skill-evaluator/scripts/evaluate.py check --base <revision> --impact editorial` for an explicit maintenance judgment, or use `--impact auto` to identify changes needing closer scoping. This command only performs local checks. Changes to behavior, routing, execution conditions, or grading require evidence only for the affected scope; Git identity and elapsed time alone do not invalidate model results.

Bundle 11.2.0 uses model-free repository tests, generated identities, source validation and plugin smoke for engineering verification. Building and publishing packages do not require a model qualification or an authorization JSON file. Public effects follow the user's authorization; claims of model effectiveness need their own relevant evidence.

## Source archives

The source archive uses root `frontier-engineering-bundle`; the skills-only archive contains the ten canonical skill roots. Build both layouts with `scripts/build_source_archive.py` into a new temporary output directory, verify reproducible bytes and schema-valid evidence, and inspect the member list before publication. The builder excludes `.work`, worktrees, caches, local paths, credentials, and historical run artifacts; it does not publish the archive.

Ordinary change verification follows this table. Plugin staging remains a local packaging check and does not require a new model qualification.

| Change | Default work |
|---|---|
| README, version, generated identity, or editorial change judged to preserve meaning | Zero task/judge/calibration calls; only relevant local checks |
| One changed mechanism | Reuse compatible controls; execute only selected affected candidates |
| Deterministic check or model rubric | Reuse task observations; run only affected grading, with no automatic calibration |
| Fixture, effective model/effort, runtime, or routing catalog | Invalidate the affected dependency; preserve unrelated evidence |
| Controlled behavior comparison | Use selected paired cases and report the diagnostic scope; release authority is separate |

`python3 skill-evaluator/scripts/evaluate.py run --suite author-suite.json --host host.json --output run --previous-report previous/summary.json --case case-basic --task-attempt-budget 1 --judge-invocation-budget 0` demonstrates a scoped update with a reusable control. The [maintenance guide](skill-evaluator/references/maintenance.md) explains compact inputs and failure recovery. A task attempt is not an API request; cost reports separate task, judge, cache usage, and unknown billing.

## Plugin packaging

The plugin identity is `frontier-engineering-plugin` version 11.2.0 with display name `Frontier Engineering`. Its release layout is:

```text
frontier-engineering-plugin/
  .codex-plugin/plugin.json
  skills/
    code-review/
    code-simplifier/
    codebase-investigation/
    debugging/
    runtime-verification/
    software-design/
    long-document-segmented-writing/
    skill-evaluator/
    software-quality-workflows/
    writing-plans/
```

Use `scripts/build_codex_plugin.py` to create a new staging tree and build evidence, then validate the staged tree and run `scripts/smoke_codex_plugin.py`. These commands copy the ten complete skill directories into a local staging output and preserve external deployment state.

To produce an installable marketplace and deterministic ZIP, supply `--marketplace-root` and `--marketplace-archive-output` together. Use `--output <marketplace-root>/plugins/frontier-engineering-plugin`; keep evidence and the ZIP outside the marketplace. The archive contains `.agents/plugins/marketplace.json` and `plugins/frontier-engineering-plugin/` at its root and is verified against the packaged bytes. Output paths are never overwritten.

```bash
python3 bundle/build_bundle_manifest.py --check
python3 scripts/build_codex_plugin.py \
  --output /tmp/fas-build/marketplace/plugins/frontier-engineering-plugin \
  --evidence-output /tmp/fas-build/build.json \
  --marketplace-root /tmp/fas-build/marketplace \
  --marketplace-archive-output /tmp/fas-build/marketplace.zip
python3 scripts/smoke_codex_plugin.py \
  --plugin-root /tmp/fas-build/marketplace/plugins/frontier-engineering-plugin \
  --build-evidence /tmp/fas-build/build.json \
  --output /tmp/fas-build/static-smoke.json
```

Use a fresh task-owned output directory for each build. `scripts/smoke_codex_cli_install.py` checks installation and removal in an isolated Codex home without model calls; pass the plugin, build evidence, static smoke, marketplace, an existing work directory and an output file. These checks establish package and loader behavior, not measured skill effectiveness.

### Qoder shell

The repository itself is a Qoder plugin. `.qoder-plugin/plugin.json` declares the plugin name `frontier-engineering`, the bundle version and the ten skill directories, which sit at the repository top level rather than inside a single `skills/` directory. `scripts/build_qoder_plugin.py` renders that manifest from `bundle-manifest.json` and refuses a missing, renamed, unsorted or undescribed skill; `--check` fails when the committed manifest is stale. The shell adds no hooks, MCP servers, commands, agents, binaries, output styles, workflows, settings or dependency.

```bash
python3 scripts/build_qoder_plugin.py --check
qoder plugins validate "$PWD"
qoder plugins install "$PWD"
```

The Codex plugin package keeps its own `.codex-plugin/plugin.json` and never contains the Qoder shell. See [the Qoder host note](docs/qoder-plugin.md).

## Same-thread Codex skill reload supervisor

This optional developer tool sits outside the Bundle 11.2.0 source-complete and release path. `scripts/codex_skill_reload_supervisor.py` keeps one exact Codex thread across local plugin reinstall cycles through a local Unix-socket app-server and launches each replacement TUI with `danger-full-access` plus approval policy `never`; use it only where that permission boundary is intentional.

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

The [Skill Evaluator entrypoint](skill-evaluator/SKILL.md) uses one compact suite, independent task and grade results, and a small maintenance report. Exact reuse does not compile or prepare a run. Bundle source-completeness uses deterministic local gates; maintenance scores never grant release authority.

Rollback uses an ordinary revert to a selected signed predecessor. Installed rollback uses a separately verified predecessor plugin or archive under the same deployment authority boundary.
