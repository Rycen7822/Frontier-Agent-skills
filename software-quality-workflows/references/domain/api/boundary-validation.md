---
{
  "card_id": "sqw.domain.api.boundary-validation",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "public_contract",
    "boundary_inputs",
    "compatibility_class"
  ],
  "produces": [
    "boundary_oracles",
    "negative_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Public Boundary Validation

## Decision this card owns
Define consumer-visible positive, negative, compatibility, and serialization proof at the real public boundary.

## Use when
- Boundary validation or compatibility oracles remain unresolved.

## Do not use when
- Only a private helper changes and public behavior is already protected.

## Required inputs
- Contract schema, valid/invalid examples, errors, version behavior, and public execution path.

## Procedure
1. Select representative valid/invalid inputs; parse and normalize before business logic and bound material collections, strings, recursion, files, and pagination.
2. Fix outputs/errors/retryability/partial success; keep authorization outside user-forgeable payload fields.
3. Add independent compatibility/fixed-fixture expectations and apply the published rule for unknown control fields.
4. Exercise serialization, defaults, versions, idempotency, ordering, and third-party/model/browser/tool output validation before data use or rendering.
5. Run proof through the real API, protocol, CLI, generated or installed artifact; use synthetic examples without credentials/private identifiers/sensitive payloads.
6. Record source/version identity, size/resource boundaries, consumer-visible failure classes, and residual untested boundaries.

## Output contract
- `positive_oracles`, `negative_oracles`, `compatibility_oracles`, `public_surface_gate`, `evidence_refs`, and `gaps`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when the public boundary has independent, consumer-visible proof.
