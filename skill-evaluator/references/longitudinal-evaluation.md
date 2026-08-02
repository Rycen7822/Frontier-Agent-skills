# Longitudinal Evaluation

Use this owner only when the claim compares immutable Skill versions or evaluation cycles. It closes a frozen revision hypothesis or classifies a model transition from existing cycle capsules; it does not generate candidates, schedule runs, orchestrate a Skill library, or promote a release.

## L4 claim ceiling

L4 is limited to controlled revision and model-transition evidence. Without verified selection, order, and composition receipts, the evaluator must not claim library-scale multi-Skill orchestration evidence.

L4 may establish only what its frozen version/cycle matrix supports: change in task benefit, protected outcomes, routing, safety, Target-Skill context, total cost, and declared slices under controlled identities.

## Offline comparison owner

`compare_cycles.py` consumes a self-hashed `comparison-plan v1` and two or three immutable cycle capsules. A `revision` plan binds one failure class, one change set, a prior and candidate, target closure, margins, protected metrics, and gates; its only terminal states are `closed`, `open`, and `not_evaluable`.

First emit observations while analyzing every bound cycle, then run the comparator with the frozen plan:

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/analyze_runs.py" artifacts/index.jsonl \
  --spec eval-spec.ready.json --json summary.json --failure-index failures.json \
  --comparison-observations comparison-observations.json
python3 "$SKILL_EVALUATOR_DIR/scripts/compare_cycles.py" comparison-plan.json
```

The comparator accepts only `revision` or `model_transition` and writes one canonical report/index transaction. It makes no provider, network, candidate-generation, installation, or publication call.

A `model_transition` plan freezes one mode:

- `direct`: A and C differ only in registered model/tokenizer identity;
- `bridge`: A→B isolates registered apparatus or judge change, then B→C isolates the model;
- `combined`: A→C changes model and apparatus and can report only joint drift.

Each transition binds absolute comparison observations, gain/stage retention, tokenizer and judge policy, protected gates, and distinct-case support. The closed classification is diagnostic evidence, not permission to remove a Skill. Exploratory history remains authority-blocked; a mechanically eligible pre-registered result still requires the external decision owner.

## Freeze each cycle

Record these inputs before execution:

- cycle ID and timestamps;
- accepted prior and candidate package hashes;
- change reason and affected requirement IDs;
- spec, public scenarios, holdout manifest/payload, fixtures, graders, model/harness, and environment hashes;
- compiled plan/compiler, host manifest/probes, calibration/quality, declared treatments/modules, repeats, gates, context authority, manual-review contract, and rollback target;
- protected case IDs and protected requirement IDs.

Store a new cycle. Never overwrite prior evidence or compare metrics across changed contracts as though they were one experiment. When a material control changes, rerun the affected prior and candidate treatments in the new frozen contract.

## Comparable version matrix

Use the same spec v5, execution plan v1, run-index row v2, receipt v4, summary v4, and failure-index v1 runtime contract as L1–L3. Bind each cycle through `comparison-plan v1`; model transitions also require `comparison-observations v1`. For each compared version, bind candidate revision/source/plugin identity plus package, catalog, treatment, host, compiler, fixture, grader, calibration/quality, artifact, provenance, module/stage, routing, principal/handoff/action/state/fault, usage, context, and cleanup evidence.

The comparison is evaluable only when:

- version identities are immutable and distinct where the treatment changed;
- declared scenarios, repeats, run order, authority, and environment are comparable;
- receipt integrity and the required matrix are complete;
- the case-level inferential denominator is explicit;
- protected outcomes and required context gates are present;
- holdout custody and exposure rules are satisfied when holdout evidence is claimed.

Do not attribute an executor, tool, grader, fixture, or environment change to the Skill.

## Version and cycle record

Preserve one row per cycle:

| Field | Required meaning |
|---|---|
| Cycle/version/package hash | Immutable treatment identity |
| Change reason/requirement IDs | Scope of the candidate difference |
| Contract and environment hashes | Comparability boundary |
| Receipt integrity and matrix status | Whether evidence is usable |
| Distinct cases and run pairs | Inferential and descriptive denominators |
| Benefit interval and guardrails | Incremental contribution evidence |
| Protected-outcome failures | Missing, invalid, or failed protected behavior |
| Skill context and total cost | Attributed burden and end-to-end cost |
| Safety and holdout status | Declared risk/generalization evidence only |
| Five status axes | Applicability, feasibility, evidence, usefulness, and external-decision eligibility |
| Drift and rollback triggers | Required next evaluation action |

Keep development, regression, and holdout results separate. Do not pool models, domains, or environments unless the frozen analysis contract explicitly defines that aggregation.

## Protected behavior

Protected cases must cover the exact behavior the cycle may accidentally remove: safety/permission boundaries, required outcomes, routing exclusions, cleanup/termination, and stable interfaces that the Skill owns.

Count missing, duplicate, invalid, and failed protected keys as failures. A favorable aggregate cannot cancel a protected-outcome failure. Changing the protected set is a contract revision and invalidates direct comparison until affected versions are rerun.

## Context and package drift

For every version, report package bytes, verified loaded component bytes, captured tokens when present, attribution coverage, frozen context-gate results, and end-to-end usage. Do not infer tokens from bytes or compare attributed context with paired-total-only data as though they were the same measure.

Re-audit package inventory, links, scripts, and security surfaces when their bytes change. A shorter package is not automatically a more useful Skill.

## Drift triggers

Open a new cycle when the Skill package, model/harness, relevant tool/API, fixture/grader, environment, neighboring catalog identity, authority policy, or exposed holdout state changes materially. The new cycle records which comparisons remain valid and which require rerun.

Cross-model, cross-host, cross-domain, and cross-environment evidence is required only when portability is part of the claim. Report each host/module axis separately; one host's pass cannot compensate for another host's required failure. Retain a fixed reference executor where practical for attribution.

## Monitoring and rollback

After an external owner accepts a version, retain:

- the accepted immutable package and decision evidence;
- the prior rollback package and restoration procedure;
- monitored failure classes and incident thresholds;
- environment/dependency drift triggers;
- the smallest sentinel scenario set that detects protected regressions;
- the condition that requires quarantine, rollback, or a new full cycle.

The evaluator reports these triggers and subsequent evidence. The external release authority owns deployment, promotion, rollback execution, and candidate creation.
