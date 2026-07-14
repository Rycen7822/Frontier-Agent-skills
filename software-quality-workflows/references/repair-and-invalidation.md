# Repair and Invalidation

This reference owns workflow dependency invalidation and repair-scope semantics. It does not modify plan decisions or conceal changed assumptions behind local retries.

## Propagation

Start from explicit changed refs and traverse outgoing `data`, `evidence`, `invariant`, `effect`, `resource`, and `control` edges. An edge with `sensitivity.fields` is traversed only when declared changed fields intersect. Without field detail, propagation is conservative. Explicit edge semantics take precedence over generic node input/dependency inference.

Return affected/invalidated IDs, preserved IDs, new frontier, required rechecks, and escalation reasons. Do not mutate canonical state unless the caller explicitly requests a validated state projection.

## Local repair

Local repair is allowed when affected state is bounded to one modeled owner seam, preserved dependencies remain fresh/equivalent, side effects are known/reversible, and retry budget plus approval remain valid. Unrelated branches remain preserved and must have a precision fixture.

## Mandatory escalation

Use `global_or_parent_replan` when any of these changes:

- goal, non-goal, user authority, security, or approval boundary;
- global invariant or root-cause decision;
- source drift across multiple owner seams;
- hidden external state or an uncertain rollback after observed effects;
- failure-locality evidence is insufficient;
- preserved nodes may have unmodeled resource coupling;
- local repair fails beyond its budget;
- plan content hash or canonical objective changes.

Escalation produces a plan-change proposal or blocked state. It never silently rewrites plan state, broadens scope, grants approval, or retries a non-idempotent action.

Resume begins by reconciling source revision, scope hash, plan hash, evidence content hashes, locks/leases, event sequence, state version, and background work. Any drift remains visible in the repair report.
