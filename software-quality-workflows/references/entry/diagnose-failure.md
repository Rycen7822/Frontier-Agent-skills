---
{
  "card_id": "sqw.entry.diagnose-failure",
  "card_version": 1,
  "kind": "entry",
  "consumes": [
    "failure_report",
    "request_mode",
    "authority_projection",
    "source_projection",
    "existing_patch_projection"
  ],
  "produces": [
    "diagnosis_contract",
    "next_edge_id"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "diagnose-to-reproduce",
      "to_card_id": "sqw.diagnosis.reproduce-and-bound",
      "edge_mode": "hard",
      "hard_predicate_id": "fresh-reproduction-missing",
      "missing_decision": "Fresh reproduction and bounded failure surface are absent",
      "required_evidence": "Failure report and executable observation surface",
      "evict_when": "Reproduction record and failure boundary are recorded"
    }
  ]
}
---
# Diagnose Failure

## Decision this card owns
Establish the bounded symptom-to-cause diagnosis contract without authorizing implementation before the cause is supported.

## Use when
- A failure, regression, unexpected behavior, integration break, or performance/runtime anomaly has an unknown root cause.

## Do not use when
- A fresh supported cause already exists, or the request authorizes only a static report with no diagnostic probe.
- The task is a feature, refactor, or migration with no unexplained failure.

## Required inputs
- Request mode, failure report, observable surface, source revision, authority ceiling, environment limits, and any existing patch or concurrent work.

## Procedure
1. Restate the symptom without embedding a favored cause or speculative repair.
2. Bind the stopping point to request mode: report findings only, diagnose to supported cause/`INCONCLUSIVE`, or prepare a repair only after cause and change authority exist.
3. Preserve any existing patch and record what it currently changes; do not discard it to recreate a preferred workflow.
4. Identify the smallest observable reproduction surface and separate product behavior from harness/environment prerequisites.
5. Record current source, relevant state identity, protected work, probe side-effect ceiling, and cleanup boundary.
6. Block production changes, persistent instrumentation, and repair attempts until discriminating evidence supports a cause.
7. Request the reproduction card when a fresh bounded reproduction artifact is missing.

## Output contract
- `request_mode`, `symptom`, `observation_surface`, `source_identity`, `existing_patch_projection`, `probe_boundary`, `implementation_blocked`, `next_edge_id`, and `blocker|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `diagnose-to-reproduce` | Fresh reproduction and bounded failure surface are absent | Failure report and executable observation surface | `sqw.diagnosis.reproduce-and-bound` | Reproduction record and failure boundary are recorded |

## Stop
Stop after emitting the diagnosis contract; reroute after the reproduction artifact boundary.
