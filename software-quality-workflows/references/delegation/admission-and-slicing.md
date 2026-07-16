---
{
  "card_id": "sqw.delegation.admission-and-slicing",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "delegation_authority",
    "workflow_mode",
    "frozen_scope_manifest",
    "candidate_work_frontier",
    "host_capability_projection"
  ],
  "produces": [
    "delegation_admission_decision",
    "bounded_slice_manifests"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "delegation-to-candidate-worker",
      "to_card_id": "sqw.delegation.candidate-worker-contract",
      "edge_mode": "hard",
      "hard_predicate_id": "isolated-write-slice-admitted",
      "missing_decision": "Admitted isolated write slice lacks its worker contract",
      "required_evidence": "Write/resource sets, authority, source/scope identity, verifier",
      "evict_when": "Candidate-worker contract recorded"
    },
    {
      "edge_id": "delegation-to-read-only-evidence",
      "to_card_id": "sqw.delegation.read-only-evidence-contract",
      "edge_mode": "hard",
      "hard_predicate_id": "read-only-slice-admitted",
      "missing_decision": "Admitted read slice lacks its evidence contract",
      "required_evidence": "Read question, coverage, source/scope identity, no-write authority",
      "evict_when": "Read-only evidence contract recorded"
    }
  ]
}
---
# Delegation Admission and Slicing

## Decision this card owns
Decide whether delegation has net value and admit non-conflicting revision-bound read or isolated-write slices.

## Use when
- M2/M3 execution or an explicit read-only fan-out has independent slices and the host exposes usable delegation.

## Do not use when
- Work is small, shares mutable state/owner seams, has unresolved intent/control flow, is serial, or delegation is unauthorized/unavailable.

## Required inputs
- Authority, mode, frozen revision/scope, frontier/invariants, dependencies, read/write/resource sets, risk/proof needs, and live host capabilities.

## Procedure
1. Compare reliability/latency/separation benefit with capsule, coordination, validation, and reconciliation cost; controller-local is valid.
2. Reject slices with unresolved control/data dependencies, overlapping writes/resources, hidden shared mutable state, unfrozen shared schema, or ambiguous acceptance criteria.
3. Bind slices to one source/scope/state identity and declare objective, completion, dependencies, sets, side-effect ceiling, protections, verifier, and false-green risk.
4. Keep dependent/shared-writer slices serial. Permit concurrent writes only to isolated candidate artifacts or disjoint paths with an explicit controller integration path.
5. Resolve user decisions before admission; a worker cannot expand authority, ask on behalf of the controller, publish, or choose canonical outcomes.
6. Confirm the live host operation/schema and depth/count limits. Do not invent tool names, parameters, child capabilities, or background-completion semantics.
7. Classify admitted slices as `read_only` or `isolated_write`; activate only the matching edge and record every rejection/controller-local reason.

## Output contract
- Status/rationale; source/scope/state identity; slice manifests; dependency order; authority/protection ceilings; verifier/fan-in needs; capability limits; blocker|null.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `delegation-to-candidate-worker` | Admitted isolated write slice lacks its worker contract | Write/resource sets, authority, source/scope identity, verifier | `sqw.delegation.candidate-worker-contract` | Candidate-worker contract recorded |
| `delegation-to-read-only-evidence` | Admitted read slice lacks its evidence contract | Read question, coverage, source/scope identity, no-write authority | `sqw.delegation.read-only-evidence-contract` | Read-only evidence contract recorded |

## Stop
Stop after admission/slicing. Do not dispatch, implement, review, integrate, or treat availability as authority.
