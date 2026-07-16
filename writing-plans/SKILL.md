---
name: writing-plans
description: Use when an authorized software change needs a durable implementation plan, a cross-context handoff, or an autonomous-closure request must be compiled into a frozen intended-state contract. Do not use for routine Direct edits, unresolved diagnosis, or actual execution, verification, sign-off, publication, or workflow closure.
license: MIT
metadata:
  version: 4.0.0
  author: Hermes Agent (adapted from obra/superpowers)
  hosts: [codex, hermes-agent]
  hermes:
    tags: [planning, design, implementation, closure-contract, documentation]
    category: software-development
    related_skills: [software-quality-workflows]
---

# Writing Plans

## Owner boundary

Own the lightest durable intended-state plan preserving scope, constraints, decisions, order, recovery, and proof, plus a frozen Closure Contract when eligible. Compile what must become true; never claim actual execution truth.

Diagnosis, code edits, evidence acceptance, execution state, sign-off, publication, and closure belong to `software-quality-workflows` (SQW). Direct work remains planless unless a durable plan is requested. Long non-software corpora belong to `long-document-segmented-writing`.

The contract is identical in Codex and Hermes Agent. Resolve bundled paths from this skill root and use equivalent host capabilities; plan UI and delegation are optional. Plans index authoritative sources and stable IDs rather than copying the repository.

## Route

Observe facts; do not infer nullable safety facts as false. Run `scripts/assess_plan_mode.py` with input conforming to `schemas/plan-route-facts.schema.json`, then validate the exact result against `schemas/plan-route-result.schema.json` and the live card manifest.

Fixed precedence: terminal Admission stops; unknown root cause or material intent gap returns to SQW; long corpus selects its bridge; one feasibility uncertainty selects spike; `CLOSURE_ELIGIBLE` selects Program + `autonomous_closure` + `wp.closure.compile`; public contract/migration/resume/external effects select Program; cross-context/durable/multi-slice/executable handoff selects Handoff; an explicit remaining request selects Brief; otherwise return Direct.

Accept exactly zero or one `primary_card` transport reference from the route. Never choose a card by filename, memory, or broad similarity.

## Profile selection

- Brief (`wp.profiles.brief`): one same-session outcome; no graph, state, or Closure Contract.
- Handoff (`wp.profiles.handoff`): ordered slices, frontier, boundaries, gaps, proof, rollback, and standard handoff.
- Program (`wp.profiles.program`): multi-owner/public/migration/resume/closure graph. `schemas/plan-state.schema.json` is truth; render only frontier-relevant decisions/invariants within 8,192 bytes.

Closure is Program-only. Move upward if a lighter profile erases migration, authority, recovery, or verifier dependencies.

## Closure boundary

Use closure only after an independent Admission says `CLOSURE_ELIGIBLE`. Start at `wp.closure.compile`, resolve its four section decisions one at a time, and validate the complete draft with `scripts/validate_closure_contract.py` against `schemas/closure-contract.schema.json`.

Freeze with `scripts/freeze_closure_contract.py` to a new immutable path. Verify Admission, Authority Manifest, bundle, source, scope, policy/card manifests, authority hash, and ceiling. Freeze is atomic/no-overwrite; supersede by epoch. Never bind plans, future candidates, runtime verdicts, raw logs, or publication claims.

Build Program state only after freeze. It binds the exact contract ID/epoch/hash and the same source, scope, bundle, policy, card-manifest, and authority identities. Validate through `scripts/validate_plan_state.py`. Generated profiles and capsules are disposable projections: capsules bind exact card/projection hashes, have an effective 8,192-byte ceiling, and fail closed if mandatory content does not fit.

## One-card protocol

Load the selected card, verify it against `registries/reference-cards.manifest.json`, and make only its named decision. Follow at most one evidence-supported neighbor. Emit its artifact or typed blocker, then reroute. Do not preload siblings, operator manuals, or directories.

Cards own model decisions. Schemas/scripts own machine truth. `operator/` owns runtime mechanics and is never part of the model card graph. Templates are projections, not policy owners. Record policy claims as stable `policy_id + bundle_version + policy_hash`, never as a Markdown path.

If context is approaching its limit, persist canonical state and render a node capsule with `scripts/render_context_capsule.py`; do not write a prose substitute. Manifest/card drift invalidates only such generated context, while source/scope/contract/root-policy drift requires wider replanning.

## SQW handoff

Writing Plans hands off intended state; SQW independently owns execution and proof. Emit exactly `schemas/plan-execution-handoff.schema.json`:

- standard execution: plan identity, source revision, authority manifest, scope, current frontier, required SQW policy IDs, and blockers; all Admission/Closure Contract fields are null;
- autonomous closure: Program plus non-null Admission and frozen Closure Contract refs/hashes under the same bundle/source/scope/authority boundary.

Do not include internal route-card IDs in the handoff. Point to canonical plan state instead of embedding historical nodes. SQW may reject stale, under-authorized, unverifiable, or conflicting plans.

## Completion

Standard writing is complete when the requested artifact is internally consistent, source-bound, proportionate, schema-valid where applicable, and handed off with explicit gaps.

Autonomous writing is complete exactly at `contract_frozen + plan_validated + handoff_emitted`. This does not mean implementation, sign-off, publication, or workflow closure. Report all four as unproven until SQW supplies fresh owner-qualified evidence.
