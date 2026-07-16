---
{
  "card_id": "sqw.domain.browser.live-readiness",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "browser_evidence_plan_and_observation",
    "live_update_contract",
    "readiness_and_cleanup_boundary"
  ],
  "produces": [
    "browser_live_readiness_artifact"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Browser Live Readiness

## Decision this card owns
Prove document readiness and contract-relevant live state, event behavior, failure handling, and cleanup for streaming or long-poll browser surfaces.

## Use when
- Live updates, readiness, persistent streams, reconnect, polling, or asynchronous zero/progress state is an acceptance surface.

## Do not use when
- The page is static or ordinary bounded request/render evidence already proves the claim.

## Required inputs
- Trusted route/interaction, document/live contract, event identity/order/dedup/reconnect/cancel/end semantics, concrete ready/zero/error state, process/profile/fixture identity, and time/cleanup budget.

## Procedure
1. Wait for document readiness plus a concrete contract-relevant element/state; persistent streams make network-idle alone invalid readiness proof.
2. Observe initial state, incremental events, ordering, duplicate handling, reconnect/resume, cancellation/disconnect/end, explicit zero state, and error/recovery as applicable.
3. Bind console/network/DOM observations to event/request and client-state identity; distinguish delayed data, static shell, and rendering defects.
4. Exercise a clean reload/retrigger and bounded time budget; classify harness startup separately and use an alternate probe only when it proves the same contract.
5. Restore temporary browser profile, feature setting, fixture, and task-owned process/port; verify no live listener/connection/process remains unexpectedly.
6. Record actual built/installed surface, readiness/event evidence, unverified states, and product versus harness status.

## Output contract
- Surface/route identity, readiness predicate, initial/live/reconnect/order/dedup/cancel/zero/error observations, console/network/DOM refs, timing, harness classification, cleanup, gaps and verdict.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at bounded live evidence; never wait indefinitely for network idle or hide harness failure as product failure.
