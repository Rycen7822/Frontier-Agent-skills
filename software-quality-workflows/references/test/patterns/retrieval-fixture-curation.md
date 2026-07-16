---
{
  "card_id": "sqw.test.patterns.retrieval-fixture-curation",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "retrieval_case_schema",
    "retrieval_oracle_and_metrics",
    "fixture_target_and_provenance"
  ],
  "produces": [
    "retrieval_fixture_delta_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Retrieval Fixture Curation Pattern

## Decision this card owns
Curate a revision-bound retrieval/ranking/routing fixture delta with defensible gold labels, diversity, held-out evidence, and exact durable count.

## Use when
- Retrieval, ranking, routing, or recommendation evaluation data is expanded or repaired.

## Do not use when
- Labels lack a defensible oracle or one unreviewed model would generate, filter, and judge every case.

## Required inputs
- Versioned case schema/evaluator/metrics, provenance and judgment policy, exact target, current accepted inventory, categories/languages/exclusions, duplicate rule, held-out set, and canonical revision.

## Procedure
1. Normalize IDs, prompts, gold targets, exclusions, categories, language, provenance, evaluator version, seed/generator/filter rules, removals, and refill decisions.
2. Keep candidates/rejections outside canonical data; separate exploratory top-k usefulness from top-choice precision and use the real retrieval path.
3. Measure task metrics and diversity: category balance, normalized entropy, near-duplicate similarity, and novelty.
4. Use held-out cases and independent human/domain adjudication for ambiguous or high-impact gold changes; separate generation from approval where practical.
5. Reproduce path/budget flakes in a controlled short environment before changing scoring or gold.
6. Apply only the reviewed delta, re-read canonical data, and prove accepted count, schema, metrics, diversity, held-out/adjudication status, and saved identity.
7. Before inverse rollback, confirm canonical post-update revision; reconcile drift instead of overwriting concurrent work.

## Output contract
- Candidate/accepted/rejected manifest delta, canonical before/after revision, exact accepted count, schema/provenance/dedup/metric/diversity/held-out evidence, adjudication, rollback and unresolved items.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after durable re-read and exact count; parsing or generation alone is not acceptance.
