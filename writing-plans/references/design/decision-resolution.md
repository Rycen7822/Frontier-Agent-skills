---
{
  "card_id": "wp.design.decision-resolution",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "wp.select.design.decision-resolution",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "design-decision"
  ],
  "max_bytes": 8192
}
---
# Design Decision Resolution

## Decision this card owns
Resolve the smallest evidence-backed design, compression, and readiness decision without inventing seams or expanding unresolved intent into implementation detail.

## Use when
- A plan may alter ownership, dependencies, shared/public contracts, security/state boundaries, migration shape, or another costly-to-reverse choice.

## Do not use when
- Root cause or intended outcome is unresolved; return a typed diagnosis/intent handoff.
- The only gap is one falsifiable feasibility fact; request the disposable-spike decision.

## Required inputs
- Outcome/non-goals, source/scope/authority identity, controlling instructions, current owners/contracts/tests/config/history where relevant, reversibility and risk evidence, alternatives/counterevidence, proof/false-green, migration, and rollback.

## Procedure

### 1. Select depth
1. Use D0 only for a mechanical local change with a clear owner/contract and no new seam; record one sentence.
2. Use D1 for a plausible helper, adapter, cache, mode, schema, dependency, or owner decision; require bounded fact, decision, compression, proof, and rollback rows.
3. Use D2 for public contracts, cross-module migration, security/shared state, hard-to-reverse architecture, or materially different viable families; require scoped alternatives, counterevidence, migration/rollback, and an exclusion rationale.
4. Never infer depth from file or line count. Bind it to inspected source identity and explicit missing evidence.

### 2. Build the evidence and decision ledger
1. Record stable fact rows with current contract, exact anchor, owner seam, freshness, and change risk.
2. Record one decision row per material owner/seam/contract/proof move with baseline refs, intent, touched seams, expected impact, rollback, and discriminating proof.
3. Record compression candidates against baseline rows; do not turn every file or action into a decision.
4. Preserve assumptions, counterevidence, unresolved fog, source gaps, and false-green risks. Reopen exact pointers when freshness matters; expose evidence and rationale, never private reasoning transcripts.

### 3. Compare and compress alternatives
1. Compare status quo and materially different families by semantic fit, owner/dependency shape, blast radius, reversibility, proof, compatibility, migration, and long-term burden.
2. For affected prior design choose exactly `keep`, `rewrite`, `split`, `merge`, `defer`, `delete`, or `replace` and prove why the result is not avoidable append-only code.
3. Every proposed file, abstraction, dependency, API, cache, or mode must explain why the existing owning seam cannot be reused, changed, merged, or removed.
4. Reject cosmetic variants. Add another design round only when new evidence changes a decision, proof, rollback, or blast radius.
5. Select one family or return bounded underdetermination with rejected families and the smallest empirical boundary.

### 4. Apply the planning gate
1. Confirm depth, source freshness, owner/contract coverage, counterevidence, compression, proof/false-green, migration/rollback, effect authority, and approval.
2. Reject stale sources, unowned seams, avoidable append-only design, missing discriminators, or prose-expanded gaps.
3. Emit one disposition: `ready_for_slicing`, `spike_required`, `sqw_diagnosis`, `sqw_intent`, `source_required`, `approval_blocked`, `spec_underdetermined`, or `spec_unsat`.

## Output contract
- One `design-decision` containing depth/source identity, fact/decision/compression/proof rows, selected and rejected alternatives, consequences, migration/rollback, disposition, unresolved fog, evidence refs, and blocker.
- When another decision is required, emit only a schema-valid decision request and return to Router.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at one evidence-backed disposition or the smallest typed evidence/intent/authority blocker; never select a design merely to keep planning moving.
