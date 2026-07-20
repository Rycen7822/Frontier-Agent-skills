---
name: long-document-segmented-writing
description: Use when Codex must read many files or a large source corpus and produce or substantially rewrite a long document, technical report, manual, roadmap, architecture guide, thesis-like draft, research synthesis, or other self-contained text. Preserves recovery state while keeping routine long-document work compact.
metadata:
  version: 1.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [documentation, long-form, research, planning]
    category: software-development
    related_skills: [writing-plans]
---

# Long Document Segmented Writing

Use durable files as working memory for long-form synthesis. Keep the workflow proportional: compact is the default; full exists only for an evidenced recovery or scale threshold.

This skill owns long-corpus reading, segmented drafting, recovery, deterministic assembly, whole-document review, and evidence-backed confidence repair. Repository instructions and format/domain skills remain authoritative for their own surfaces.

## Opening and resume status

At the start, after context compaction, or after a long interruption, report:

```text
文档完成状态：<not started / in progress / draft complete / verified final>
范围内证据置信：<low / medium / high / fully supported> — <main gap or proof>
恢复锚点：<scratch root and current section>
```

Completion requires the final file and its named checks; a plan, partial draft, or self-assessment is not completion evidence.

## Select one profile

Use compact unless at least one full-mode fact is already true.

| Profile | Selection facts | Allowed scratch structure |
|---|---|---|
| compact | Sources and sections can be indexed stably in one task, and no full-mode fact is true | One `scratch-ledger.md`, ordered section drafts, one `confidence-review.md`, and the final document |
| full | Cross-context or cross-session recovery is explicitly required; sources exceed 12; expected final sections exceed 10; one ledger would exceed 16 KiB; or the user requires a full audit structure | One scope file, one source inventory, one reading ledger, one section matrix, one recovery packet, ordered section drafts, one confidence review, and the final document |

Both profiles use exactly one task-owned scratch root. Never create notes by reading batch, confidence-review siblings by iteration, per-step JSON, receipt copies, or parallel scratch roots.

Retain the whole scratch root while interrupted, under audit, or not yet verified. After final verification, delete the whole root only when repository or user cleanup requirements call for it; never guess and delete individual old files.

## Compact ledger contract

Keep these sections in the single `scratch-ledger.md` and update them in place:

- scope, success criteria, final path, audience, exclusions, and safety boundaries;
- source inventory with authority, exact anchors, coverage state, extracted facts, and reread triggers;
- section coverage with purpose, required evidence, status, local checks, and open gaps;
- current recovery anchor, next action, final-assembly order, and unresolved confidence items.

Keep entries concise. Do not paste large excerpts, raw traces, manifests, schemas, or process history. `CODEX_STATE.md` remains a small index to active anchors, not a second ledger.

## Full profile contract

Full mode separates the same information only because a selection threshold requires it. Each information class has one canonical file and is updated in place. It does not permit batch notes, duplicate inventories, rolling recovery packets, or multiple confidence files.

After compaction, recover in this order: repository instructions and `CODEX_STATE.md` once; the scope; inventory and reading ledger; section matrix; recovery packet; confidence review; current section; exact source anchors named by the next incomplete section. Do not traverse the corpus again by default.

## Read and draft

1. Define scope and the final section order before broad reading.
2. Discover sources with bounded searches, locate anchors, and read thematic batches.
3. Immediately update the active ledger with exact ranges, extracted facts, target sections, and reread triggers.
4. Draft one sortable section file per final section, such as `00_summary.md` and `01_design.md`.
5. Reread exact sources for commands, flags, schemas, APIs, state transitions, numbers, dates, citations, tests, paths, and public contracts.
6. Check each section for required content, unsupported claims, contradictions, placeholders, sensitive data, broken Markdown, duplication, and source-style violations.

Do not rely on conversation memory for a material claim. When evidence conflicts, record the owning source decision in the ledger and repair the section from that source.

## Source style

Outside fenced code, one prose paragraph, list item, or blockquote paragraph occupies one physical line. Structural line breaks for headings, blank lines, table rows, list items, blockquotes, fences, and fence bodies remain intact. Never hard-wrap prose to terminal width or interrupt a sentence with an arbitrary newline.

Run the assembler's source-style check against every ledger, section, confidence review, and final prose source before promotion:

```bash
python3 "$LONG_DOCUMENT_SKILL_ROOT/scripts/assemble_markdown.py" \
  --check-source-style path/to/scratch-ledger.md \
  --check-source-style path/to/00_summary.md
```

Fix the source that fails. The checker never rewrites prose.

## Deterministic assembly

The checked-in [Markdown assembler](scripts/assemble_markdown.py) is the only owner of full-document assembly. Supply every section explicitly and in final order; globbing, directory scans, implicit sorting, model-authored patch assembly, shell concatenation, and copy/paste assembly are forbidden.

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

Successful stdout is one compact JSON status line. The tool creates no manifest, sidecar, receipt, or worknote.

## Whole-document verification

Read the assembled document in bounded sections. Verify global structure, transitions, terminology, repeated definitions, cross-references, commands, state transitions, source support, and whether a new reader can act without hidden conversation context.

When review exposes a factual gap, reopen the exact source and patch the owning section; rerun source-style validation, assembly, and `--check`. Never patch only the assembled output.

## Confidence repair

Use one `confidence-review.md`. For each concrete gap, record the requirement or claim, source to reread, owning section, repair, and proof. Update this file in place until every in-scope material claim is verified or has an explicit evidence boundary.

Stop when concrete gaps are closed. Do not create new review files for abstract certainty, and do not describe inaccessible evidence as verified.

## Final report

Report completion status, evidence-backed confidence, final document path, retained or removed scratch root, material source families reread, actual assembly and verification results, and any remaining out-of-scope or inaccessible uncertainty.

Keep scratch paths, process history, source ledgers, local machine paths, credentials, private identifiers, raw private text, and patch details out of the reader-facing document unless the user explicitly requests an audit artifact.
