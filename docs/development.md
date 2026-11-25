# Build, test and release FAS

This guide covers repository maintenance. New users should start with [the README](../README.md) and [host installation](hosts.md).

The current source identity is `frontier-engineering/11.7.0` with schema epoch 9. The activation ceiling is `implicit_local_pilot`, and `remote_writes` is `false`. Source preparation and release publication are separate operations. See [release notes](../RELEASE_NOTES.md) for source history and [the published 11.3.0 release](https://github.com/Rycen7822/Frontier-Agent-skills/releases/tag/frontier-engineering-v11.3.0) for released artifacts.

## Source and generated files

`bundle-manifest.json` is the canonical skill and test-profile manifest. `package.json` provides Pi's native discovery of `skills/*/SKILL.md`. The following files are generated and must match their builders:

- `frontier-engineering.bundle.json`
- `.qoder-plugin/plugin.json`

`.zcode-plugin/plugin.json` and `marketplace.json` are ZCode's plugin and marketplace manifests. They carry the bundle version and the sixteen canonical skill directories and are edited by hand; `tests/test_zcode_plugin.py` fails when they drift from `bundle-manifest.json`.

Check the generated identities and static contracts from the repository root:

```sh
python3 bundle/build_bundle_manifest.py --check
python3 scripts/build_qoder_plugin.py --check
python3 scripts/evaluate_static_contracts.py --check
```

Run the applicable commands in the `quick`, `extended` and `release` arrays in `bundle-manifest.json`. Select the smallest relevant profile for ordinary changes. Broaden verification for failures, cross-cutting effects or material uncertainty. Plugin staging is a local packaging check and does not require model qualification. Building and publishing packages require neither model qualification nor an authorization JSON file. Public effects still follow the user's authorization.

## Build a Codex marketplace

The plugin identity is `frontier-engineering-plugin` version 11.7.0 with display name `Frontier Engineering`. Its layout is:

```text
frontier-engineering-plugin/
  .codex-plugin/plugin.json
  skills/
    clean-code-comments/
    code-review/
    code-simplifier/
    codebase-improve/
    codebase-investigation/
    debugging/
    improve-docs/
    long-document-segmented-writing/
    reframe/
    runtime-verification/
    sharpen/
    skill-evaluator/
    software-design/
    software-quality-workflows/
    test-behavior/
    writing-plans/
```

Use a new task-owned output directory for each build. Output paths are never overwritten. Keep evidence and the ZIP outside the marketplace:

```sh
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

The builder copies all sixteen complete skill directories and preserves external deployment state. The archive contains `.agents/plugins/marketplace.json` and `plugins/frontier-engineering-plugin/` at its root. Its bytes are verified against the staged package.

The Hermes command files inside Clean Code Comments, Codebase Improve, Improve Docs, Reframe and Sharpen are inert resources in Codex and Pi. Only Hermes plugin registration exposes their slash commands. The Codex package keeps its own `.codex-plugin/plugin.json` and never contains the Qoder shell.

`scripts/smoke_codex_cli_install.py` checks installation and removal in an isolated Codex home without model calls. Pass the plugin, build evidence, static smoke, marketplace, an existing work directory and an output file. These checks establish package and loader behavior, not measured skill effectiveness.

## Build source archives

The bundle archive mirrors the source tree under `frontier-engineering-bundle/`, including `skills/<name>/`. The skills-only archive still places each of the sixteen skill directories directly at its root. Build both layouts into new output paths:

```sh
python3 scripts/build_source_archive.py \
  --source-root "$PWD" \
  --output /tmp/fas-build/bundle.zip \
  --evidence-output /tmp/fas-build/bundle.json \
  --layout bundle
python3 scripts/build_source_archive.py \
  --source-root "$PWD" \
  --output /tmp/fas-build/skills.zip \
  --evidence-output /tmp/fas-build/skills.json \
  --layout skills_only
```

Verify reproducible bytes, schema-valid evidence and the member list before publication. The builder excludes `.work`, `references`, worktrees, caches, local paths, credentials and historical run artifacts. It does not publish the archive.

## Review helper requirements

The code-review helper `skills/code-review/scripts/review_support.py` captures one review scope into a packet with `scope` or checks a machine-readable record against that packet with `check`. It requires POSIX, Python 3.11 or later, Git 2.41 or later and the `jsonschema` package in the environment that runs it. Installing the plugin does not install Python packages. A packet or record is optional for ordinary reviews. See [the v11 migration note](fas-v11-migration.md).

## Evidence and digest policy

Evidence remains readable and source-bound. A digest establishes byte equality across a real ownership, process, retention, package or external-data boundary. Semantic payload, coverage, producer, command status, oracle authority, freshness, limitations and raw-evidence references establish meaning.

Direct same-context work stays model-native. Cross-context work keeps one durable frontier and one canonical copy of non-replayable evidence. Machine integrity uses one digest per independently consumed byte object at its real boundary. Readable names carry semantic identity.

Every retained digest has one producer, one named validating consumer, a bounded mismatch action and the same lifecycle as its bytes. It is machine-only by default. Missing readable evidence fails a claim even when a digest matches. Missing a required external or raw binding fails byte integrity even when the prose is readable.

## Verification and evaluation boundary

Ordinary maintenance does not require model reevaluation. Non-behavioral documentation, version and hash updates, and editorial changes judged to preserve meaning use zero model calls. A historical report is not a prerequisite.

Run `python3 skills/skill-evaluator/scripts/evaluate.py check --base <revision> --impact editorial` for an explicit maintenance judgment. Use `--impact auto` to identify changes needing closer scoping. This command performs local checks only.

Changes to behavior, routing, execution conditions or grading require evidence only for the affected scope. Git identity and elapsed time alone do not invalidate model results.

| Change | Default work |
|---|---|
| README, version, generated identity or meaning-preserving editorial change | Use zero task, judge or calibration calls. Run relevant local checks. |
| One changed mechanism | Reuse compatible controls. Execute only selected affected candidates. |
| Deterministic check or model rubric | Reuse task observations. Run only affected grading with no automatic calibration. |
| Fixture, effective model or effort, runtime, or routing catalog | Invalidate the affected dependency and preserve unrelated evidence. |
| Controlled behavior comparison | Use selected paired cases and report the diagnostic scope. Release authority is separate. |

The following command demonstrates a scoped update with a reusable control:

```sh
python3 skills/skill-evaluator/scripts/evaluate.py run --suite author-suite.json --host host.json --output run --previous-report previous/summary.json --case case-basic --task-attempt-budget 1 --judge-invocation-budget 0
```

The [maintenance guide](../skills/skill-evaluator/references/maintenance.md) explains compact inputs and failure recovery. A task attempt is not an API request. Cost reports separate task, judge, cache usage and unknown billing.

The [Skill Evaluator entrypoint](../skills/skill-evaluator/SKILL.md) uses one compact suite, independent task and grade results, and a small maintenance report. Exact reuse does not compile or prepare a run. Bundle source completeness uses deterministic local gates. Maintenance scores never grant release authority. Public effects follow the user's authorization, and claims of model effectiveness need relevant evidence.

## Rollback and licensing

Roll back source with an ordinary revert to a selected signed predecessor. Roll back an installation with a separately verified predecessor plugin or archive under the same deployment authority boundary.

Adopted source terms travel with the skills. Pstack guidance is MIT licensed, and adapted Anthropic guidance is Apache-2.0 licensed. There is no separate simplifier plugin dependency. Existing visual design tools belong to their respective task skills.
