---
{
  "card_id": "sqw.safety.side-effect-risk",
  "card_version": 1,
  "kind": "safety",
  "consumes": [
    "request_mode_decision",
    "authority_decision",
    "proposed_action",
    "runtime_observation"
  ],
  "produces": [
    "side_effect_decision",
    "probe_boundary"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Side-effect Risk

## Decision this card owns
Classify an action by its real effects and decide whether it is allowed, must be isolated, needs explicit authority, or must stop.

## Use when
- A command may write state, create processes/resources, touch external systems, require privilege, or destroy data or repository state.

## Do not use when
- Existing evidence proves the bounded action is read-only and inside the current scope and authority decision.

## Required inputs
- Proposed command or operation, request mode, authority ceiling, target identity, owning configuration, expected writes/resources, credentials/cost, and cleanup or rollback evidence.

## Procedure
1. Classify actual behavior as `READ_ONLY`, `LOCAL_REVERSIBLE`, `EXTERNAL_STATE`, or `PRIVILEGED_DANGEROUS`; names such as test, check, build, and dry-run are not evidence.
2. Allow bounded reads inside scope. Allow local reversible writes only for authorized change work or a task-owned isolated diagnostic probe.
3. Treat push, hosted comments or approvals, CI reruns, releases, installed-copy synchronization, persistent services, and remote mutations as external state requiring exact authority.
4. Treat host-policy changes, real-data deletion, destructive VCS operations, unknown-process control, and publicly reachable debugging as privileged/dangerous; present the safer alternative and require exact authorization.
5. For a probe, bind a task-unique location, resource/port identity, credential and cost ceiling, retry budget, residue policy, and cleanup proof before execution.
6. Reject unsafe archive paths, traversal, absolute paths, unsafe links, ambiguous candidate counts, or shared temporary paths.
7. After failure, classify product defect, harness gap, environment unavailable, or permission denied before changing product behavior.

## Output contract
- `side_effect_decision`: risk class, target identity, allowed/blocked status, authority evidence, rollback/cleanup obligations, and reason code.
- `probe_boundary`: exact disposable resources and stop conditions, or `null` when no probe is authorized.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop before any ungranted external, privileged, destructive, financial, persistent, or ambiguous side effect.
