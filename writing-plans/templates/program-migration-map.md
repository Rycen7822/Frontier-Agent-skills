# Program/Migration Projection v3: {{ destination }}

- Plan ID: `{{ plan_id }}`
- State binding: `{{ state_version }} / {{ content_hash }}`
- Source identity: `{{ kind }} / {{ identity_hash }}`
- Planning scope binding: `{{ binding_id }}`
- Completion/card binding: `{{ completion_id }} / {{ card_instance_id }}`

The canonical owner is the locked Program state identified above. This Markdown is a disposable projection and never carries a state path, projection locator, authority claim, or recovery bookkeeping.

## Goal and non-goals

{{ canonical goal and explicit exclusions }}

## Global invariants and selected decisions

{{ ordered typed references that affect the current frontier }}

## Current frontier

{{ complete current frontier; do not truncate mandatory nodes }}

## Blocked nodes and unresolved gaps

{{ deterministic blockers and evidence gaps only }}

## Rollout, rollback, verification, and completion

{{ typed rollback, required evidence, false-green risks, residual uncertainty, and completion state }}

Remote milestones remain references until they enter the current frontier.
