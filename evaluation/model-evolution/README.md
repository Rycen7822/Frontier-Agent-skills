# Model evolution campaign controller

This directory defines the bounded qualification campaign used when a new Codex Host or model revision may change the behavior of the Frontier Engineering plugin. The controller records identity, phase, budget, existing Skill Evaluator evidence, and the final qualification. It does not implement evaluation, grading, optimization, worker supervision, or release authorization.

## Owned artifacts

- `schemas/campaign-v2.schema.json` owns fresh-only campaign state and current-cycle budget accounting.
- `schemas/interaction-probes-v1.schema.json` owns the model-independent Host probe set contract.
- `schemas/sentinel-index-v1.schema.json` indexes the four Skill sentinel surfaces without copying evaluator specifications.
- `schemas/qualification-v1.schema.json` owns the deterministic qualification projection.
- `codex-interaction-probes-v1.json` freezes six inert, model-independent Host observations; unsupported direct evidence remains `unknown`.
- `sentinel-index-v1.json` binds the exact four non-ready public suites under `sentinels/`.
- Each Skill sentinel contains six public cases, minimal fixture/verifier inputs, deterministic suite-quality evidence, and calibration gold. Ratings and holdout payloads are external.
- `scripts/build_model_evolution_sentinels.py` is the only generator for those tracked artifacts.
- `scripts/model_evolution.py` is the only command-line entry point.
- `scripts/_model_evolution_campaign.py` owns campaign construction and optional exact-product predecessor binding.
- `scripts/_model_evolution_qualification.py` owns deterministic qualification and observed-Host projection.

Repository bindings contain a relative path and SHA-256 hash. Campaign bindings use the same shape but resolve below one campaign directory. Absolute paths, URIs, symlinks, path traversal, and hash drift fail closed. Optional predecessor evidence must remain inside the repository so the campaign can store a relative binding; it need not be Git-tracked.

## Lifecycle

The legal commands are:

1. `init` freezes a signed, tracked-clean source identity, the provisional Host, probe set, sentinel index, and project-wide ceilings.
2. `preflight` runs only local deterministic checks and the existing evaluator's fake compile/run/analyze chain.
3. `probe` spends the separately approved Host-probe budget and publishes the observed Host manifest.
4. `prepare-calibration` creates bounded per-Skill calibration inputs; `record grader_calibration` binds the four validated results.
5. `prepare-current` uses only frozen sentinel, Host, calibration, and staged-package evidence to atomically generate each current ready spec and plan.
6. `prepare-candidate` uses the one accepted candidate staging, all six owner cases, and one positive plus one protected case for every unaffected Skill. `prepare-holdout` accepts an exposed external three-file bundle containing exactly two independent scenarios per Skill. Both rebuild every derived field and invoke no provider.
7. `verify-plan` is read-only and rebuilds the selected current, candidate, or holdout directory from its raw authorities before comparing every file byte.
8. `register-plan` repeats the role-specific rebuild, requires zero attempts, reserves its worst-case requests, and renders the exact `systemd-run --user` command. It never starts the worker.
9. `record` binds existing analysis, comparison, revision, build, or holdout evidence. The one optional candidate is accepted only from a signed allowlisted Git diff after canonical focused gates pass.
10. `status` is read-only and renders the next legal event, runner status, blockers, and reserved/observed budget.
11. `qualify` atomically publishes deterministic JSON and Markdown without changing campaign revision.
12. `verify` reprojects the qualification in a fresh process without provider access.

Every mutation requires `--expected-revision`. A stale revision, held lock, failed operation, invalid binding, exceeded ceiling, or published qualification leaves `campaign.json` unchanged. A qualification directory makes the campaign immutable.

## Predecessor binding

An optional predecessor is supplied at `init` with a closed campaign, its observed Host, and an eligible model-transition comparison. An optional qualification may strengthen the exact product identity. The controller derives all stored hashes from those files.

Every campaign starts with zero reserved current-cycle counts; observed counts start at zero except `artifact_bytes`, which remains unknown until measured. A predecessor supplies comparison identity only; it never imports attempts, receipts, reservations, observed usage, or authorization from another campaign.

## Operational boundary

The controller calls the Skill Evaluator only through its public compiler, runner status, runner, analyzer, and comparison command surfaces. Fake preflight output proves apparatus plumbing only and never becomes model qualification evidence. Live evaluator attempts remain owned by `skill-evaluator/scripts/run_eval_plan.py`; durability remains owned by `systemd --user`.

The campaign never creates reviewers, optimizer loops, retry candidates, provider caches, or downloaded model assets. Reviewer, optimizer, and download ceilings are fixed at zero, and the candidate ceiling is at most one.

## Development verification

Run the focused zero-provider modules:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -m unittest \
  tests/test_extended_model_evolution_contract.py \
  tests/test_extended_model_evolution_lifecycle.py -v
```

Then run the canonical Quick profile, the registered Extended command containing these modules, Bundle `--check`, static-contract `--check`, Ruff, and schema meta-validation. These checks must not contact a provider, reviewer, optimizer, or download endpoint.
