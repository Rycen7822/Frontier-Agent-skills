# Browser Evidence and Readiness

## Purpose
Select minimum browser evidence for the exact user claim and prove document/live readiness, failure behavior, and cleanup when applicable.

## Use when
- Rendered behavior, client data flow, accessibility/geometry, console/network, responsive layout, readiness, streams, reconnect, polling, or asynchronous state requires runtime proof.

## Do not use when
- No browser surface is affected or static/ordinary request evidence already proves the claim.

## Required inputs
- task context; source/build/installed surface identity; trusted route/interaction; claim and starting artifact; breakpoints/states; HTTP/DOM/accessibility/screenshot/console/network capabilities; live event contract; side-effect/time/cleanup authority.

## Procedure
1. Match evidence to claim: source/static branches, HTTP status/headers/payload, DOM/accessibility roles/focus/geometry, screenshot qualitative layout, console/network runtime failures, and computed values for numeric contrast/geometry.
2. Reproduce the exact trusted route/interaction and preserve the smallest starting artifact. A screenshot alone proves neither cause nor numeric conformance.
3. Trace request, normalization, client state, renderer, and built/installed path; distinguish static shell, delayed/live data, network/API, runtime config, layout, compatibility, and harness causes.
4. Inspect relevant DOM/accessibility/computed properties, console, requests, responsive viewport, empty/loading/error states, and nearest automation. Keep page evaluation read-only by default.
5. For live surfaces, wait for document readiness plus a concrete contract state; network idle is invalid for persistent streams. Observe initial/zero state, event identity/order/dedup, reconnect/resume, cancel/disconnect/end, error/recovery, and bounded time decision.
6. Bind observations to request/event/client-state identity, run a clean reload/retrigger, and classify product versus startup/harness failure; an alternate probe must prove the same contract.
7. Restore task-owned browser profile, feature settings, fixtures, process/port, listeners, and connections; report unverified states separately.

## Required result
- One `domain-browser-evidence-and-readiness` with surface/route identity, layer rationale, DOM/accessibility/geometry/console/network observations, data lineage and cause, readiness predicate, live/order/dedup/reconnect/cancel/zero/error results, timing, clean-state proof, harness classification, cleanup, gaps, and verdict.

## Stop
Stop at bounded browser evidence; never infer missing layers from screenshots or wait indefinitely for network idle.
