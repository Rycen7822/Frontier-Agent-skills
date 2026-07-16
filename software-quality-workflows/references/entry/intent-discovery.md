---
{
  "card_id": "sqw.entry.intent-discovery",
  "card_version": 1,
  "kind": "entry",
  "consumes": [
    "request_source",
    "repository_evidence",
    "authority_projection"
  ],
  "produces": [
    "intent_assessment",
    "next_edge_id"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "intent-to-material-gaps",
      "to_card_id": "sqw.intent.material-intent-gaps",
      "edge_mode": "hard",
      "hard_predicate_id": "material-intent-assessment-missing",
      "missing_decision": "Material intent gaps have not been classified",
      "required_evidence": "Request sources and repository-observable defaults",
      "evict_when": "Intent gaps and safe defaults are classified"
    }
  ]
}
---
# Intent Discovery

## Decision this card owns
Determine whether repository evidence or a safe default can close intent, or whether material semantics remain unresolved.

## Use when
- Multiple materially different outcomes may satisfy the current wording, or a required outcome is missing.

## Do not use when
- The outcome is already fixed, or only the failure cause is unknown.

## Required inputs
- Request sources, repository conventions, current public behavior, authority, and reversibility facts.

## Procedure
1. Inspect project structure, owners, relevant code/tests/docs, prior decisions, and available session context before asking the user to repeat facts.
2. Normalize observable outcome, users, constraints, success, non-goals, assumptions, and unresolved decisions separately from implementation detail.
3. Decompose independent products/subsystems and select the first bounded outcome slice before specification.
4. Identify repository-supported defaults that are explicit, reversible, and low risk.
5. Mark conflicting, external, legal, product, costly, or irreversible decisions and classify every material gap rather than asking routine preferences.
6. Skip this branch for precise approved/report/diagnosis/mechanical work; otherwise request the gap card only when no assessment artifact exists.

## Output contract
- `intent_status`, normalized outcome/scope/success/non-goals, bounded decomposition, `safe_defaults`, `material_gap_ids`, conflicts, `next_edge_id`, and `terminal_certificate|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `intent-to-material-gaps` | Material intent gaps have not been classified | Request sources and repository-observable defaults | `sqw.intent.material-intent-gaps` | Intent gaps and safe defaults are classified |

## Stop
Stop when intent is adequate or a typed underdetermination/conflict result has been emitted.
