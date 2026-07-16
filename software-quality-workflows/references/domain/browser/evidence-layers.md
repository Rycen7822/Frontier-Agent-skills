---
{
  "card_id": "sqw.domain.browser.evidence-layers",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "browser_claim_and_user_path",
    "browser_surface_identity",
    "available_runtime_evidence"
  ],
  "produces": [
    "browser_evidence_plan_and_observation"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "browser-to-live-readiness",
      "to_card_id": "sqw.domain.browser.live-readiness",
      "edge_mode": "hard",
      "hard_predicate_id": "live-readiness-required",
      "missing_decision": "Live update or readiness is an acceptance surface and proof is absent",
      "required_evidence": "Route, stream/poll contract, readiness state, event ordering and cleanup needs",
      "evict_when": "Live-readiness artifact recorded"
    },
    {
      "edge_id": "browser-to-content-security",
      "to_card_id": "sqw.domain.browser.content-security",
      "edge_mode": "hard",
      "hard_predicate_id": "untrusted-content-implicated",
      "missing_decision": "Untrusted rich content, CSP, escaping, or sanitization is implicated",
      "required_evidence": "Content contract, renderer/parser path, trust boundary, DOM and injection cases",
      "evict_when": "Browser content-security artifact recorded"
    }
  ]
}
---
# Browser Evidence Layers

## Decision this card owns
Select and execute the minimum browser evidence layers that can prove the exact user-facing claim and localize its failure.

## Use when
- Rendered behavior, client data flow, console/network, accessibility state, responsive layout, or visual/runtime claims cannot be proven statically.

## Do not use when
- No browser surface is affected or installed/runtime identity is unresolved upstream.

## Required inputs
- Route/interaction and source-built-installed identity, trusted target, starting artifact, claim, breakpoints/states, automation, and side-effect authority.

## Procedure
1. Match evidence to claim: source/static for branches/transforms; HTTP for status/headers/payload; DOM/accessibility for roles/focus/geometry; screenshot for qualitative layout; console/network for runtime/request failures.
2. Reproduce the exact trusted route/interaction and preserve the smallest starting artifact; a screenshot alone proves neither cause nor numeric accessibility conformance.
3. Inspect relevant DOM/accessibility, computed properties, console, requests, and geometry; use computed colors/calculation for contrast claims.
4. Trace visible data through request, normalization, client state, renderer, and built/installed path; distinguish static shell from live endpoint/stream.
5. Classify source, data flow, layout, runtime config, network/API, compatibility, or harness cause; fix/probe only with separately authorized change mechanics and keep page evaluation read-only by default.
6. Re-observe clean state and nearest automation, including responsive and empty/error/loading states. Select one missing edge; preserve any second implication for post-artifact Router reselection.

## Output contract
- Surface identity, layer rationale/observations, route, data lineage, cause, clean-state proof, gaps, cleanup, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `browser-to-live-readiness` | Live update or readiness is an acceptance surface and proof is absent | Route, stream/poll contract, readiness state, event ordering and cleanup needs | `sqw.domain.browser.live-readiness` | Live-readiness artifact recorded |
| `browser-to-content-security` | Untrusted rich content, CSP, escaping, or sanitization is implicated | Content contract, renderer/parser path, trust boundary, DOM and injection cases | `sqw.domain.browser.content-security` | Browser content-security artifact recorded |

## Stop
Stop after the claim is proved/unverified or one missing browser decision is selected; do not infer layers from screenshots alone.
