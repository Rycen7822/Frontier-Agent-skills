# Longitudinal Evaluation

Use this owner only when the claim compares immutable Skill versions or evaluation cycles. It monitors evidence over time; it does not generate candidates, run revision workflows, schedule a Skill library, or promote a release.

## L4 claim ceiling

L4 is limited to version and cycle monitoring. Without verified selection, order, and composition receipts, the evaluator must not claim library-scale multi-Skill orchestration evidence.

L4 may establish only what its frozen version/cycle matrix supports: change in task benefit, protected outcomes, routing, safety, Target-Skill context, total cost, and declared slices under controlled identities.

## Freeze each cycle

Record these inputs before execution:

- cycle ID and timestamps;
- accepted prior and candidate package hashes;
- change reason and affected requirement IDs;
- spec, public cases, holdout manifest/payload, fixtures, graders, model/harness, and environment hashes;
- declared variants, repeats, gates, context authority, manual-review contract, and rollback target;
- protected case IDs and protected requirement IDs.

Store a new cycle. Never overwrite prior evidence or compare metrics across changed contracts as though they were one experiment. When a material control changes, rerun the affected prior and candidate variants in the new frozen contract.

## Comparable version matrix

Use the same receipt-index v1 and receipt v2 contract as L1–L3. For each compared version, bind candidate revision/source/plugin identity plus package, catalog, treatment, fixture set, grader set/schedule, artifact, provenance, routing, usage, and context evidence.

The comparison is evaluable only when:

- version identities are immutable and distinct where the treatment changed;
- declared cases, repeats, run order, authority, and environment are comparable;
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
| Usefulness/final-authority statuses | Analyzer signal and external decision eligibility |
| Drift and rollback triggers | Required next evaluation action |

Keep development, regression, and holdout results separate. Do not pool models, domains, or environments unless the frozen analysis contract explicitly defines that aggregation.

## Protected behavior

Protected cases must cover the exact behavior the cycle may accidentally remove: safety/permission boundaries, required outcomes, routing exclusions, cleanup/termination, and stable interfaces that the Skill owns.

Count missing, duplicate, invalid, and failed protected keys as failures. A favorable aggregate cannot cancel a protected-outcome failure. Changing the protected set is a contract revision and invalidates direct comparison until affected versions are rerun.

## Context and package drift

For every version, report package bytes, verified loaded component bytes, host-receipt tokens when available, measurement source, attribution coverage, p95 guardrail results, and end-to-end usage. Do not infer tokens from bytes or compare attributed context with paired-total-only data as though they were the same measure.

Re-audit package inventory, links, scripts, and security surfaces when their bytes change. A shorter package is not automatically a more useful Skill.

## Drift triggers

Open a new cycle when the Skill package, model/harness, relevant tool/API, fixture/grader, environment, neighboring catalog identity, authority policy, or exposed holdout state changes materially. The new cycle records which comparisons remain valid and which require rerun.

Cross-model, cross-domain, and cross-environment evidence is required only when portability is part of the claim. Report each axis separately and retain a fixed reference executor where practical for attribution.

## Monitoring and rollback

After an external owner accepts a version, retain:

- the accepted immutable package and decision evidence;
- the prior rollback package and restoration procedure;
- monitored failure classes and incident thresholds;
- environment/dependency drift triggers;
- the smallest sentinel case set that detects protected regressions;
- the condition that requires quarantine, rollback, or a new full cycle.

The evaluator reports these triggers and subsequent evidence. The external release authority owns deployment, promotion, rollback execution, and candidate creation.
