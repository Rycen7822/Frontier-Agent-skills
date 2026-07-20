---
name: writing-plans
description: Use when an authorized software change needs a durable implementation plan, cross-context handoff, migration plan, or evidence-backed design decision. Do not use for routine direct edits, unresolved diagnosis, or actual execution, verification, sign-off, or publication.
license: MIT
metadata:
  version: 6.0.0
  author: Hermes Agent (adapted from obra/superpowers)
  hosts: [codex, hermes-agent]
  hermes:
    tags: [planning, design, implementation, migration, documentation]
    category: software-development
    related_skills: [software-quality-workflows]
---

# Writing Plans

## Owner boundary

Own the lightest durable intended-state plan preserving scope, constraints, decisions, order, recovery, and proof. Compile what must become true; never claim actual execution truth.

Diagnosis, code edits, evidence acceptance, execution state, sign-off, and publication belong to `software-quality-workflows` (SQW). Direct work remains planless unless a durable plan is requested. Long non-software corpora belong to `long-document-segmented-writing`.

The contract is identical in Codex and Hermes Agent. Resolve bundled paths from this skill root and use equivalent host capabilities; plan UI and delegation are optional. Plans index authoritative sources and stable IDs rather than copying the repository.

## Route

Observe facts; do not infer missing safety facts. Run `scripts/assess_plan_mode.py` with input conforming to `schemas/plan-route-facts.schema.json`, then validate the exact result against `schemas/plan-route-result.schema.json`, `registries/decision-card-map.json`, and the live card manifest.

Fixed precedence: unknown root cause or material intent gap returns to SQW; long corpus selects its bridge; one feasibility uncertainty selects spike; public contract, migration, resume, external effect, or multiple strategy families select Program; cross-context, durable, multi-slice, or copy-paste execution selects Handoff; an explicit plan request selects Brief; otherwise return Direct.

Accept exactly zero or one `primary_card` transport reference. Pending decisions enter the queue only through a schema-valid `decision_request` produced by the just-completed mapped card. Unknown, duplicate, completed, producer-mismatched, or prerequisite-missing decisions block with a typed reason. Never choose a card by filename, memory, cross-card link, or broad similarity.

## Profile selection

- Brief (`wp.profiles.brief`): one same-session outcome; no durable graph or state.
- Handoff (`wp.profiles.handoff`): ordered slices, frontier, boundaries, gaps, proof, and rollback.
- Program (`wp.profiles.program`): multi-owner, public-contract, migration, or resumable program graph. `schemas/plan-state.schema.json` is truth; render only frontier-relevant decisions and invariants within 8,192 bytes.

Use the lightest profile that preserves migration, authority, recovery, and verifier dependencies. Validate Program state through `scripts/validate_plan_state.py`. Generated profiles and capsules are disposable projections: capsules bind exact card and projection hashes, have an effective 8,192-byte ceiling, and fail closed if mandatory content does not fit.

## One-card protocol

Load the selected card, verify its map/manifest identity, and make only its named decision. Emit only the declared artifact or typed blocker, then reroute. Do not preload siblings, operator manuals, or directories.

Use the [support map](references/package-support-map.md) only for lookup; do not preload it. Cards decide; schemas/scripts own machine truth; `operator/` non-model runtime; templates projections. Policies: `policy_id + bundle_version + policy_hash`, never paths.

If context is approaching its limit, persist canonical state and render a node capsule with `scripts/render_context_capsule.py`; do not write a prose substitute. Manifest/card drift invalidates only generated context, while source, scope, or root-policy drift requires wider replanning.

## SQW handoff

Writing Plans hands off intended state; SQW independently owns execution and proof. Emit exactly `schemas/plan-execution-handoff.schema.json`: plan identity, source revision, authority manifest, scope, current frontier, required SQW policy IDs, and unresolved blockers.

Do not include internal route-card IDs in the handoff. Point to canonical plan state instead of embedding historical nodes. SQW may reject stale, under-authorized, unverifiable, or conflicting plans.

## Completion

Writing is complete when the requested artifact is internally consistent, source-bound, proportionate, schema-valid where applicable, and handed off with explicit gaps. This does not mean implementation, sign-off, publication, or workflow completion; report those outcomes as unproven until SQW supplies fresh owner-qualified evidence.
