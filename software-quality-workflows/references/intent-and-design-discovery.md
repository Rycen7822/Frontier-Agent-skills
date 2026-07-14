# Intent and Design Discovery

Use this reference when software work starts from an underdefined idea, a materially ambiguous feature request, a product or UI concept, or an architecture choice whose intended outcome must be formed before planning. It owns collaborative intent discovery and specification formation; it is not a second software-development entrypoint.

This branch is adapted from Jesse Vincent's Superpowers brainstorming workflow under the [MIT license](design-discovery-upstream-license.txt). The original standalone workflow is narrowed here to respect the umbrella's authority, risk, and execution contracts.

## Contents

- [Owner boundaries](#owner-boundaries)
- [Activation test](#activation-test)
- [Workflow](#workflow)
- [Clarification discipline](#clarification-discipline)
- [Approach comparison](#approach-comparison)
- [Design contract](#design-contract)
- [Approval boundary](#approval-boundary)
- [Specification and handoff](#specification-and-handoff)
- [Isolation and clarity](#isolation-and-clarity)
- [Visual companion](#visual-companion)
- [Completion record](#completion-record)

## Owner boundaries

- Follow [Authority and Scope](authority-and-scope.md) for request mode, authority, risk, side effects, dirty-worktree ownership, and stop conditions.
- Use this reference to determine what should be built. Use [Architecture and Module Design](architecture-module-design.md) for internal seams and dependency shape, and [API and Interface Design](api-interface-design.md) for externally consumed contracts.
- Hand non-trivial implementation planning to `writing-plans`; do not duplicate its design-audit ledger, implementation slicing, or plan format here.
- Use [Test-Driven Development](test-driven-development.md) during implementation and [Verification Discipline](verification-discipline.md) for completion claims.
- A user-approved plan, precise acceptance criteria, a routine bugfix with established behavior, or a bounded maintenance edit does not need this branch unless intent is genuinely unresolved.

## Activation test

Load this reference when one or more of these conditions holds:

- The user asks to brainstorm, shape, explore, or specify a software idea.
- Multiple plausible outcomes would satisfy the words of the request but produce materially different products or behavior.
- Purpose, users, constraints, success criteria, or non-goals are missing and cannot be recovered from the project, direct source, or session history.
- The request combines several independent subsystems and must be decomposed before one implementation plan can be credible.
- A visual or interaction design choice needs user feedback before implementation.

Do not activate it merely because implementation involves creativity. Skip it for report-only review, diagnosis, mechanical migration, precise config changes, approved-plan execution, and ordinary fixes whose desired behavior is already evidenced.

## Workflow

1. **Explore context.** Inspect the current project structure, owning docs, relevant code/tests, recent decisions, and prior session context before asking the user to repeat information.
2. **Normalize the outcome.** Record the intended result, constraints, success criteria, non-goals, current assumptions, and unresolved decisions.
3. **Check scope.** If the request contains independent products or subsystems, propose a decomposition and select the first bounded slice.
4. **Resolve only material gaps.** Ask one question at a time when the answer would change the design; otherwise state the safe default and proceed.
5. **Compare designs.** When real alternatives exist, present two or three materially different approaches with trade-offs and a recommendation.
6. **Form the design.** Cover the outcome, architecture/components, data and control flow, interfaces, errors and recovery, security/operability where applicable, testing, rollout, and explicit exclusions.
7. **Validate proportionally.** Present the design in sections when it is complex; revise any material disagreement before freezing a spec.
8. **Write and review the spec when warranted.** Follow the project convention, run the inline review, then hand the result to `writing-plans`.

Use `todo` for a multi-step live discovery session. Do not create one task per ritual step for a tiny request; proportionality remains owned by the umbrella.

## Clarification discipline

- Ask one question at a time so each answer can update the working design.
- Prefer concise selectable options when the meaningful answer space is known; use an open question when it is not.
- Focus on purpose, users, constraints, success criteria, compatibility, and non-goals before implementation detail.
- Retrieve facts from the direct project/source and `session_search` before asking the user to repeat them.
- Use `clarify` only when the decision is genuinely blocking or materially preference-dependent. Low-stakes implementation choices should receive a stated, evidence-backed default.
- If new evidence invalidates an earlier answer, return to that decision instead of preserving a contradictory spec.

## Approach comparison

Compare the status quo and two or three materially different approaches when the decision is costly, hard to reverse, user-visible, or architecture-sensitive. For each approach state:

- the core design and ownership model;
- what it optimizes for;
- user, compatibility, operational, and migration consequences;
- important failure modes;
- proof and rollback boundaries.

Lead with the recommended approach and explain why it best fits the inspected constraints. Do not manufacture alternatives when only one safe, compatible path exists; record why the choice is constrained and continue.

## Design contract

Scale detail to the task, but make these decisions explicit when applicable:

| Area | Required answer |
|---|---|
| Outcome | What changes for the user or system, and how success is observed. |
| Scope | Included behavior, explicit exclusions, and decomposition boundary. |
| Components | Clear owner for each responsibility and dependency. |
| Flow | Inputs, state transitions, outputs, side effects, and lifecycle. |
| Interfaces | Caller knowledge, compatibility, errors, cancellation, and cleanup. |
| Failure handling | Invalid input, partial failure, retry/recovery, and safe fallback. |
| Quality proof | Behavioral tests, affected-area gates, runtime proof, and false-green risks. |
| Rollout | Migration order, observability, rollback, and removal conditions for temporary paths. |

Present only the sections that carry real decisions. A short design can be a few decisive paragraphs; complexity is not proof of rigor.

### Fillable requirement blocks

When a requirement is deliberately left for later completion, keep the placeholder type-safe and decision-ready rather than scattering free-form blanks. Record one requirement ID, the owning section/path, allowed choices or value shape, default only when authoritative, constraints, source/evidence pointer, validation rule, and status (`open`, `resolved`, or `blocked`). Unresolved blocks stay with this intent owner and cannot be converted into implementation detail by `writing-plans`; once resolved, the plan references the stable requirement ID instead of copying the glossary.

## Approval boundary

Approval is required only when the user explicitly requested collaborative design approval, a material product preference cannot be inferred safely, or the next choice is costly, externally visible, or hard to reverse. In those cases, present the relevant design section and wait for the user's answer before freezing that decision.

There is no universal approval gate for every software edit. When authority is clear, acceptance criteria are precise, and the design choice is low-risk or recoverable, state the selected design and continue through the umbrella workflow without a routine permission question. Never let this branch override a higher-level instruction to act or a report-only prohibition on edits.

## Specification and handoff

Write a durable spec when the behavior is non-trivial, the user requests one, several decisions must survive context compression, or implementation will be handed off. Use the project convention for the path; prefer an existing `worknotes/`, `docs/`, or specification directory over inventing `docs/superpowers/specs/`. Do not commit the spec unless the user or project workflow authorizes commits.

Before handoff, review the complete spec inline:

1. Remove placeholders, TODOs, and unresolved contradictions.
2. Make ambiguous requirements decisive or label the exact external decision that remains.
3. Confirm architecture, behavior, errors, tests, and rollout describe the same system.
4. Confirm the scope fits one implementation plan; decompose it if it does not.
5. Remove speculative flexibility and unrequested features.

Use the [independent spec reviewer template](../templates/design-discovery-spec-reviewer-prompt.md) only when the user explicitly requests independent review or the governing workflow requires separation of duties. After the spec is ready, load `writing-plans` and create the implementation plan from the approved or otherwise authoritative decisions.

## Isolation and clarity

- Give each unit one coherent responsibility and a small caller-facing contract.
- A consumer should understand what a unit does, how to use it, and what it depends on without reading internals.
- Prefer changing the owning seam over adding a parallel helper, wrapper, mode, or adapter.
- Follow existing project language and patterns; include only targeted design improvements needed for the requested outcome.
- Apply YAGNI: omit speculative extension points, optional modes, and future-proofing without current evidence.

## Visual companion

When a question is inherently visual and the user would benefit from seeing alternatives, offer the optional [Visual Design Companion](visual-design-companion.md). Use it for mockups, layouts, diagrams, spatial relationships, and side-by-side visual designs; keep requirements questions, conceptual choices, and text trade-offs in the normal conversation.

The companion is a tool, not a session mode. Decide per question, bind the server to loopback by default, keep artifacts task-owned, and stop the process when the visual decision is complete.

## Completion record

Before handing off, record:

- context inspected and assumptions retained;
- material questions answered or defaulted;
- selected approach and rejected alternatives;
- authoritative spec path, if one was written;
- remaining external decisions or explicitly deferred scope;
- next owner: normally `writing-plans`, or the applicable report/diagnosis owner when no implementation follows.
