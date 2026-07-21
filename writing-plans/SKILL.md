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

Own the lightest plan preserving scope/decisions/order/recovery/proof; never claim execution. `software-quality-workflows` owns execution/evidence/publication; `long-document-segmented-writing` owns large drafts. Codex and Hermes Agent resolve here; index, never copy.

## Card-cycle entry

Use this root's `scripts/card_cycle.py`:

1. Read `LC_ALL=C scripts/card_cycle.py route --help`.
2. Run `scripts/card_cycle.py route --fields-json '<object>' --source-root <source>`; resume adds `--resume`, owner fields and required external `--work-root`.
3. Read only `card_path`, verify `card_hash`, decide it; never recall or scan.
4. Pipe stdout unchanged to `scripts/card_cycle.py complete --fields-json JSON`. Brief ends with its projection. Only Program/Handoff pipe completion stdout to `scripts/card_cycle.py render --fields-json '{}'`; Program may use `{"projection_kind":"context-capsule"}`. Never build an envelope or copy locators.
5. Lost stdout: replay pre-owner; post-owner resume. Give only projected roots. Never write receipt/command files or inspect CLI source.
6. Keep only the replacement. Before Program returns an owner, source is read-only except a projected output root.

Require route receipt ID matching `sha256:[0-9a-f]{64}`; root is `<source-parent>/.frontier-wp-<full-hex>`. Before Program completion run `mkdir -m 700 -- <exact-root>` once, never `-p`; only completion receives it. Existing with matching canonical active anchor means route resume, not bootstrap; else block without scan/write. Copy schema-valid `field_examples`, replace placeholders/repeat nodes, and retain its projection queue; never invent keys.

`E_ORPHAN_CONFLICT` is non-retryable. Unavailable/unsafe/foreign/partial/binding conflict blocks without inspect, chmod, delete, recreate, alternate root, or fallback Markdown/manual state.

`scripts/assess_plan_mode.py`, schemas, registries, manifests, tests, docs, templates, and support map are internal, not model commands/default reads; never read/run. Mismatch fails closed.

`semantic_inline` fields use `--fields-json`; receipts/results stay in stdin/stdout or owner state. Except returned locators, write no protocol file. Do not open raw state, locks, whole artifact/projection directories, schemas/manifests, fixtures, history, or logs. Replacement stops propagation, not physical context eviction.

## Selection and profiles

Unknown cause/intent returns to SQW; long corpus uses bridge; uncertainty uses spike; public/migration/resume/external/multi-strategy uses Program; cross-context/durable/multi-slice uses Handoff; explicit plan uses Brief; else Direct.

`migration_or_rollback=true` only if the target migrates/cuts over/rolls out; a rollback section is false. `resume_required=true` only for later mutable Program planning, not immutable handoff. `same_session_execution=true` when this request finishes its plan now; implementation timing is irrelevant.

- Brief: same-session immutable projection; no anchor.
- Handoff: ordered slices/boundaries/proof/rollback, one delivery locator; no anchor.
- Program: one durable migration/resume graph. `schemas/plan-state.schema.json` is truth; frontier ≤8,192 bytes.

Use the lightest profile preserving authority/recovery/proof. Missing long-document owner is a typed blocker. Hand state to SQW only through `schemas/plan-execution-handoff.schema.json`; SQW revalidates it.

## One-card context

Entry, help/receipt, one card, stdout, one projection/boundary. Manifest/card drift invalidates; source/scope/policy drift replans; overflow blocks.

Long-document bridge passes only `scratch_retention`, final locator/hash, source/scope, requirements, unresolved decisions; never section/ledger/coverage/recovery/confidence content.

## Program anchor lifecycle

After Program bootstrap keep a canonical task-index line; create an anchor only if none exists:

`owner=<skill>/<owner-kind> | root=<exact task root> | locator=<immutable owner locator> | source=<source identity> | bundle=<bundle identity> | lifecycle=<active|terminal-retain|terminal-disposable> | boundary=<none or named consumer/evidence ref>`

Keep roots outside source. Replace locator/source; never save receipts. No boundary: `terminal-disposable`, remove exact root/anchor. Named boundary: `terminal-retain` until consumed. Never delete by age or add lifecycle schema, cleanup command, registry, or per-step anchor.

## Completion

Complete when artifact is consistent, source-bound, proportionate, schema-valid, and handed off with gaps; it proves no execution, sign-off, publication, or workflow completion.
