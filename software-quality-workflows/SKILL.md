---
name: software-quality-workflows
description: "Use for software inspection, diagnosis, implementation, refactoring, testing, review, recovery, migration, developer tooling, or developer-facing documentation. Routine low-risk same-session edits use the direct path; load one specialized card only when current facts select it."
license: MIT
metadata:
  version: 8.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, testing, review, debugging]
    category: software-development
    related_skills: [writing-plans]
---

# Software Quality Workflows

## Owner contract

Own software execution truth: authority, scope, diagnosis, edits, tests, accepted evidence, review, recovery, and completion. Routine work stays Direct; durable machinery requires recovery or proof value.

Never invent intent, expand authority, treat context as state, trust worker self-verdicts, or equate local proof with publication readiness. `writing-plans` owns durable intended state; `long-document-segmented-writing` owns large-corpus drafting; hosted-platform owners control live remote state. A missing owner does not remove a gate.

Codex and Hermes Agent share this contract. Resolve paths from this skill root. Optional host features are not prerequisites; live agents, remote/destructive work, release, and publication require explicit authority.

## Safety kernel

Before changing anything:

1. Re-observe request, revision, dirty/concurrent state, scope, protected surfaces, effects, verifier, and proof. Unknown safety facts stay unknown.
2. Classify report, diagnose, intent, change, review, or recovery. Unknown cause blocks implementation; materially underdefined intent requires one focused decision.
3. Freeze the smallest authorized read/write/effect boundary; preserve user changes and repository identity.
4. Establish a behavior distinction first. Use [behavior cycle](references/test/behavior-cycle.md), make the smallest general change, and run proportional proof without weakening the oracle.
5. Treat worker output and evidence as proposals; the controller verifies identity, freshness, scope, and independence.
6. Inspect final diff/evidence and name every not-run, blocked, flaky, stale, sampled, or environment-limited gate. High-risk implementers do not self-approve.

## Card-cycle entry

Use only this skill root's `scripts/card_cycle.py` as the model-facing protocol:

1. Read the compact initial contract with `LC_ALL=C scripts/card_cycle.py route --help`.
2. Send one v2 route command through stdin with `scripts/card_cycle.py route --input - --source-root <source>`; `--source-root` is the target repository root, never this skill root. Add `--work-root` only for a durable resume required by that command.
3. For `next_step.kind=card`, read only `card_path`, verify `card_hash`, and make that decision. Never select by memory, similarity, link, or scan.
4. Every complete/render stdin object has exactly: `contract_id` from `input_contract`, `invocation_phase` (`initial` or `resume`), `previous_receipt` as the entire current replacement receipt (never an ID), `fields` from `input_contract`, and `outcome.blocker`; pass only `--source-root`, `required_root_args.always`, and matching conditional roots.
5. Send the command through stdin with `scripts/card_cycle.py complete --input - ...`. Keep only the returned replacement receipt; never preserve a receipt chain.
6. Resume durable work only with the route resume variant. Produce bounded durable projections only with `scripts/card_cycle.py render --input - ...`. After every completion, return to the card cycle; cards never select or preload successors.

`scripts/route_workflow.py`, schemas, registries, manifests, tests, and support map are internal owners, not model commands or default reads. Any identity mismatch fails closed; a card absent from the manifest is inactive.

`semantic_inline` fields and protocol results exist only in stdin/stdout or owner state. Except for returned boundary/projection locators, write no protocol JSON, Markdown, ledger, worknote, card result, or receipt. Do not open raw state, locks, events, whole artifact/projection directories, full schemas/manifests, fixtures, history, or logs. Replacement stops future propagation; it does not prove physical context eviction.

## Mode, review, and context

- **M0 Direct:** same-session, local, reversible, known seam, focused proof; no durable state or anchor.
- **M1 Trace:** bounded observed summaries and controlled pointers; no durable state or anchor.
- **M2 Sparse:** one durable owner at costly, delegated, approval, public-contract, or recovery boundaries.
- **M3 Full:** one durable owner for multi-session migration, release, destructive recovery, or shared state.

Mode never expands authority. Upgrade on observed authority, source, shared state, conflict, failure-locality, or proof risk; downgrade when that boundary ends. Review depth is independent: R0 self-diff plus verifier, R1 requirements plus engineering axes, R2 independent/adversarial evidence for high-risk work.

Model context is limited to this entry, current help/replacement receipt, one card, short stdout, and one needed projection/boundary artifact. `scripts/project_context.py` may render exact inputs within 8,192 bytes; overflow blocks, and projections never enter state hashing.

## Durable anchor lifecycle

After an M2/M3 bootstrap, keep exactly one line in an existing canonical task index or host session state; create one task-level anchor only when no index exists:

`owner=<skill>/<owner-kind> | root=<exact task root> | locator=<immutable owner locator> | source=<source identity> | bundle=<bundle identity> | lifecycle=<active|terminal-retain|terminal-disposable> | boundary=<none or named consumer/evidence ref>`

Keep each task root isolated and outside source. Replace locator/source in place; never save the receipt. A terminal owner without an unconsumed boundary becomes `terminal-disposable`: safely remove the exact root, verify absence, then remove the anchor. A named handoff/evidence boundary becomes `terminal-retain` until consumption or migration evidence makes it disposable. Never delete by age or add lifecycle schema, cleanup command, global registry, or per-step anchor.

## Planning handoff and completion

Planning hands off only through `writing-plans/schemas/plan-execution-handoff.schema.json`. Revalidate bundle, source, scope, authority, plan hash, policies, and blockers before execution state. Plan changes return to Writing Plans; publication readiness stays separate.

Complete only from fresh source/scope identity, accepted evidence, satisfied verifiers, resolved approvals, no pending work or locks, and explicit residual risk. Report `needs_repair`, `verified_within_scope`, `blocked`, or `empirical_validation_required` precisely. Local completion does not imply commit, push, PR, merge, release, deploy, or publication.
