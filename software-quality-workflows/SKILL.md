---
name: software-quality-workflows
description: "Use for software inspection, diagnosis, implementation, refactoring, testing, review, recovery, migration, developer tooling, or developer-facing documentation. Routine low-risk same-session edits use the direct path; load specialized cards only when observed facts require them."
license: MIT
metadata:
  version: 5.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, testing, review, debugging]
    category: software-development
    related_skills: [writing-plans]
---

# Software Quality Workflows

## Owner contract

Own software execution truth: authority/scope, diagnosis, edits, tests, accepted evidence, review, invalidation, recovery, sign-off, and completion. Routine work stays Direct; durable machinery is justified only by recovery or proof value.

All software work obeys the short kernel. Never invent intent, expand authority, treat context as state, trust worker self-verdicts, or equate local proof with publication readiness. `writing-plans` owns durable intended state and Closure Contract handoff; `long-document-segmented-writing` owns large-corpus drafting; hosted-platform owners control live remote state. Missing owners do not remove gates.

## Host compatibility

The contract is identical in Codex and Hermes Agent. Resolve bundled paths from this skill's root and express requirements by capability rather than a product-specific tool name. Optional host features never become prerequisites. Live host-agent execution and multi-candidate search are default-off; remote/destructive/publication actions need separate authority.

## Safety kernel

Before changing anything:

1. Re-observe request, source revision, dirty/concurrent state, scope, protected surfaces, and effects. Unknown safety facts stay unknown.
2. Classify report/diagnose/intent/change/review/recovery/admission. Unknown root cause blocks implementation; material intent alternatives require one question at a time.
3. Freeze the smallest authorized read/write/effect boundary; preserve user changes and repository identity.
4. Establish a behavior distinction first. For behavior changes use [behavior distinction](references/test/behavior-distinction-and-red.md), implement the smallest general change, and run proportional proof without weakening the oracle.
5. Treat worker output and reported evidence as proposals. The controller verifies identity, freshness, scope, and independence.
6. Inspect final diff/evidence; name every not-run, blocked, flaky, stale, sampled, or environment-limited gate. High-risk implementers do not self-approve.

Authority, source/scope identity, hard constraints, verifier identity, and required proof are mandatory context and may not be truncated.

## Route and mode

Validate sparse facts with the route schemas, run `scripts/route_workflow.py`, then verify the exact result and live manifest. Router returns zero or one exact `primary_card`, never a list or transitive closure.

Choose the lightest justified mode:

- **M0 Direct:** same-session, local/reversible, known seam, focused proof; no durable workflow graph.
- **M1 Trace:** bounded observed summaries/pointers; no predeclared graph.
- **M2 Sparse:** durable state only at costly, delegated, approval, public-contract, or recovery boundaries.
- **M3 Full:** multi-session migration/release/destructive recovery/shared state needing full reconciliation.

Mode never expands authority. Upgrade on observed authority, source, hidden/shared state, conflict, failure-locality, or proof risk; downgrade when the costly boundary closes.

Review depth is independent: **R0** self-diff + verifier; **R1** requirements + engineering axes; **R2** independent/adversarial evidence for public/security/release/high risk. Reviewer count is not quality.

## Policy ownership

`registries/policy-owners.json` solely owns policy; the generated card manifest solely owns card ID/path/hash/edges. Schemas/scripts own machine truth, cards one model decision, and `operator/` non-model mechanics. Paths are not policy identity.

Never choose a card by filename, memory, keyword similarity, or directory scan. Bundle, policy, or manifest mismatch fails closed. A card missing from the generated manifest is not active.

## One-card execution

Load the exact primary card; verify ID/hash/bytes; make only its decision. Follow at most one declared neighbor through the Resolver with required reason/evidence, then evict or reroute. Keep at most three exact cards; never preload siblings, catalogs, raw logs, full plans, or candidate history.

`scripts/project_context.py` takes exact cards/projections and emits at most 8,192 bytes. Mandatory overflow blocks. Context trace/projections are disposable and hash-excluded.

Candidate work is not success. Only the controller accepts transitions, budgets, promotion, and typed invalidation. Hidden/shared/root-assumption changes require global replan.

## Closure and handoffs

Autonomous closure begins with the canonical pre-workflow Admission. Direct selection remains standard; terminal Admission creates no workflow; `CLOSURE_ELIGIBLE` routes to Writing Plans for a frozen Program Closure Contract and the sole `plan-execution-handoff` envelope.

SQW revalidates Admission, Authority, plan, contract, bundle/source/scope/policy/card hashes, and epoch. Closure starts `BASELINING`, then controller-owned `VERIFIER_QUALIFYING`, `SEARCHING`, `SIGNING_OFF`, `TERMINAL`. Supersession needs a complete newer-epoch handoff; sign-off needs fresh integration, frozen verifier, four axes, and incumbent-bound certificate.

Standard handoffs have no Admission/Contract. Plan changes return to Writing Plans; publication readiness stays separate.

## Completion

Close only from fresh source/scope identity, accepted evidence, resolved required approvals/background work, proportional verification, and explicit residual risk. Use epistemic status precisely:

- `needs_repair`: evidence or implementation is invalidated or incomplete;
- `verified_within_scope`: named gates passed for the stated source and scope;
- `blocked`: a required condition cannot currently be satisfied;
- `empirical_validation_required`: correctness depends on a real runtime or external observation not yet performed.

Report the outcome, changed scope, observed proof, not-run/blocked gates, residual risk, and safe next action. Local completion does not imply commit, push, PR, merge, release, deploy, or publication.
