---
{
  "card_id": "sqw.runtime.stability-round",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "runtime_stability_contract",
    "current_candidate_and_runtime_projection",
    "prior_round_and_issue_state"
  ],
  "produces": [
    "runtime_stability_round_result"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 8192,
  "neighbors": [
    {
      "edge_id": "stability-round-to-exit",
      "to_card_id": "sqw.runtime.exit-and-escalation",
      "edge_mode": "hard",
      "hard_predicate_id": "stability-exit-triggered",
      "missing_decision": "Stop, blocked, budget, confidence target, or escalation condition requires an exit judgment",
      "required_evidence": "Round outcome, clean count, issue state, active provenance, gates, pending work, and boundary",
      "evict_when": "Exit/escalation judgment recorded"
    }
  ]
}
---
# One Runtime Stability Round

## Decision this card owns
Execute and classify exactly one revision-bound representative task through the active public runtime, producing a fresh projection for repeat/repair/exit.

## Use when
- A frozen stability contract requires a round and its authority, budget, runtime, signals, and oracle remain current.

## Do not use when
- Contract/provenance is stale, a repair/diagnosis owner is active, or an exit/escalation trigger already exists.

## Required inputs
- Contract and round number, current source/scope/dirty and active runtime provenance/config/health, canonical activation status, real command/procedure, required surfaces/oracle, open issues/fixes, budgets, and prior clean count.

## Procedure
1. Re-observe candidate and runtime target version/content/config/registration/process freshness/health; activate only through an authorized canonical path and prove replacement before judging a fix.
2. Execute the exact public CLI/API/UI/plugin/scheduler/benchmark/integration task and required lifecycle surfaces; internal calls are supporting evidence only.
3. Observe behavior and signals, classify product versus stale install/config, harness, environment, dependency, permission, resource/latency, hard-domain/reward, baseline, or nondeterministic outcome.
4. Record each new product issue before repair. Stop/reroute with reproduction, owner seam, meaningful distinction and same-path rerun need when continuing would corrupt evidence/waste resources/cross a boundary.
5. For an externally completed fix, reconfirm activated provenance and rerun the same exposing path before broader execution; never trust a fix report without actual state/evidence.
6. Emit exactly `clean_round`, `fix_required`, `blocked_external`, or `inconclusive`; list reached/not-reached surfaces, new issues, evidence/statuses, pending processes/jobs/sessions, and cleanup.
7. Increment clean count only for full scoped clean; reset on product fix/material revision, preserve but annotate clearly external failure, and indicate repeat versus exit-trigger facts.

## Output contract
- Round/candidate/runtime identities, command/procedure and original status, reached/excluded surfaces, issue/failure classification, same-path evidence, active provenance, outcome, clean count, budgets/pending work/cleanup, reroute request and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `stability-round-to-exit` | Stop, blocked, budget, confidence target, or escalation condition requires an exit judgment | Round outcome, clean count, issue state, active provenance, gates, pending work, and boundary | `sqw.runtime.exit-and-escalation` | Exit/escalation judgment recorded |

## Stop
Stop after one round result. Router repeats this same card with a fresh projection or selects repair/diagnosis/exit; do not run an open-ended loop in one context.
