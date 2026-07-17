---
{
  "card_id": "sqw.test.patterns.dashboard-evidence",
  "card_version": 2,
  "kind": "recipe",
  "decision_id": "sqw.select.test.patterns.dashboard-evidence",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "test-patterns-dashboard-evidence"
  ],
  "max_bytes": 8192
}
---
# Dashboard Evidence Pattern

## Decision this card owns
Prove a dashboard's exact data lineage, API/browser/stream semantics, source-versus-installed path, and read-only persistence boundary.

## Use when
- `workflow-intake` identifies missing/misclassified records or requires proof that a local inspection dashboard reads the intended store without mutation.

## Do not use when
- The failure is purely visual after a complete correct API model, the UI writes the store, is internet-facing, or needs product-specific deployment/security design.

## Required inputs
- `workflow-intake`; UI selection/request code; API schema/handler; query/repository and migrations; canonical current/history/raw/cache/derived ownership; running process, schema and data-root identity; read-only and stream contracts; source and installed launch paths; isolated fixture/copy; loopback process/port; and browser evidence needs.

## Procedure
1. Trace UI selection through request parameters, handler, query and backing table/collection; validate identifiers and join keys at every layer. Separate current canonical records from history, raw events, caches and summaries.
2. Define explicit zero states for requested absent categories rather than falling back to another dataset. Visible count is not correctness, and semantically distinct current/history surfaces stay separate.
3. Use an isolated copy or explicitly read-only connection; missing data must report absence without creating a store. Freeze store identity before launch.
4. Test data layer, API, source launch, installed/public launch and browser surface separately. Prove the running process uses the inspected schema/data root with one current record, one historical/raw event and one absent category, each visible only in its intended surface.
5. For streams, prove initial data, incremental events, disconnect/end behavior and client cleanup. Record actual process identity, loopback address, assigned port, rendered/asynchronous state, console and network responses.
6. Confirm unchanged backing-store identity, then stop only task-owned process/browser/port and remove only the isolated fixture/copy.

## Output contract
- One `test-patterns-dashboard-evidence` with lineage IDs/joins, process/schema/data-root and store before/after identities, source/installed layer evidence, fixture/query/API/UI/stream/browser/zero-state proof, semantic gaps, failures, and task-owned cleanup.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at lineage and read-only dashboard proof; do not merge distinct datasets for visible counts or clean/probe a shared data root without authority.
