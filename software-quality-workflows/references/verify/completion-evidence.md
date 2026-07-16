---
{
  "card_id": "sqw.verify.completion-evidence",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "verification_plan",
    "gate_run_records",
    "failure_classifications",
    "coverage_ledger",
    "freshness_decision"
  ],
  "produces": [
    "completion_evidence_record"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Completion Evidence

## Decision this card owns
Decide what can truthfully be claimed from fresh gate, coverage, baseline, public-surface, and pending-review evidence.

## Use when
- Implementation or analysis is ending and required evidence must be assembled into a scoped completion, interim, blocked, or inconclusive record.

## Do not use when
- A required gate has not run, a failure is unclassified, source/scope drift is unresolved, or the work is still changing.

## Required inputs
- Verification plan, immutable gate records, failure classifications, source/scope/environment identity, coverage and freshness decisions, public/installed proof, baseline delta, and pending async reviews or blockers.

## Procedure
1. For each applicable gate, record gate ID, exact command/procedure, original result, source/scope identity, and evidence ref.
2. List `not_applicable` and `not_run` gates separately with reasons; never describe ad-hoc evidence as suite or canonical success.
3. Record baseline failures, warnings, and flakiness separately from scoped regressions.
4. For installed or public surfaces, require provenance/version at the executed layer and a smallest real path from a neutral context; source tests alone are insufficient.
5. Require fresh evidence after any relevant source, scope, environment, artifact, or verifier identity change.
6. If any required gate, coverage item, review, or blocker audit is pending, mark the result interim. If evidence cannot support a determination, use `inconclusive`.
7. Keep local technical verification separate from merge, publication, release, or remote-write readiness.

## Output contract
- `completion_evidence_record`: scoped status, source/scope/environment identities, applicable gate records, public-surface proof, not-run/not-applicable items, baseline delta, coverage, pending items, and residual uncertainty.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop before a verified/completed claim unless every required record is fresh and passing within scope; this artifact never grants publication or external-write authority.
