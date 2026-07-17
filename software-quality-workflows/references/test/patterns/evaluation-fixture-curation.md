---
{
  "card_id": "sqw.test.patterns.evaluation-fixture-curation",
  "card_version": 2,
  "kind": "recipe",
  "decision_id": "sqw.select.test.patterns.evaluation-fixture-curation",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "test-patterns-evaluation-fixture-curation"
  ],
  "max_bytes": 8192
}
---
# Evaluation Fixture Curation Pattern

## Decision this card owns
Apply one reviewed revision-bound benchmark, retrieval, ranking, routing, or recommendation fixture delta with defensible oracles, representative diversity, held-out evidence, and exact durable count.

## Use when
- `workflow-intake` requires expanding or repairing a canonical evaluation corpus, an exact accepted count, or a missing contract stratum.

## Do not use when
- Data is disposable diagnostic output, labels lack a defensible oracle, or one unreviewed model would generate, filter, and judge all cases.

## Required inputs
- `workflow-intake`; versioned manifest, schema, evaluator and metrics; current accepted inventory; exact target and strata; categories/languages/exclusions; provenance/privacy/license/dedup rules; independent judgment/oracle; generator/filter/seed/removal/refill policy; held-out/parity set; noise, repeat and threshold contract; and canonical revision.

## Procedure
1. Read accepted cases from disk, normalize IDs/prompts/gold targets/exclusions/categories/language/provenance/evaluator version, and freeze the exact target plus missing strata before candidate generation.
2. Keep candidates and rejections outside canonical data. Freeze oracle, warmup/noise/repeats, thresholds and aligned failure corpus independently of the candidate; separate candidate generation from approval where practical.
3. Validate schema, provenance, privacy/license, duplicates and oracle quality. For retrieval-like tasks, exercise the real retrieval path, distinguish exploratory top-k usefulness from top-choice precision, and measure task metrics plus category balance, normalized entropy, near-duplicate similarity and novelty.
4. Compare held-out/parity behavior and require independent human/domain adjudication for ambiguous or high-impact gold changes. Reproduce path/budget flakes in a controlled short environment before altering scoring or gold.
5. Apply only the reviewed manifest delta, reread canonical data, and prove before/after identity, exact accepted count from disk, strata/diversity, metrics, held-out/adjudication, provenance, privacy/license, dedup and oracle status.
6. Compact durable selection evidence before scratch cleanup. Roll back only the task-owned delta after confirming the canonical post-update revision; reconcile drift instead of overwriting concurrent work.

## Output contract
- One `test-patterns-evaluation-fixture-curation` with candidate/accepted/rejected delta, canonical before/after identity, exact accepted count, strata and diversity metrics, schema/provenance/privacy/license/dedup/oracle checks, held-out/parity/adjudication evidence, rollback state, and unresolved items.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after durable reread and exact quality/count proof; parsing or generation is not acceptance, and fixtures or thresholds cannot be tuned against the evaluated candidate.
