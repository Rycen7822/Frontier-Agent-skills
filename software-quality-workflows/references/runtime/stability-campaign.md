---
{
  "card_id": "sqw.runtime.stability-campaign",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.runtime.stability-campaign",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "runtime-stability-campaign"
  ],
  "max_bytes": 8192
}
---
# Runtime Stability Campaign

## Decision this card owns
Run a bounded sequence of fresh real-runtime rounds against one frozen public outcome and return truthful repeat, repair, block, inconclusive, or scoped-confidence facts.

## Use when
- `workflow-intake` explicitly requires repeated confidence through a real user-facing plugin, CLI, service, agent, benchmark, pipeline, or integration surface.

## Do not use when
- A one-shot smoke/unit repair is sufficient, repeated confidence is not justified, current identity cannot be reconciled, or repair/diagnosis owns the next decision.

## Required inputs
- `workflow-intake`; source root/revision/dirty scope; installed/package/service/container/profile/deployment identity and public entrypoint; canonical activation proof; representative outcome; required/excluded lifecycle surfaces; oracle and failure classes; health/progress signals; clean-round target and reset rules; durable issue/round location; authority, effects and protected data; and time/cost/quota/resource/external/destructive stop boundaries.

## Procedure
1. Freeze source identity separately from the active runtime target and exact public path. Define startup, intake, dispatch, state, resume, idempotency, output, verification, finalization, error, and cleanup surfaces with explicit exclusions.
2. Freeze a result artifact/oracle, honest failure taxonomy, clean consecutive-round target, reset conditions, bounded retry/backoff, durable secret-safe record schema, and resumable artifact identity. Default to three clean rounds only when multi-round hardening was explicitly requested.
3. Before every round, re-observe candidate and runtime version/content/config/registration/process freshness/health. Activate only through an authorized canonical path and prove replacement; source tests never establish installed or deployed provenance.
4. Execute exactly one fresh revision-bound public task and required lifecycle surfaces per Router selection. Internal calls are supporting evidence only. Record command/procedure, original status, reached and unreached surfaces, signals, artifacts, pending work, and cleanup.
5. Classify outcome as product issue, stale install/config, harness, environment, dependency, permission, resource/latency, hard-domain or benchmark result, baseline failure, or nondeterminism. For a product issue, record reproduction and owner seam before repair, then require proved activation and the same exposing-path rerun.
6. Update the clean count only after a full scoped clean; reset it on a product fix or material candidate revision. Preserve but label external failures, never weaken the task/oracle/gate/environment, and never use repeated runs to wash out deterministic failures or valid unfavorable results.
7. After that single round, emit Router facts for exactly one outcome: `confidence_met` requires real public completion, valid required gates, final active provenance, no pending work, every product issue fixed/activated/same-path proved or reported, and durable resumability; `repeat_required` stays inside budget and causes Router to reselect this card with a fresh projection; `repair_reroute` has a supported product issue; `blocked_external` names environment/permission/cost/quota/service/authority; `inconclusive` names stale, incomplete, or nondeterministic evidence.
8. Escalate instead of crossing destructive, external, authority, or budget boundaries. Report real-runtime proof, code-test-only proof, unverified/excluded surfaces, baselines and external blockers separately.

## Output contract
- One `runtime-stability-campaign` with frozen source/runtime/public-task identities, required/excluded surfaces, activation proof, round oracle and records, issue/fix/same-path evidence, clean target/count, final outcome facts, gates and pending work, budgets/stops, resumability state, blockers, and scoped residual risk.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after one round at a truthful scoped repeat/repair/block/inconclusive/confidence fact or authority/budget escalation. Do not run an open-ended loop in one card context or claim absolute/universal runtime reliability.
