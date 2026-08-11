# Intent Discovery and Freeze

## Purpose
Resolve material outcome semantics and freeze one authoritative implementation-plannable specification when durability is warranted.

## Use when
- An intent intake contains material gaps, alternative outcomes, or a non-trivial durable specification need.

## Do not use when
- Only implementation technique is undecided, cause is unknown, or routine defined work needs no durable spec.

## Required inputs
- task context; authoritative request/repository/session facts; scenarios, public behavior, constraints, reversibility/compatibility/risk; architecture/flows/interfaces/failures; proof/rollout; and documentation/approval authority.

## Procedure
1. List only decisions that change observable outcomes or irreversible commitments. Retrieve direct source facts before asking and accept defaults only when explicit, safe, reversible, and low impact.
2. Represent deferred requirements with stable ID, owner location, allowed value shape, authoritative default, constraints/source/validation, and `open|resolved|blocked`; remove or block every placeholder, contradiction, and invented acceptance criterion.
3. Ask at most one material question at a time. Mark conflicting/external decisions without guessing; a visual probe is allowed only for an inherently spatial choice and does not authorize runtime tooling.
4. Compare status quo and two or three materially different outcomes when evidence supports them across user value, ownership, compatibility/migration, operations, failures, safety, reversibility, proof, and rollback. Reject cosmetic variants.
5. Select one outcome within authority or emit underdetermination with the minimum missing fact; record rejected alternatives, distinguishing evidence, assumptions, consequences, proof/rollback, and required external approval.
6. Scale the spec to real decisions: outcome/scope/non-goals; component owners; data/control/state/effects/lifecycle; compatibility/errors/cancel/cleanup; invalid/partial/retry/recovery; proof/false-green; migration/observability/rollout/rollback/removal.
7. Review the complete spec for decisive behavior, consistent errors/tests/rollout, one-plan scope, YAGNI, and no speculative flexibility. Use independent review only when proportionate.
8. Persist only when warranted at the project convention without inferring commit/publication authority; otherwise use a stable inline identity. Decompose if one plan cannot credibly implement it.
9. Emit the authoritative identity plus exact handoff to Writing Plans or the applicable non-implementation owner; do not implement or plan slices here.

## Required result
- One `intent-discovery-and-freeze` with resolved facts/defaults, requirement blocks, selected/rejected outcomes, underdetermination or approval blocker, a `spec_ref` containing repository-relative path plus source revision or stable inline requirement IDs, component/flow/interface/failure/proof/rollout contract, assumptions/exclusions, and next-owner handoff. The `spec_ref` carries the frozen identity.

## Stop
Stop at an internally reviewed authoritative spec or typed blocker; never infer approval, implement, or duplicate planning.
