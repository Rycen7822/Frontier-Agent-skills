---
{
  "card_id": "wp.entry.plan-route",
  "card_version": 1,
  "kind": "entry",
  "consumes": [
    "plan_route_facts",
    "request_source",
    "closure_admission_projection"
  ],
  "produces": [
    "plan_route",
    "profile_selection"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Plan Route

## Decision this card owns
Decide whether planning is needed and select Direct, SQW diagnosis/intent, Brief, Handoff, Program, spike, long-document handoff, or terminal.

## Use when
- A request may need a durable implementation plan, cross-context handoff, migration map, or Closure Contract.

## Do not use when
- The exact plan route and profile already exist for the current source/scope identity.

## Required inputs
- Request mode, intent/root-cause status, authority, scope, persistence need, closure admission, and task shape.

## Procedure
1. Reject incomplete route facts and preserve request mode.
2. Return diagnosis or intent artifacts to SQW before implementation planning.
3. Bypass planning for routine local work unless a plan was explicitly requested.
4. Select Brief, Handoff, or Program by persistence and dependency needs.
5. Route one falsifiable feasibility gap to spike and large non-software synthesis to its owner.
6. Emit exactly one route/profile result with no reference list.

## Output contract
- `route`, `profile|null`, `execution_policy`, `primary_card|null`, `required_artifact_projection_ids`, `reason_codes`, and `handoff_owner|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after emitting one exact route; the Router selects the chosen profile or decision card on the next invocation.
