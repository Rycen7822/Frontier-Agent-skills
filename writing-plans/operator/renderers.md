# Renderer operations

All renderer functions validate their complete typed input before producing bytes. Public file writes belong only to `scripts/card_cycle.py`; `render_plan_profile.py` and `render_context_capsule.py` expose no free state path, runtime JSON path, output path, or metadata path CLI.

Brief renders directly from its validated completion payload to an immutable file in the explicit projection root. Standalone Handoff first materializes one typed v3 boundary artifact; its Markdown is a projection of that artifact and never exposes a Program state path. Program output and context render only from the locked current owner.

When an explicit Brief/Handoff delivery root is inside the bound source, the card cycle runs a complete pre-publication and post-publication source fence, accepts only its deterministic content-addressed target, and records a `plan-output` transition in the receipt. Exact replay reconstructs the same transition without replacing the final; post-publication uncertainty returns `E_POST_PUBLISH_UNVERIFIED` and leaves the final available for verification.

Program uses `projections/program.md`; context uses `projections/context-capsule.md`. Their only temps are the matching `.tmp` siblings. Headers bind plan ID, current state version/hash, completion where applicable, card/manifest identity, and renderer contract. State stores neither projection locator nor projection hash. Removing a final is valid; the same current state rebuilds identical bytes. A request bound to an older state hash is stale.

Program output has an exact 8,192-byte ceiling. Mandatory current-frontier content must fit completely; 8,193 bytes returns `E_PROJECTION_BUDGET` before state or projection writes. It never truncates mandatory identity, decision, invariant, scope, source, frontier, verifier, or rollback content.

Context accepts 500–8,192 bytes and one strict runtime projection. Mandatory selection order is identity/card binding, goal/current node, decisions, blocking gaps, policy claims, global invariants, approvals/edges, verifier/retry, non-goals, then runtime bytes. Optional node inputs, outputs, verifier evidence, and direct dependencies use ordered first-fit. Missing local references fail; external references become on-demand. Mandatory, included, omitted, and on-demand groups remain disjoint and ordered.

Context completion validates candidate state and projection in memory, commits the one semantic transition, then publishes the fixed projection. Exact retry after state commit reconstructs from `last_transition.inline_render_completion`; runtime input is not retransmitted. Rerender is read-only with respect to state. Context rebuild is allowed only while that context completion is the current last transition; later state returns `E_CONTEXT_NOT_CURRENT` and preserves stale bytes.

Renderer contract hashes are canonical hashes of sorted package-support-map path/hash records for the renderer and canonical state schema. `render()` invokes `select_context_items()` exactly once. Closed or unrelated future nodes never enter included, omitted, or on-demand groups; unresolved local refs fail, while explicit external refs enter on-demand without being read.

Typed Handoff 3.0 carries producer completion, source and planning-scope bindings, owner seams, exact requirement refs, ordered slices, rollback, and the SQW receiver entry. It records authority requirements but never grants authority. Its Markdown renderer consumes only the validated immutable artifact and emits no local source, owner-state, artifact-root, or projection-root path.
