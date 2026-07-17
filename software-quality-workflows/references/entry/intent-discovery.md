---
{
  "card_id": "sqw.entry.intent-discovery",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "sqw.select.entry.intent-discovery",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "workflow-intake"
  ],
  "max_bytes": 4096
}
---
# Intent Discovery Entry

## Decision this card owns
Determine whether evidence can close intent or a material outcome decision remains open.

## Use when
- Multiple materially different outcomes may satisfy the request or a required observable outcome is missing.

## Do not use when
- Intent is already fixed, or only the cause of a failure is unknown.

## Required inputs
- Request sources, repository/session evidence, public behavior, authority, reversibility, constraints, and current scope identity.

## Procedure
1. Inspect project owners, code, tests, docs, prior decisions, and available session context before asking for repeated facts.
2. Separate observable outcome, users, scope, success, non-goals, assumptions, and unresolved semantics from implementation technique.
3. Decompose independent products or subsystems and identify the first bounded outcome.
4. Record only repository-supported defaults that are explicit, low impact, reversible, and inside authority.
5. Type conflicting, external, legal, product, costly, irreversible, or user-visible gaps without guessing.
6. Emit `workflow-intake` plus a typed intent decision request when material semantics remain; otherwise return the evidence-backed defined intent.

## Output contract
- One `workflow-intake` with normalized outcome/scope/success/non-goals, decomposition, safe defaults, material gap IDs, conflicts, authority, blocker, and optional typed intent request.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when intent is defined or a typed underdetermination/conflict boundary is established.
