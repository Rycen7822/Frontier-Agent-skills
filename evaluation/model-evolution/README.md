# Model evolution campaign controller

This directory owns the bounded qualification campaign used when a Codex Host or model revision can change Frontier Engineering behavior. The controller coordinates the existing Skill Evaluator and records a readable campaign state, explicit budgets, durable evidence locations, and the final qualification.

## Artifact owners

- `schemas/campaign-v3.schema.json` defines campaign state and revision-based mutation.
- `schemas/interaction-probes-v2.schema.json` defines the bounded Host probe set.
- `schemas/sentinel-index-v2.schema.json` indexes the four Skill sentinel suites.
- `schemas/qualification-v2.schema.json` defines the deterministic qualification projection.
- `codex-interaction-probes-v2.json` contains six model-independent Host probes.
- `sentinel-index-v2.json` binds the four generated public suites under `sentinels/`.
- `scripts/build_model_evolution_sentinels.py` is the tracked-artifact generator.
- `scripts/model_evolution.py` is the campaign command-line entry point.

Each binding follows its source owner:

- Repository artifacts use `{root, path}` and inherit the signed source revision.
- Campaign artifacts use `{root, path, schema_version}` and inherit campaign revision control.
- External or non-replayable evidence uses `{root, path, schema_version, digest}` so raw bytes remain independently verifiable.

## Lifecycle

1. `init` records the signed source, provisional Host, staged plugin, probes, sentinels, and project budget.
2. `preflight` closes the deterministic source, schema, bundle, plugin, and evaluator plumbing checks.
3. `probe` runs the approved Host observations and records their raw terminals.
4. `prepare-calibration` creates one bounded workspace per Skill; `record grader_calibration` binds each validated result.
5. `prepare-current`, `prepare-candidate`, and `prepare-holdout` materialize evaluator-owned plans from their declared inputs.
6. `verify-plan` rebuilds a selected plan, while `register-plan` records its plan ID, content digest, Host identity, request ceiling, and initial runner counts.
7. `record` joins analysis and comparison evidence by readable plan IDs and campaign roles.
8. `status` projects the next legal event and durable worker state; `qualify` publishes JSON and Markdown; `verify` reprojects that qualification in a fresh process.

Every mutation uses `--expected-revision`. Long-running evaluation remains owned by `run_eval_plan.py` and its durable `systemd --user` worker. Raw receipts, Host streams, calibration records, and exposed holdout inputs remain available at their recorded locations.

## Development verification

Run the focused local modules:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -m pytest \
  tests/test_model_evolution_documents.py \
  tests/test_model_evolution_state.py \
  tests/test_model_evolution_materialization.py \
  tests/test_model_evolution_host.py \
  tests/test_model_evolution_cli.py \
  tests/test_model_evolution_sentinels.py \
  tests/test_extended_model_calibration.py -q
```

The release verification then adds the registered Quick and Extended profiles, bundle and static checks, schema meta-validation, Ruff, archive inspection, and fresh-process plugin discovery.
