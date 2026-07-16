---
{
  "card_id": "sqw.intent.spec-freeze-handoff",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "resolved_intent_and_requirements",
    "selected_outcome_or_constrained_design",
    "specification_authority"
  ],
  "produces": [
    "frozen_specification_handoff"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Specification Freeze and Handoff

## Decision this card owns
Form, proportionally validate, freeze, and hand off one authoritative implementation-plannable specification without duplicating planning.

## Use when
- Intent/alternatives are resolved and non-trivial behavior, durable handoff, context survival, or an explicitly requested spec requires a stable design contract.

## Do not use when
- Material outcome decisions remain open, work is routine/fully specified, or no implementation/reusable specification follows.

## Required inputs
- Normalized outcome/scope/success/non-goals, selected design and rejected alternatives, resolved requirement blocks, architecture/components/flow/interfaces/failures, quality/rollout constraints, authority/approval status, visual-probe result if used, and project documentation convention.

## Procedure
1. Scale detail to real decisions and cover outcome/scope; component owners; data/control/state/side effects/lifecycle; caller-facing compatibility/error/cancel/cleanup; invalid/partial/retry/recovery; proof/false-green; migration/observability/rollback/removal.
2. Keep requirement IDs stable and remove or explicitly block every placeholder/TODO/contradiction; planning may reference but never invent missing acceptance criteria.
3. Apply approval only when explicitly requested or a material preference/costly external/hard-to-reverse choice cannot be inferred safely; clear low-risk authority does not require ritual permission.
4. If a visual probe was selected, consume only the bounded user decision/evidence; operator server/events/artifacts never enter the model card or specification as runtime instructions.
5. Write durably only when warranted, at the project convention, without assuming commit authority. Review the complete spec inline for decisive behavior, consistent errors/tests/rollout, one-plan scope, YAGNI, and no speculative flexibility; use the bounded [independent spec-review prompt](../../templates/design-discovery-spec-reviewer-prompt.md) when a separate reviewer is justified.
6. Decompose if one plan cannot credibly implement it. Emit the authoritative path/hash or inline identity, unresolved external decisions, assumptions, exclusions, and exact handoff to `writing-plans` or the applicable non-implementation owner.

## Output contract
- Frozen spec identity/revision/hash; outcome/scope/non-goals; stable requirements and selected/rejected design; component/flow/interface/failure/proof/rollout contract; approval/visual evidence; assumptions/external blockers; next-owner handoff.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at an internally reviewed authoritative spec or typed blocker; do not implement, plan slices, commit, or infer approval.
