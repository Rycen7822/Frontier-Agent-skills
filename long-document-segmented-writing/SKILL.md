---
name: long-document-segmented-writing
description: Use when Codex must read many files or a large source corpus and produce or substantially rewrite a long document, technical report, manual, roadmap, architecture guide, thesis-like draft, research synthesis, or other self-contained text. Preserves recovery state while keeping routine long-document work compact.
metadata:
  version: 2.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [documentation, long-form, research, planning]
    category: software-development
    related_skills: [writing-plans]
---

# Long Document Segmented Writing

Use durable files as working memory only when scale or recovery requires them. Keep the workflow proportional: bounded same-session work is Direct, compact is the segmented default, and full exists only for an evidenced recovery or scale threshold.

This skill owns long-corpus reading, segmented drafting, recovery, deterministic assembly, whole-document review, and evidence-backed confidence repair. Repository instructions and format/domain skills remain authoritative for their own surfaces.

## Opening and resume status

For compact or full work, at the start, after context compaction, or after a long interruption, report:

```text
文档完成状态：<not started / in progress / draft complete / verified final>
范围内证据置信：<low / medium / high / fully supported> — <main gap or proof>
恢复锚点：<scratch root and current section>
```

An explicit output-only shape remains authoritative. A compact recovery block contains exactly four labeled fields: Current recovery anchor, Next action, Final-assembly order, and Confidence gaps/proof; emit no opening status or other ledger section. For any other exact final structure, fold recovery facts into its named fields; do not prepend this status triplet or expose internal ledger sections unless that structure expressly requires them.

Completion requires the final file and its named checks; a plan, partial draft, or self-assessment is not completion evidence.

Direct work does not emit a recovery status or invent a scratch anchor. When the user explicitly requests a same-session continuation anchor, return that anchor inline without creating durable working files; the requested anchor does not by itself select a segmented profile.

When returning a recovery anchor, name each material fact and its owning source explicitly in the proof or gap field.

## Same-session Direct gate

Use Direct, with no scratch root, only when all of these facts are true:

- there are at most 4 source files and their combined size is at most 32 KiB;
- the requested final document needs at most 6 sections and at most 8 KiB unless the user explicitly requires greater length;
- the work will finish in the current context and does not require cross-session recovery or a full audit trail;
- no unresolved source conflict requires a durable decision ledger.

Skill activation does not imply a long output. A small source bundle with no requested length remains Direct and the final document stays proportional to the source and requirements.

A bounded two-turn task remains Direct when both turns stay in the same Codex session and every other Direct fact holds. Read the bounded sources needed by both turns before the first response, complete the requested first-turn content, and include only the requested inline anchor with the remaining section, its exact source facts, final order, and any open evidence gap. On continuation, reread the exact bounded sources named by that anchor, write the complete final document once, run the Direct source-style check, and reread the final. Do not create a ledger, draft shard, or assembler workflow for this path.

In Direct, read the bounded sources, define the short section order in working context, preserve every requested deliverable constraint including exact structure, count, and format, write only the requested final document, run the source-style check against that final file, reread the final in one bounded pass, and reopen only exact source anchors needed to repair concrete gaps. Do not create a scratch root, owner allocation, ledger, section drafts, confidence review, `CODEX_STATE.md`, receipt, worknote, or sidecar; do not inspect `agents/openai.yaml` or search for owner-allocation tools; do not run assembler section/output modes. If a Direct fact becomes false before the final write, select compact or full once and do not maintain both paths.

## Select one segmented profile

Use compact unless at least one full-mode fact is already true.

| Profile | Selection facts | Allowed scratch structure |
|---|---|---|
| compact | Direct does not apply, sources and sections can be indexed stably in one task, and no full-mode fact is true | One `scratch-ledger.md`, 1–4 ordered draft shards, and the final document; confidence gaps stay in the ledger |
| full | Cross-context or cross-session recovery is explicitly required; sources exceed 12; expected final sections exceed 10; one ledger would exceed 16 KiB; or the user requires a full audit structure | One scope file, one source inventory, one reading ledger, one section matrix, one recovery packet, ordered section drafts, one confidence review, and the final document |

Both segmented profiles use exactly one task-owned scratch root. Never create notes by reading batch, confidence-review siblings by iteration, per-step JSON, receipt copies, or parallel scratch roots.

Retain the whole scratch root while interrupted, under audit, or not yet verified. After final verification, delete the whole root only when repository or user cleanup requirements call for it; never guess and delete individual old files.

## Compact ledger contract

Keep these sections in the single `scratch-ledger.md` and update them in place:

- scope, success criteria, final path, audience, exclusions, and safety boundaries;
- source inventory with authority, exact anchors, coverage state, extracted facts, and reread triggers;
- section coverage with purpose, required evidence, status, local checks, and open gaps;
- current recovery anchor, next action, final-assembly order, and every confidence gap or proof.

Keep entries concise. Do not paste large excerpts, raw traces, manifests, schemas, or process history. `CODEX_STATE.md` remains a small index to active anchors, not a second ledger.

## Full profile contract

Full mode separates the same information only because a selection threshold requires it. Each information class has one canonical file and is updated in place. It does not permit batch notes, duplicate inventories, rolling recovery packets, or multiple confidence files.

After compaction, recover in this order: repository instructions and `CODEX_STATE.md` once; the scope; inventory and reading ledger; section matrix; recovery packet; confidence review; current section; exact source anchors named by the next incomplete section. Do not traverse the corpus again by default.

## Read and draft

1. Define scope and the final section order before broad reading.
2. Discover sources with bounded searches, locate anchors, and read thematic batches.
3. Immediately update the active ledger with exact ranges, extracted facts, target sections, and reread triggers.
4. Draft one sortable shard per coherent edit and review unit, not per heading. Compact uses 1–4 shards even when the final document has more headings; full uses only the section files justified by its scale facts.
5. Reread exact sources for commands, flags, schemas, APIs, state transitions, numbers, dates, citations, tests, paths, and public contracts.
6. Check each section for required content, unsupported claims, contradictions, placeholders, sensitive data, broken Markdown, duplication, and source-style violations.

Source qualifiers are part of the claim. Mark a broader statement unsupported when its citation proves only a narrower scope, even when the citation is otherwise related.

During review, enumerate every in-scope claim once in source order, classify it against its source and the request's taxonomy, then return the resulting tuples one-for-one in that same order.

Before returning structured findings, reconcile every output tuple against its cited source and the request's taxonomy: copy the source fact exactly, classify an incompatible fact as contradicted, and use unsupported when no source establishes or rules out the claim.

Do not rely on conversation memory for a material claim. When evidence conflicts, record the owning source decision in the ledger and repair the section from that source.

## Source style

Outside fenced code, one prose paragraph, list item, or blockquote paragraph occupies one physical line. Structural line breaks for headings, blank lines, table rows, list items, blockquotes, fences, and fence bodies remain intact. Never hard-wrap prose to terminal width or interrupt a sentence with an arbitrary newline.

Run the assembler's source-style check against the Direct final file or every segmented ledger, draft shard, confidence review, and final prose source before promotion:

Run each source-style invocation as a dedicated command whose stdout contains only `status` and total `bytes`. Treat it as validation feedback; direct candidate/output byte comparison owns assembly evidence. Perform the bounded final reread separately after the status is captured.

```bash
python3 "$LONG_DOCUMENT_SKILL_ROOT/scripts/assemble_markdown.py" \
  --check-source-style path/to/scratch-ledger.md \
  --check-source-style path/to/00_summary.md
```

Fix the source that fails. The checker never rewrites prose.

## Deterministic segmented assembly

For compact and full work, the checked-in [Markdown assembler](scripts/assemble_markdown.py) is the only owner of full-document assembly. Supply every draft shard explicitly and in final order; globbing, directory scans, implicit sorting, model-authored patch assembly, shell concatenation, and copy/paste assembly are forbidden. Direct work invokes only the source-style submode and writes the requested final file without section/output assembly modes.

```bash
python3 "$LONG_DOCUMENT_SKILL_ROOT/scripts/assemble_markdown.py" \
  --section path/to/00_summary.md \
  --section path/to/01_design.md \
  --output path/to/final.md
```

The assembler validates all inputs before writing, preserves section bytes except trailing blank lines, places exactly one blank line between sections, writes exactly one final LF, and publishes atomically. An identical target is a zero-write no-op that preserves inode and mtime.

Verify the final bytes with the identical ordered arguments plus `--check`:

```bash
python3 "$LONG_DOCUMENT_SKILL_ROOT/scripts/assemble_markdown.py" \
  --section path/to/00_summary.md \
  --section path/to/01_design.md \
  --output path/to/final.md \
  --check
```

Successful stdout is one compact JSON line containing only `status` and output `bytes`. The assembler writes only the requested target; deterministic proof comes from direct candidate/output byte comparison.

## Whole-document verification

Read the assembled document in bounded sections. Verify global structure, transitions, terminology, repeated definitions, cross-references, commands, state transitions, source support, and whether a new reader can act without hidden conversation context.

When review exposes a factual gap, reopen the exact source and patch the owning section; rerun source-style validation, assembly, and `--check`. Never patch only the assembled output.

## Confidence repair

Direct repairs concrete gaps in the final document and creates no confidence artifact. Compact records each concrete gap, source reread, owning shard, repair, and proof in `scratch-ledger.md`. Full uses one `confidence-review.md` and updates it in place. Continue only until every in-scope material claim is verified or has an explicit evidence boundary.

Stop when concrete gaps are closed. Do not create new review files for abstract certainty, and do not describe inaccessible evidence as verified.

## Final report

Report completion status, evidence-backed confidence, final document path, material source families reread, actual write/assembly and verification results, and any remaining out-of-scope or inaccessible uncertainty. Mention scratch retention only for compact or full work.

Keep scratch paths, process history, source ledgers, local machine paths, credentials, private identifiers, raw private text, and patch details out of the reader-facing document unless the user explicitly requests an audit artifact.

An explicit request for a recovery anchor, recovery packet, or audit marker is part of the reader-facing deliverable. Preserve that requested content even if the document could otherwise be finalized without internal recovery state.
