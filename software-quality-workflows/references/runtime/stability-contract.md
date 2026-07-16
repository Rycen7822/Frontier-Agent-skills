---
{
  "card_id": "sqw.runtime.stability-contract",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "runtime_hardening_request",
    "actual_public_runtime_identity",
    "authority_and_budget"
  ],
  "produces": [
    "runtime_stability_contract"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "stability-to-round",
      "to_card_id": "sqw.runtime.stability-round",
      "edge_mode": "hard",
      "hard_predicate_id": "stability-round-required",
      "missing_decision": "Stability contract, signals, and budget are frozen but another round is required",
      "required_evidence": "Representative task, active-runtime proof, surfaces, oracle, clean target, stop and side-effect boundaries",
      "evict_when": "One revision-bound round result recorded"
    }
  ]
}
---
# Runtime Stability Contract

## Decision this card owns
Freeze a scoped repeated real-runtime confidence target, representative task, round oracle, clean-round goal, and authority/budget stop boundaries.

## Use when
- Explicit runtime hardening requires repeated execution through the real user-facing plugin/CLI/service/agent/benchmark/pipeline/integration surface.

## Do not use when
- A one-shot smoke/unit repair is sufficient or repeated runtime confidence was not requested/justified.

## Required inputs
- Product/source revision/dirty boundary, runtime target/provenance and activation path, representative public task, required lifecycle/surfaces, allowed edits/effects/protected data, round oracle/evidence, health/progress signals, clean-round target, and time/cost/quota/dependency/authority stops.

## Procedure
1. Bind source root/revision/dirty scope separately from installed/package/service/container/profile/deployment identity and exact public entrypoint.
2. Define representative user outcome and required startup/intake/dispatch/state/resume/idempotency/output/verification/finalization/error surfaces with explicit exclusions.
3. Freeze canonical activation plus proof that a changed candidate became active; source tests never establish installed/deployed provenance.
4. Define round success artifact/oracle and honest failure classes; do not weaken task, verifier, gate, or environment to manufacture green.
5. Set clean consecutive-round target; default three only for explicitly requested multi-round hardening. Reset on product fix or material candidate revision.
6. Set bounded retry/backoff, time/cost/quota/resource/external/destructive/authority stops, durable issue/round record location, secret-safe fields, and resumable artifact identity.
7. Emit `round_required` only when contract, health/progress signals, activation, oracle, and budget are executable; otherwise emit blocked/inconclusive with exact missing input.

## Output contract
- Source/runtime/public-task identities; required/excluded surfaces; activation/provenance proof; round oracle; clean target/current count; signal and durable-record schema; budgets/stops/effects; blocker and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `stability-to-round` | Stability contract, signals, and budget are frozen but another round is required | Representative task, active-runtime proof, surfaces, oracle, clean target, stop and side-effect boundaries | `sqw.runtime.stability-round` | One revision-bound round result recorded |

## Stop
Stop at an executable scoped contract or precise blocker; never claim universal future reliability.
