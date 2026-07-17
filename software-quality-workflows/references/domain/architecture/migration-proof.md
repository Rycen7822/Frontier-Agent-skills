---
{
  "card_id": "sqw.domain.architecture.migration-proof",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.domain.architecture.migration-proof",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "domain-architecture-migration-proof"
  ],
  "max_bytes": 8192
}
---
# Architecture Migration Proof

## Decision this card owns
Define and prove ownership migration, coexistence, rollback, temporary-path retirement, and caller-visible locality for a selected architecture.

## Use when
- A selected module/dependency design cannot land atomically or creates temporary adapters, dual paths, caller moves, or rollback obligations.

## Do not use when
- No structural migration is required or architecture selection remains unresolved.

## Required inputs
- `workflow-intake`; selected design/contracts, caller/consumer and generated/config/docs inventory, authoritative policy owner, coexistence needs, last compatible state, rollback constraints, and proof gates.

## Procedure
1. Characterize the highest stable owned interface, material errors/lifecycle, and existing locality before moving behavior.
2. Make target owner/direction explicit; for wide changes use expand→migrate bounded callers→contract only after remaining consumers are absent.
3. Preserve one authoritative policy. If dual read/write is unavoidable, define precedence, divergence detection, reconciliation, compatibility window, and rollback.
4. Update callers, tests, configuration, generated artifacts, observability, docs, and dormant surfaces encoding the old boundary.
5. Give every temporary adapter an owner, expiry/removal condition, and proof; test retirement follows lifecycle authority rather than architecture convenience.
6. Prove representative callers/errors/lifecycle, dependency/layering checks, distribution-test locality, stale-consumer scan, and affected public/security/performance evidence.
7. Record last compatible state and semantic restoration path; do not use destructive version-control rollback or silently promote exploratory code.

## Output contract
- Migration phases/callers, policy/coexistence contract, per-slice proof, temporary-path ledger, stale-surface scan, locality/distribution result, rollback boundary, final removal gate, blockers and residual uncertainty.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at executable migration/rollback/removal proof; passing compilation, diagrams, mocks, or moved files alone are insufficient.
