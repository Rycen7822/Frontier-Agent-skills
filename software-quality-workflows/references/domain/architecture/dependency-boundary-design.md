---
{
  "card_id": "sqw.domain.architecture.dependency-boundary-design",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "module_boundary_contract",
    "dependency_graph_and_owners",
    "boundary_failure_semantics"
  ],
  "produces": [
    "dependency_boundary_contract"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "dependency-to-alternatives",
      "to_card_id": "sqw.domain.architecture.alternative-decision",
      "edge_mode": "semantic",
      "missing_decision": "Dependency contract is known but structural choice remains",
      "required_evidence": "Classified dependencies, direction constraints, and viable structures",
      "evict_when": "Alternative decision recorded"
    }
  ]
}
---
# Dependency-Boundary Design

## Decision this card owns
Classify dependencies and set direction, ownership, construction, lifecycle, and failure contracts without ritual inversion.

## Use when
- Module design leaves dependency ownership/direction, a cycle, provider/trust/process boundary, or selection policy unresolved.

## Do not use when
- A same-owner stable implementation detail has no boundary knowledge or independent change pressure.

## Required inputs
- Module contract, current dependency/cycle graph, policy owners, volatility evidence, consumers, trust/process/lifecycle/error semantics, and public-consumption status.

## Procedure
1. Classify each dependency: same-owner stable detail; independently changing policy; external provider/platform; trust boundary; process/network/queue/persistence; or cross-package/team/plugin/external consumer.
2. Keep stable same-owner details concrete/private. Isolate the smallest stable policy for observed independent change; adapt external providers only to hide material provider shape/failure/lifecycle.
3. Put parsing/validation/authorization at trust crossings and make timeout/cancel/retry/idempotency/partial/recovery/ownership explicit at process boundaries.
4. Route cross-owner consumers as public/semi-public contracts; dependency direction follows policy ownership/volatility, not a rule that each concrete type needs an interface.
5. Centralize selection/defaults/construction; reject injection that merely distributes construction or exposes vendor/test controls.
6. Record direction, owner, lifecycle/failure contract, cycle resolution, construction point, public/trust implications, reclassification trigger, and remaining structural choice.

## Output contract
- Classified dependency map; allowed directions; policy/construction/lifecycle/failure owners; cycle resolution; boundary/public escalations; rejected ritual abstractions; `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `dependency-to-alternatives` | Dependency contract is known but structural choice remains | Classified dependencies, direction constraints, and viable structures | `sqw.domain.architecture.alternative-decision` | Alternative decision recorded |

## Stop
Stop at the dependency contract or the one unresolved structural decision; do not implement it here.
