---
{
  "card_id": "sqw.test.patterns.dashboard-data-lineage",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "dashboard_query_contract",
    "api_storage_lineage",
    "record_fixture"
  ],
  "produces": [
    "dashboard_data_lineage_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Dashboard Data-Lineage Pattern

## Decision this card owns
Locate and prove the exact UI→request→API→query→store lineage when a dashboard appears to omit or misclassify records.

## Use when
- Visible records, layers, history, or status disagree with known storage activity.

## Do not use when
- API already returns the complete correct model and the failure is purely visual.

## Required inputs
- UI selection/request code, API schema/handler, query/repository, migrations, record ownership, running data-root/schema identity, and isolated fixture.

## Procedure
1. Trace UI selection through request parameters, handler, query, and backing table/collection; validate identifiers and join keys at every layer.
2. Distinguish canonical current records from raw events, history, caches, and derived summaries.
3. Expose explicit zero states for requested absent categories instead of falling back to another dataset.
4. Keep current and historical surfaces separate when semantics differ; visible count is not correctness.
5. Prove the running process uses the inspected schema/data root with one current record, one historical/raw event, and one absent category.
6. Assert each fixture appears only in its intended surface; remove only task-owned fixture records/copies.

## Output contract
- Lineage map with IDs/joins, process/schema/data-root identity, fixture and query/API/UI evidence, zero-state proof, semantic gaps, and cleanup.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at lineage evidence; do not merge semantically different datasets to increase visible counts.
