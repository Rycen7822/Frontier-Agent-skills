# Workflow Artifact, Evidence, Approval, Retry, and Lock Contract

This operator reference owns durable identity and machine-validation details that must not consume model context.

## Identity and input limits

Namespaces are `wf-*`, `N-*`, `evt-*`, `RUN-*`, `EV-*`, `VER-*`, `I-*`, `AP-*`, `LOCK-*`, `X-*`, and `ERR-*`. Cross-artifact references use `<kind>:<artifact>#<local-id>`; bare IDs are local only.

Reject unknown fields, duplicate JSON keys, inputs over 2 MiB, nesting over 40, collections over 1,000 items, and edge collections over 2,000 items. Canonical state hashes use sorted compact JSON with `state_hash` omitted.

## Evidence records

Evidence records carry:

- versioned `schema_id` and claim;
- producer/run and source revision/scope hash;
- original exit code and duration;
- classification, coverage, freshness, and limitations;
- content hash and controlled artifact pointer.

Node input and output contracts must match observed artifact schemas before readiness or completion. Verifier `evidence_sensitivity` declares which evidence fields invalidate its claim. `baseline_failure` is distinct from `product_failure` and cannot satisfy a product-regression verifier.

## Approval and side effects

External or destructive nodes require an active scoped approval whose authority ceiling covers the exact effect. Approval never widens path, source, or publication scope implicitly. Revocation blocks new effects and triggers controller reconciliation.

## Retry

Non-idempotent retries require an idempotency key or manual reconciliation proving the prior attempt's effects. Retry counters, backoff, budgets, and observed external identity are controller data. A worker cannot approve its own retry or erase prior evidence.

## Locks

Locks contain resource, owner, acquisition/lease times, and state version. Two live owners cannot hold the same resource. Expiry is not proof of cleanup: reconciliation must observe the resource before reassignment.

## Model projection boundary

Models receive only current-node invariant/effect/authority/evidence projections and immutable artifact refs. They do not receive the full event log, retry table, lock catalog, schema enum, stable error catalog, or canonical hashing procedure.
