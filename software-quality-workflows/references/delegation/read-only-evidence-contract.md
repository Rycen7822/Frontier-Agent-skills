---
{
  "card_id": "sqw.delegation.read-only-evidence-contract",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "scope_partition",
    "source_identity",
    "delegation_authority"
  ],
  "produces": [
    "read_only_slice_contracts",
    "evidence_envelope_contract"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Read-Only Evidence Delegation

## Decision this card owns
Define independent read-only slices and the exact evidence envelope required for controller fan-in.

## Use when
- Two or more independent read slices are admitted and delegation is authorized.

## Do not use when
- Any worker needs write authority, slices overlap materially, or delegation has no net value.

## Required inputs
- Frozen source/scope identity, disjoint slice definitions, shared questions, and result schema.

## Procedure
1. Give each reviewer one non-overlapping evidence question and path/surface scope.
2. Bind every slice to the same source and scope snapshot.
3. Forbid writes, approvals, publication, and scope expansion.
4. Require findings, coverage, evidence references, and not-reviewed surfaces.
5. Reject stale, overlapping, malformed, or authority-expanding results.
6. Fan in only validated envelopes; do not concatenate reviewer context.

## Output contract
- `slice_contracts`, `shared_identity`, `result_schema_id`, `fan_in_rule`, and `blocker|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after bounded slice contracts exist; the controller owns execution and integration.
