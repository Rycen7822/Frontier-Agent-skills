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

Own execution truth: authority/scope/diagnosis/changes/evidence/review/recovery/completion. Stay Direct unless recovery/proof requires durability. Never invent intent, expand authority, treat context as state, trust worker verdicts, or equate local proof with release readiness. `writing-plans` owns plans, `long-document-segmented-writing` owns large drafts, hosted owners control remote state; missing owners preserve gates.

For Codex and Hermes Agent: Resolve paths from this skill root. Optional host features are not prerequisites; live agents, remote/destructive work, release, and publication require explicit authority.

## Safety kernel

Before changing anything:

1. Re-observe request, revision, dirty/concurrent state, scope, protected surfaces, effects, verifier, proof; unknown stays unknown.
2. Classify report, diagnosis, intent, change, review, or recovery. Unknown cause blocks implementation; materially underdefined intent requires one focused decision.
3. Freeze the smallest authorized read/write/effect boundary; preserve user changes/repository identity.
4. Establish a distinction. Use [behavior cycle](references/test/behavior-cycle.md), make the smallest general change, and prove proportionally without weakening the oracle.
5. Treat worker output/evidence as proposals; verify identity, freshness, scope, independence.
6. Inspect final diff/evidence; name not-run, blocked, flaky, stale, sampled, or environment-limited gates. High-risk implementers do not self-approve.

## Direct path

Use **M0 Direct** without `card_cycle.py` only for same-session, local, reversible work with known authority/seam and no durable, recovery, delegation, public-contract, or external-effect boundary. It creates no receipt, work root, anchor, or protocol artifact. Inspect source/dirty state, make or report the smallest distinction, and prove proportionally. Unknown cause blocks Direct implementation, not bounded read-only diagnosis.

## Card-cycle entry

All other work uses only this skill root's `scripts/card_cycle.py` as the model-facing protocol:

1. Read `LC_ALL=C scripts/card_cycle.py route --help`.
2. Route fields only with `scripts/card_cycle.py route --fields-json '<object>' --source-root <source>`; resume uses the same command with `--resume`, owner-locator fields and required external `--work-root`. Source is the target repository.
3. For a card step, read only `card_path`, verify `card_hash`, and decide it; never select from memory or scan.
4. Pipe the receipt unchanged to `scripts/card_cycle.py complete --fields-json '<object>' ...`; SQW render uses the same receipt pipe with `scripts/card_cycle.py render --fields-json '<object>' ...`. CLI owns contract, phase and previous receipt. Never build an envelope, add `command`, or pass an unprojected root.
5. If stdout is gone, rerun the unchanged pre-owner prefix as one pipeline; after bootstrap use resume. Use variables/pipes, never receipt/command files.
6. Keep only the replacement. Before M2/M3 returns an owner, do not patch, emit task output or create a source-nested root.

First M2/M3 bootstrap uses explicit external root; else require the pending replacement receipt's `receipt_id` to match `sha256:[0-9a-f]{64}` and select `<source-parent>/.frontier-sqw-<full-hex>`. Before scope, run `mkdir -m 700 -- <exact-root>` once if absent, never `-p`. Existing with matching canonical active anchor means route resume, not bootstrap; else block without scan/write.

`E_ORPHAN_CONFLICT` is non-retryable. Unavailable/unsafe/foreign/partial/binding conflict stops: no inspect, chmod, delete, recreate, alternate root, source-nested `.eval-work`, `worknotes`, fallback Markdown/manual state. Later calls need root preconditions.

`scripts/route_workflow.py`, schemas, registries, manifests, tests, and support map are internal, not model commands or default reads. Mismatch fails closed; an unmanifested card is inactive.

`semantic_inline` fields/results exist only in stdin/stdout or owner state. Except returned boundary/projection locators, write no protocol JSON, Markdown, ledger, worknote, card result, or receipt. Do not open raw state, locks, events, whole artifact/projection directories, full schemas/manifests, fixtures, history, or logs. Replacement stops propagation; it does not prove physical context eviction.

## Mode, review, and context

- **M0 Direct:** admission above; no durable state/anchor.
- **M1 Trace:** bounded summaries/pointers; no durable state or anchor.
- **M2 Sparse:** one owner at costly, delegated, approval, public-contract, or recovery boundaries.
- **M3 Full:** one owner for multi-session migration, release, destructive recovery, or shared state.

Mode never expands authority. Upgrade on authority, source, shared state, conflict, failure-locality, or proof risk; downgrade afterward. Review is separate: R0 diff/verifier, R1 requirements/engineering axes, R2 independent/adversarial evidence for high risk.

Model context: this entry, help/receipt, one card, short stdout, one projection/boundary. `scripts/project_context.py` renders exact inputs ≤8,192 bytes; overflow blocks, projections never enter state hashing.

## Durable anchor lifecycle

After M2/M3 bootstrap, keep one line in an existing canonical task index/host state; create one task anchor only when no index exists:

`owner=<skill>/<owner-kind> | root=<exact task root> | locator=<immutable owner locator> | source=<source identity> | bundle=<bundle identity> | lifecycle=<active|terminal-retain|terminal-disposable> | boundary=<none or named consumer/evidence ref>`

Keep task roots isolated/outside source. Replace locator/source in place; never save receipts. Terminal without an unconsumed boundary is `terminal-disposable`: remove exact root safely, verify absence, remove anchor. Named handoff/evidence is `terminal-retain` until consumption/migration evidence. Never delete by age or add lifecycle schema, cleanup command, global registry, or per-step anchor.

## Planning handoff and completion

Planning hands off through `writing-plans/schemas/plan-execution-handoff.schema.json` only. Before execution revalidate bundle, source, scope, authority, plan hash, policies, blockers. Plan changes return to Writing Plans; publication stays separate.

Complete only from fresh source/scope identity, accepted evidence, satisfied verifiers, resolved approvals, no pending work/locks, and stated residual risk. Report `needs_repair`, `verified_within_scope`, `blocked`, or `empirical_validation_required`. Local completion does not imply commit, push, PR, merge, release, deploy, or publication.
