---
{
  "card_id": "sqw.safety.evidence-coverage-and-freshness",
  "card_version": 1,
  "kind": "safety",
  "consumes": [
    "scope_decision",
    "source_identity",
    "evidence_inventory",
    "coverage_projection"
  ],
  "produces": [
    "coverage_ledger",
    "freshness_decision"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Evidence Coverage and Freshness

## Decision this card owns
Decide what was actually covered and whether evidence remains fresh enough to support the next claim or action.

## Use when
- Scope is multi-file, source or environment may drift, results are truncated or sampled, or review/fix/publication depends on prior evidence.

## Do not use when
- A bounded fresh proof covers the entire declared M0 seam and no identity changed since observation.

## Required inputs
- Scope/source identity, per-path snapshot or artifact refs, read/search/test outputs, truncation and sampling metadata, environment identity, and current revision/scope observations.

## Procedure
1. Record every scoped item as `full`, `sampled`, or `not_reviewed`; a scan hit begins as `scan_candidate` and becomes a finding only after contextual review.
2. Treat unread, omitted, failed, or truncated material as partial coverage. State the sampling or output boundary explicitly.
3. Bind findings, fixes, and proof to source revision, scope identity, relevant environment, and artifact hashes.
4. Re-observe revision and scope at review, fix, resume, and completion boundaries; same-revision dirty or untracked drift still invalidates affected evidence.
5. If a changed artifact can affect a result, reread the affected source and rerun the smallest owning proof before reusing the claim.
6. Select an external skill or connector only after verifying availability, request-mode compatibility, authority, revision model, and proof contract. Missing capability never weakens a gate.

## Output contract
- `coverage_ledger`: item identity, snapshot, coverage status, sampling/truncation boundary, and evidence refs.
- `freshness_decision`: `fresh`, `stale_local`, `stale_global`, or `insufficient`, with changed identities and required repair proof.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop a full-coverage, completion, approval, or publication claim when any mandatory item is unread, stale, truncated, sampled without disclosure, or bound to a different source/scope identity.
