---
{
  "card_id": "sqw.entry.read-only-audit",
  "card_version": 1,
  "kind": "entry",
  "consumes": [
    "audit_question",
    "scope_projection",
    "source_identity"
  ],
  "produces": [
    "coverage_contract",
    "audit_result"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "audit-to-read-only-delegation",
      "to_card_id": "sqw.delegation.read-only-evidence-contract",
      "edge_mode": "hard",
      "hard_predicate_id": "independent-read-slices-admitted",
      "missing_decision": "Independent read-only slices need bounded contracts",
      "required_evidence": "Scope partition and delegation authority",
      "evict_when": "Read-only evidence contracts are emitted"
    }
  ]
}
---
# Read-Only Audit

## Decision this card owns
Fix the audit scope, coverage semantics, and evidence boundary while preserving read-only authority.

## Use when
- The requested outcome is findings, review, explanation, status, or evidence rather than edits.

## Do not use when
- The user authorized implementation, or a diagnostic probe with local disposable state is the primary task.

## Required inputs
- Audit question, immutable source identity, architecture/product surfaces, runtime/deployment/config context, scope and exclusions, required coverage, and available evidence.

## Procedure
1. Freeze the reviewed source, revision, audit question, scope projection, exclusions, and read-only authority.
2. Build a coverage matrix for relevant modules, public interfaces, data/state flows, runtime/config/deployment paths, integrations, security/trust boundaries, failure handling, and tests/docs; mark each full, sampled, or not reviewed.
3. Reconstruct architecture from executable sources, configuration, deployment definitions, tests, and decisions/history. Treat prose diagrams and scanner matches as claims or candidates until corroborated.
4. Trace representative end-to-end flows and seams, checking ownership, dependency direction, invariants, lifecycle, failure propagation, recovery, and observability against the stated architecture.
5. Bind each finding to revision-stable evidence, affected surface, severity/impact, confidence, and violated contract; separate verified defects from risks, questions, and non-blocking observations.
6. Preserve read-only authority across every reviewer slice and prevent diagnostics, formatting, generated files, or staging from mutating the target.
7. Delegate only independent admitted slices with explicit coverage/evidence contracts, then reconcile overlaps and unreviewed gaps before reporting.

## Output contract
- `scope_hash`, `source_identity`, `architecture_map`, `coverage`, `findings`, `risks_questions_observations`, `evidence_refs`, `not_reviewed`, `next_edge_id|null`, and `residual_risk`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `audit-to-read-only-delegation` | Independent read-only slices need bounded contracts | Scope partition and delegation authority | `sqw.delegation.read-only-evidence-contract` | Read-only evidence contracts are emitted |

## Stop
Stop with an evidence-bound result; never convert the audit into edits.
