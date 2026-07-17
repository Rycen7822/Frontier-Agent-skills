---
{
  "card_id": "wp.profiles.handoff",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "wp.select.profiles.handoff",
  "required_artifact_ids": [],
  "produced_artifact_ids": ["plan-handoff"],
  "max_bytes": 4096
}
---
# Executable Handoff

## Decision this card owns
Freeze the minimum durable handoff needed for another turn, session, or authorized worker to continue without rediscovery.

## Use when
- Execution crosses a context boundary or has multiple independently owned slices.

## Do not use when
- A same-context Brief is sufficient or the work requires a multi-stage Program state.

## Required inputs
- Source revision, scope and authority identities, intended outcome, current frontier, evidence anchors, dependencies, and verification gates.

## Procedure
1. Bind the handoff to source, scope, authority, and bundle identity.
2. Record goal/non-goals, global invariants/owner seams, requirement/constraint coverage, completed evidence, pending decisions, and blockers separately.
3. Give ordered outcome slices stable dependencies, allowed writes/effects, one owner, acceptance/verifier distinction, false-green risk, and produced evidence.
4. Record current frontier, rollback, fog, and only source-bound resume commands/anchors.
5. Render the bounded [Handoff template](../../templates/executable-handoff.md) and emit the cross-skill envelope with no SQW internal card ID or Markdown path.

## Output contract
- One `plan-handoff` binding handoff/bundle/source/profile, plan/authority/scope/frontier/policy identities, explicit blockers, and no inferred authority.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after the receiving boundary can validate identity and reroute inside its own skill manifest.
