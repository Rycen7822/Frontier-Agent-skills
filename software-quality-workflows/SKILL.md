---
name: software-quality-workflows
description: "Use for software inspection, diagnosis, implementation, refactoring, testing, review, recovery, migration, developer tooling, or developer-facing documentation. Routine low-risk same-session edits use the direct path; load one specialized card only when current facts select it."
license: MIT
metadata:
  version: 7.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, testing, review, debugging]
    category: software-development
    related_skills: [writing-plans]
---

# Software Quality Workflows

## Owner contract

Own software execution truth: authority and scope, diagnosis, edits, tests, accepted evidence, review, invalidation, recovery, and completion. Routine work stays Direct; durable machinery exists only when recovery or proof value requires it.

All software work obeys the short kernel. Never invent intent, expand authority, treat context as state, trust worker self-verdicts, or equate local proof with publication readiness. `writing-plans` owns durable intended state and the sole typed execution handoff; `long-document-segmented-writing` owns large-corpus drafting; hosted-platform owners control live remote state. A missing owner does not remove a gate.

## Host compatibility

The contract is identical in Codex and Hermes Agent. Resolve bundled paths from this skill's root and express requirements by capability rather than a product-specific tool name. Optional host features never become prerequisites. Live host-agent execution and multi-candidate search are default-off; remote, destructive, release, and publication actions require separate authority.

## Safety kernel

Before changing anything:

1. Re-observe the request, source revision, dirty or concurrent state, scope, protected surfaces, and effects. Unknown safety facts stay unknown.
2. Classify report, diagnose, intent, change, review, or recovery. Unknown root cause blocks implementation; materially different intent alternatives require one question at a time.
3. Freeze the smallest authorized read, write, and effect boundary; preserve user changes and repository identity.
4. Establish a behavior distinction first. For behavior changes use [behavior cycle](references/test/behavior-cycle.md), implement the smallest general change, and run proportional proof without weakening the oracle.
5. Treat worker output and reported evidence as proposals. The controller verifies identity, freshness, scope, and independence.
6. Inspect final diff and evidence; name every not-run, blocked, flaky, stale, sampled, or environment-limited gate. High-risk implementers do not self-approve.

Authority, source and scope identity, hard constraints, verifier identity, and required proof are mandatory context and may not be truncated.

## Decision queue and mode

Validate current facts with `schemas/route-facts.schema.json`, run `scripts/route_workflow.py`, and validate the exact result and live manifest. The Router selects zero or one `selected_decision_id` and zero or one exact `primary_card`. A blocked result carries no card.

Pending decisions are explicit IDs. Available and completed artifacts are facts, not routing hints. A `decision_request` is valid only when it names the exact `just_completed_card_id`, one artifact that card produced, and an uncompleted mapped decision. Unknown, duplicate, already completed, unmet, or wrong-producer requests fail closed. After one card completes, return to the Router; cards never select or preload their successors.

Choose the lightest justified execution mode:

- **M0 Direct:** same-session, local and reversible, known seam, focused proof; no durable workflow state.
- **M1 Trace:** bounded observed summaries and controlled pointers; no durable workflow state.
- **M2 Sparse:** durable state only at costly, delegated, approval, public-contract, or recovery boundaries.
- **M3 Full:** multi-session migration, release, destructive recovery, or shared state requiring reconciliation.

Mode never expands authority. Upgrade on observed authority, source, hidden or shared state, conflict, failure-locality, or proof risk; downgrade when the costly boundary ends.

Review depth is independent: **R0** self-diff plus verifier; **R1** requirements plus engineering axes; **R2** independent or adversarial evidence for public, security, release, or high-risk work. Reviewer count is not quality.

## Policy ownership and one-card execution

Machine ownership is declared in `registries/policy-owners.json`; decision-to-card ownership is declared in `registries/decision-card-map.json`; card ID, path, hash, and byte identity come from the generated manifest. Use the [support map](references/package-support-map.md) only for lookup; do not preload it. A bundle, policy, map, fixture, or manifest mismatch fails closed. A card missing from the manifest is inactive.

Load only the selected card and verify its ID, hash, mapping, required artifacts, and byte ceiling. Make only that card's decision, emit its declared artifact, evict it, and return to the Router. Never select by filename, memory, keyword similarity, or directory scan. Do not preload siblings, catalogs, raw logs, full plans, or candidate history.

`scripts/project_context.py` accepts exact cards and projections and emits at most 8,192 bytes. Mandatory overflow blocks. Context traces and projections are disposable and excluded from canonical state hashing. Candidate work is not success; only the controller accepts transitions, invalidation, evidence, and completion. Hidden, shared, or root-assumption changes require parent replan.

## Planning handoff and completion

Planning hands off intended state only through `writing-plans/schemas/plan-execution-handoff.schema.json`. SQW revalidates bundle, source, scope, authority, plan hash, required policy IDs, and unresolved blockers before creating or resuming execution state. Plan changes return to Writing Plans. Publication readiness remains a separate decision and authority boundary.

Complete only from fresh source and scope identity, accepted evidence, satisfied required verifiers, resolved approvals, no pending background work or locks, and explicit residual risk. Use status precisely:

- `needs_repair`: evidence or implementation is invalidated or incomplete;
- `verified_within_scope`: named gates passed for the stated source and scope;
- `blocked`: a required condition cannot currently be satisfied;
- `empirical_validation_required`: correctness depends on a real runtime or external observation not yet performed.

Report the outcome, changed scope, observed proof, not-run or blocked gates, residual risk, and safe next action. Local completion does not imply commit, push, PR, merge, release, deploy, or publication.
