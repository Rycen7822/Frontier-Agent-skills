---
name: brainstorming
description: Use before creative work such as creating features, building components, adding functionality, or modifying behavior. Clarifies intent, inspects context, compares viable designs, and chooses a proportionate implementation. When the user authorizes a change, default to executing the best-supported safe approach without routine approval questions; ask only for dangerous or materially irreversible decisions, missing authority or genuinely blocking information, or a clearly unsound technical route.
license: MIT
metadata:
  version: 1.0.0
  author: Hermes Agent (adapted from obra/superpowers)
  hosts: [codex, hermes-agent]
  hermes:
    tags: [brainstorming, design, product, software-development]
    category: software-development
    related_skills: [writing-plans, software-quality-workflows]
---

# Brainstorming Ideas Into Actionable Designs

Turn requests into evidence-backed designs without making the user approve ordinary engineering decisions.

## Core contract

- Inspect the current project, relevant files, tests, documentation, and local conventions before deciding.
- Distinguish an execution request from a design-only, review-only, or explanatory request.
- Default action: execute the best-supported safe approach when the user has asked for a change and scope and authority are clear.
- Treat normal in-scope implementation choices as delegated engineering judgment.
- State material assumptions briefly and continue when they are safe, reversible, and consistent with the request.
- Keep design effort proportional: a few sentences for a local change; a durable design artifact for architecture, migrations, public contracts, or multi-component work.
- Do not commit, push, deploy, message external parties, or expand scope unless the user or repository workflow authorizes it.

<AUTONOMY-GATE>
Do not pause merely because multiple viable implementations exist. Compare them internally, select the option best supported by repository evidence, maintainability, safety, and verification cost, then continue.

Ask only when at least one of these conditions holds:

1. **Danger or irreversibility:** the next choice can destroy data, affect production or external users, create material cost, weaken security/privacy, or is difficult to roll back.
2. **Missing authority:** completion requires an external side effect, materially broader scope, credential use, deployment, publication, or coordination the user did not authorize.
3. **Blocked by missing information:** the needed fact cannot be discovered safely from available context, and any reasonable assumption could materially change the result.
4. **Clearly unsound route:** inspected evidence shows the requested technical route cannot meet the goal, violates a hard constraint, or creates a serious architectural or safety defect.

Before asking, exhaust safe read-only inspection and in-scope alternatives. When a question is necessary, explain the concrete evidence and ask one focused question. For an unsound route, recommend the correction instead of presenting a neutral menu.
</AUTONOMY-GATE>

## Decisions that do not require confirmation

Choose and proceed without asking about:

- naming, file placement, internal decomposition, test shape, or implementation details that follow existing conventions;
- safe and reversible trade-offs with a clear evidence-backed winner;
- which of several technically sound approaches to use when one has lower complexity, lower blast radius, or stronger verification;
- minor ambiguity that can be resolved from nearby code, documentation, tests, or an explicit reasonable assumption;
- optional refactors or enhancements: omit them unless they are required for the requested outcome.

The presence of alternatives is not itself a reason to ask. User preference questions are appropriate only when the preference is essential to the requested outcome and cannot be inferred; otherwise choose the most coherent default and flag it in the handoff.

## Workflow

1. **Explore context.** Read the smallest relevant slice of code, docs, tests, state, and history. Identify the owning seam and existing constraints.
2. **Normalize the request.** Record the outcome, scope, non-goals, authority, success criteria, and any safe assumptions.
3. **Assess scope.** Decompose requests that span independent systems. For an authorized implementation request, begin with the smallest end-to-end slice that materially advances the goal.
4. **Compare approaches internally.** For non-trivial work, consider two or three viable approaches and their correctness, complexity, maintainability, compatibility, rollback, and proof burden.
5. **Choose the strongest option.** Prefer existing owners and patterns; avoid wrappers, modes, dependencies, schemas, or parallel paths unless evidence proves they are needed.
6. **Design proportionally.** Define components, interfaces, data flow, error handling, verification, and rollback only to the depth the change requires.
7. **Execute when authorized.** Move into planning and implementation without a separate design-approval round. Respect any repository-required plan, test, or review gates.
8. **Verify and report.** Run focused proof first, then the smallest broader gate warranted by blast radius. Report the outcome, important decisions, validation, and residual risk.

## Internal alternatives, external brevity

Do the comparison work even when it is not shown. Present multiple approaches to the user only when they explicitly ask for options, when the task is design-only, or when the autonomy gate requires a consequential decision. Otherwise lead with the chosen approach and the evidence that made it preferable.

Do not expose private chain-of-thought. Expose concise decision evidence: inspected facts, assumptions, selected design, rejected alternatives when material, proof, rollback, and remaining risks.

## Design quality

- Give each unit one clear purpose and a well-defined interface.
- Follow existing codebase patterns and improve only problems that directly affect the requested work.
- Prefer changing, deleting, merging, or reusing existing seams over adding parallel abstractions.
- Keep files and components understandable in isolation.
- Include error handling and tests at the boundaries where failure would matter.
- Apply YAGNI: defer capabilities not required for the requested outcome.

## Design artifacts and handoff

- Write a durable design or implementation plan when the change is architecture-sensitive, multi-step, migration-heavy, public-contract-changing, risky, or likely to survive context compaction.
- Use the repository's established worknotes or plans directory. Do not force a design document or commit for trivial changes.
- Self-review artifacts for placeholders, contradictions, ambiguity, scope creep, and false-green verification.
- If the user asked only for a plan or design, stop after delivering it. If they asked to implement, proceed through the applicable planning and quality workflow without requesting routine approval.

## Key principles

- **Autonomy with boundaries** — execute ordinary authorized work; escalate only concrete blockers or risks.
- **Evidence before preference questions** — inspect first and infer safe defaults.
- **Internal alternatives, decisive execution** — compare options, then choose.
- **Proportional design** — match rigor to blast radius.
- **Low churn** — improve the owning seam and avoid parallel machinery.
- **Verification over ceremony** — prove the result instead of collecting approvals.

## Provenance

This Frontier adaptation retains the imported project's [source record](references/SOURCE.md) and [MIT license](references/LICENSE.txt).

## Optional resources

Load the [visual companion](references/visual-companion.md) only when the task is materially easier to understand through a browser-rendered mockup, diagram, or spatial comparison. Do not read its templates or start its local server for ordinary textual design work.

Load the [spec document reviewer prompt](references/spec-document-reviewer-prompt.md) only when an authorized workflow explicitly delegates a completed specification review. It is not part of the default brainstorming path.
