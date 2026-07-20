---
name: writing-plans
description: Use when an authorized software change needs a durable implementation plan, cross-context handoff, migration plan, or evidence-backed design decision. Do not use for routine direct edits, unresolved diagnosis, or actual execution, verification, sign-off, or publication.
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

Own the lightest intended-state plan preserving scope, decisions, order, recovery, and proof. Never claim execution truth. Diagnosis, edits, evidence acceptance, and publication belong to `software-quality-workflows`; `long-document-segmented-writing` owns large-corpus drafting.

Codex and Hermes Agent share this contract. Resolve paths from this root; index authoritative sources instead of copying them.

## Card-cycle entry

Use only this skill root's `scripts/card_cycle.py` as the model-facing protocol:

1. Read the compact initial contract with `LC_ALL=C scripts/card_cycle.py route --help`.
2. Send one v2 command through stdin with `scripts/card_cycle.py route --input - --source-root <source>`; `--source-root` is the target repository root, never this skill root. Add `--work-root` only for resume.
3. For `next_step.kind=card`, read only `card_path`, verify `card_hash`, and make that decision. Never select by memory, similarity, cross-card link, or scan.
4. Every complete/render stdin object has exactly: `contract_id` from `input_contract`, `invocation_phase` (`initial` or `resume`), `previous_receipt` as the entire current replacement receipt (never an ID), `fields` from `input_contract`, and `outcome.blocker`; pass only `--source-root`, `required_root_args.always`, and matching conditional roots.
5. Send it with `scripts/card_cycle.py complete --input - ...`. Keep only the replacement receipt, never a receipt chain.
6. Resume only with route; render bounded output only with `scripts/card_cycle.py render --input - ...`; then return to the cycle.

`scripts/assess_plan_mode.py`, schemas, registries, manifests, tests, operator docs, templates, and support map are internal, not model commands/default reads. Identity mismatch fails closed.

`semantic_inline` fields/results exist only in stdin/stdout or owner state. Except for returned boundary/projection locators, write no protocol file. Do not open raw state, locks, whole artifact/projection directories, full schemas/manifests, fixtures, history, or logs. Replacement stops propagation; it does not prove physical context eviction.

## Selection and profiles

Unknown cause/intent returns to SQW; long corpus selects bridge; one uncertainty selects spike; public contract, migration, resume, external effect, or multiple strategies select Program; cross-context/durable/multi-slice execution selects Handoff; explicit plan requests select Brief; otherwise Direct.

- Brief: one same-session immutable projection; no owner or anchor.
- Handoff: ordered slices, boundaries, proof, rollback, one delivery locator; no owner anchor.
- Program: one durable migration/resume graph. `schemas/plan-state.schema.json` is truth; render the frontier within 8,192 bytes.

Use the lightest profile preserving authority, recovery, and proof. A missing long-document owner yields a typed blocker. Hand intended state to SQW only through `schemas/plan-execution-handoff.schema.json`; SQW revalidates it.

## One-card context

Context is limited to this entry, current help/receipt, one card, short stdout, and one needed projection/boundary. Manifest/card drift invalidates projections; source/scope/policy drift replans. Overflow blocks.

The long-document bridge passes only `scratch_retention`, final locator/hash, source/scope, requirements, and unresolved decisions. Never copy sections, ledger, coverage, recovery, or confidence content.

## Program anchor lifecycle

After Program bootstrap, keep exactly one line in an existing canonical task index or host state; create one task anchor only if neither exists:

`owner=<skill>/<owner-kind> | root=<exact task root> | locator=<immutable owner locator> | source=<source identity> | bundle=<bundle identity> | lifecycle=<active|terminal-retain|terminal-disposable> | boundary=<none or named consumer/evidence ref>`

Keep each root isolated and outside source. Replace locator/source in place; never save receipts. Without an unconsumed boundary, mark `terminal-disposable`, safely remove the exact root, verify absence, then remove the anchor. A named boundary is `terminal-retain` until consumption evidence. Never delete by age or add lifecycle schema, cleanup command, registry, or per-step anchor.

## Completion

Writing is complete when the requested artifact is consistent, source-bound, proportionate, schema-valid where applicable, and handed off with explicit gaps. This does not prove implementation, sign-off, publication, or workflow completion.
