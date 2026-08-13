# Model evolution campaign controller

This directory owns the bounded qualification campaign used when a Codex Host or model revision can change Frontier Engineering behavior. The controller coordinates the existing Skill Evaluator and records a readable campaign state, explicit budgets, durable evidence locations, and the final qualification.

## Artifact owners

- `schemas/campaign-v3.schema.json` defines campaign state and revision-based mutation.
- `schemas/interaction-probes-v2.schema.json` defines the bounded Host probe set.
- `schemas/sentinel-index-v2.schema.json` indexes the four Skill sentinel suites.
- `schemas/qualification-v3.schema.json` defines the decision-axis qualification projection.
- `residual-clauses/software-quality-workflows.json` binds each evolvable SQW H2 clause to its public cases; section bytes are computed from source when selecting one candidate clause.
- `codex-interaction-probes-v2.json` contains six model-independent Host probes.
- `sentinel-index-v2.json` binds the four generated public suites under `sentinels/`.
- `evaluation/fixtures/skill-evaluator/` is the single model-free compile-run-analyze fixture used by controller preflight and the public lifecycle test.
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
5. `prepare-current`, `prepare-candidate`, `prepare-prior`, and `prepare-holdout` materialize evaluator-owned plans from their declared inputs. The prior path validates Bundle 7 with its signed builder while retaining the current Host, compiler, fixtures, and graders as the apparatus identity.
6. `verify-plan` rebuilds a selected plan, while `register-plan` records its plan ID, content digest, Host identity, request ceiling, and initial runner counts.
7. `prepare-manual-review` binds an explicit decision and attestation to one registered holdout plan, then replays the analyzer's receipt contract; `record` joins analysis and comparison evidence by readable plan IDs and campaign roles.
8. `status` projects the next legal event and durable worker state; `qualify` publishes JSON and Markdown; `verify` reprojects that qualification in a fresh process.

Bundle 8.0 bootstrap keeps `candidate=null`, records one closed revision report per Skill against the signed 7.0 source, and admits the final plugin only after all four reports. Later SQW evolution registers at most one prebuilt candidate for one transition classification: native absorption selects the largest eligible clause, routing changes preserve the runtime body, and source candidates advance the owner Skill and Bundle by one minor before holdout freeze.

Every mutation uses `--expected-revision`. Long-running evaluation remains owned by `run_eval_plan.py` and its durable `systemd --user` worker. Raw receipts, Host streams, calibration records, and exposed holdout inputs remain available at their recorded locations.

## Development verification

Run the model-free source gates and the compact public lifecycle suite:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_model_evolution_sentinels.py --check
PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_static_contracts.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/test_extended_skill_evaluator.py \
  tests/test_extended_release.py -v
```

Model-evolution code is evaluation apparatus, so it does not own a second unit-test framework. A release campaign verifies it through the real preflight, one fake compile-run-analyze chain, registered profiles, archive inspection, and fresh-process plugin discovery.
