---
{
  "card_id": "sqw.workspace.prototype-lifecycle",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.workspace.prototype-lifecycle",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "workspace-prototype-lifecycle"
  ],
  "max_bytes": 8192
}
---
# Prototype Lifecycle

## Decision this card owns
Run and dispose/retain/reclassify one isolated falsifiable experiment without treating its success as production readiness or lifting code silently.

## Use when
- A cheapest task-owned experiment/probe can answer one material architecture, feasibility, diagnosis, or product question.

## Do not use when
- The requested artifact is retained product/source/config, report-only mode forbids writes, or normal implementation proof already answers the question.

## Required inputs
- `workflow-intake`; one decision question; falsifiable learning criterion/oracle; cheapest artifact; diagnose/change mode and side-effect ceiling; isolation from production/user state; owner; expiry; disposition choices; evidence location; and cleanup/promotion authority.

## Procedure
1. Classify by outcome rather than the word prototype: disposable diagnostic probe may use authorized local reversible writes; retained/shipped/product-facing artifact is change; report-only creates neither.
2. Keep experiment outside production state/shipped paths unless explicitly authorized with its own controls and instrument only what answers the question.
3. Execute within bounded inputs/time/resources/effects and record exact artifact/revision, method, outcome, failures, and limitations.
4. Judge only the learning criterion; success proves neither readiness, maintainability, security, compatibility, scale, nor deployment.
5. At expiry preserve the decision plus compact evidence pointer; remove task-owned throwaway code when no durable consumer exists or deliberately reclassify a retained harness as an active fixture.
6. Promotion re-expresses learned behavior through normal architecture, planning, TDD, security/compatibility, and layered verification; never copy prototype code directly because it passed.
7. Treat branch/publication/deployment/collaboration as separate authority and report cleanup/retained artifacts explicitly.

## Output contract
- One `workspace-prototype-lifecycle` with question/oracle/mode/authority, isolated artifact identity, bounded execution/evidence, learning verdict/limits, expiry/disposition, compacted evidence, cleanup or fixture reclassification, promotion handoff, and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at one falsifiable verdict and explicit artifact disposition; do not infer or grant production readiness.
