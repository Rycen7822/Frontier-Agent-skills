---
name: writing-plans
description: Use when an authorized change needs a durable implementation or migration plan, cross-context handoff, or evidence-backed design decision. Do not use for routine edits, unresolved diagnosis, execution, verification, sign-off, or publication.
license: MIT
metadata:
  version: 7.0.0
  author: Hermes Agent (adapted from obra/superpowers)
  hosts: [codex, hermes-agent]
  hermes:
    tags: [planning, design, implementation, migration, documentation]
    category: software-development
    related_skills: [software-quality-workflows]
---

# Writing Plans

## Owner boundary

Own the lightest plan preserving scope/decisions/order/recovery/proof; never claim execution. `software-quality-workflows` owns execution/evidence/publication; `long-document-segmented-writing` owns large drafts. Codex and Hermes Agent: resolve from this root; index sources, never copy.

## Card-cycle entry

Use only this root's `scripts/card_cycle.py` as model protocol:

1. Read `LC_ALL=C scripts/card_cycle.py route --help`.
2. Route one v2 stdin command with `scripts/card_cycle.py route --input - --source-root <source>`; `--source-root` is the target repository root, never this skill root. Use `--work-root` only for resume.
3. For `next_step.kind=card`, read only `card_path`, verify `card_hash`, decide it; never select by memory, similarity, link, or scan.
4. Complete/render stdin has only: `contract_id` from `input_contract`, `invocation_phase` (`initial`/`resume`), `previous_receipt` as entire current replacement receipt (never an ID), `fields` from `input_contract`, `outcome.blocker`; pass only `--source-root`, `required_root_args.always`, and matching conditional roots.
5. Use `scripts/card_cycle.py complete --input - ...`; keep only replacement receipt, never a receipt chain.
6. Resume via route; use `scripts/card_cycle.py render --input - ...` only for bounded output; return to cycle.

First Program bootstrap uses explicit external root; else require the pending replacement receipt's `receipt_id` matching `sha256:[0-9a-f]{64}` and select `<source-parent>/.frontier-wp-<full-hex>`. Before Program run `mkdir -m 700 -- <exact-root>` once if absent, never `-p`. Existing with matching canonical active anchor means route resume, not bootstrap; else block without scan/write.

`E_ORPHAN_CONFLICT` is non-retryable. On unavailable/unsafe/foreign/partial/binding conflict stop: no inspect, chmod, delete, recreate, alternate root, source-nested `.eval-work`, `worknotes`, fallback Markdown/manual state. Later calls must satisfy root preconditions.

`scripts/assess_plan_mode.py`, schemas, registries, manifests, tests, docs, templates, support map are internal, not model commands/default reads; mismatch fails closed.

`semantic_inline` fields/results stay in stdin/stdout or owner state. Except returned boundary/projection locators, write no protocol file. Do not open raw state, locks, whole artifact/projection directories, schemas/manifests, fixtures, history, or logs. Replacement stops propagation, not physical context eviction.

## Selection and profiles

Unknown cause/intent returns to SQW; long corpus uses bridge; one uncertainty uses spike; public contract/migration/resume/external effect/multiple strategies use Program; cross-context/durable/multi-slice uses Handoff; explicit plan request uses Brief; else Direct.

- Brief: same-session immutable projection; no anchor.
- Handoff: ordered slices/boundaries/proof/rollback, one delivery locator; no anchor.
- Program: one durable migration/resume graph. `schemas/plan-state.schema.json` is truth; frontier ≤8,192 bytes.

Use the lightest profile preserving authority/recovery/proof. Missing long-document owner is a typed blocker. Hand state to SQW only through `schemas/plan-execution-handoff.schema.json`; SQW revalidates it.

## One-card context

Context is entry, help/receipt, one card, stdout, and one needed projection/boundary. Manifest/card drift invalidates; source/scope/policy drift replans; overflow blocks.

Long-document bridge passes only `scratch_retention`, final locator/hash, source/scope, requirements, unresolved decisions; never section/ledger/coverage/recovery/confidence content.

## Program anchor lifecycle

After Program bootstrap keep one line in a canonical task index/host state; create one task anchor only if neither exists:

`owner=<skill>/<owner-kind> | root=<exact task root> | locator=<immutable owner locator> | source=<source identity> | bundle=<bundle identity> | lifecycle=<active|terminal-retain|terminal-disposable> | boundary=<none or named consumer/evidence ref>`

Keep roots isolated/outside source. Replace locator/source in place; never save receipts. No unconsumed boundary: `terminal-disposable`; remove exact root, verify absence, remove anchor. Named boundary: `terminal-retain` until consumed. Never delete by age or add lifecycle schema, cleanup command, registry, or per-step anchor.

## Completion

Writing completes when artifact is consistent, source-bound, proportionate, schema-valid, and handed off with explicit gaps; it proves no execution, sign-off, publication, or workflow completion.
