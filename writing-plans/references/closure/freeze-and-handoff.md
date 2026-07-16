---
{
  "card_id": "wp.closure.freeze-and-handoff",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "validated_closure_contract",
    "canonical_plan_identity",
    "handoff_identity_inputs"
  ],
  "produces": [
    "frozen_closure_contract",
    "plan_execution_handoff"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Freeze Closure Contract and Handoff

## Decision this card owns
Publish one immutable closure-contract epoch and an exact identity envelope that SQW can validate before creating execution state.

## Use when
- All contract sections pass schema and semantic validation for one eligible Admission/source/scope/policy/authority identity.

## Do not use when
- Material ambiguity, constraint conflict, incomplete verifier/search policy, stale identity, or unresolved blocker remains.

## Required inputs
- Admission ref/hash/decision; bundle ID; source revision; scope hash; authority manifest ref/hash/ceiling; validated draft; canonical plan ref/hash/profile/frontier; execution policy; unresolved blockers.

## Procedure
1. Revalidate eligible Admission plus bundle/source/scope/policy/authority/environment bindings; freeze cannot widen any ceiling.
2. Validate stable constraint/corner/verifier IDs, continuous soft-objective priority, semantic completeness, and absence of actual candidate/runtime/verdict state.
3. Canonicalize with the self-hash field omitted, assign a new monotonic epoch, and publish atomically to a no-overwrite immutable path. Supersession never mutates an old epoch.
4. Keep the frozen contract independent of plan/candidate/workflow references. Bind the plan separately in the handoff.
5. Emit `plan-execution-handoff` with handoff/bundle/source identity, execution policy/profile, Admission ref/hash, plan ref/hash, contract ref/hash, authority ref, scope hash, frontier node IDs, required SQW policy IDs, and unresolved blockers.
6. Include no SQW Markdown path or internal card ID. SQW derives its initial phase/primary card after verifying the envelope.
7. On publication race or identity drift, leave existing artifacts untouched and return a typed stale/no-overwrite failure.

## Output contract
- Immutable contract ID/ref/hash/epoch and schema-valid handoff identity. For autonomous closure all Admission/contract fields are non-null; standard handoffs keep all four null and use `execution_policy=standard`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at a validated immutable contract plus handoff, or a typed binding/publication failure; never claim SQW execution closure.
