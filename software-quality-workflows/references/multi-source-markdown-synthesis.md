# Multi-Source Markdown Synthesis

Use this reference when a software-development report must consolidate several large Markdown reports into one de-duplicated final document with durable scratch notes and segmented editing.

Apply [Delegated Development](delegated-development.md) for delegation and controller verification. Use `long-document-segmented-writing` as the external owner when corpus size or document length requires its recovery-oriented drafting workflow.

## Controller workflow

1. **Inventory first.** Record source paths, line/byte counts, leading headings, and source/generated/final classification in a task-owned scratch file. Exclude generated and final outputs from the source set so they cannot be re-ingested.
2. **Assign reading by evidence weight.** Split large files or related groups across children. Require each child to write a concise notes file containing core structure, unique contributions, duplicate themes, keep/drop recommendations, overclaim risks, and suggested final-section placement.
3. **Cover failures centrally.** If a child times out, do not abandon the source. Read its durable partial report if trustworthy; otherwise extract headings and key sections directly and write a controller-owned notes file.
4. **Build a de-duplication index.** Track recurring systems, mechanisms, claims, identifiers, and links across sources. Merge repeated “paper plus repository” or “same mechanism under different names” entries into one evidence-aware item.
5. **Write an integrated outline.** Define final sections, evidence labels, de-duplication rules, and downgrade/appendix criteria before drafting. Organize by mechanism or decision rather than source file unless the user asks for source-by-source structure.
6. **Draft in logical parts.** Create task-owned part files and reread them before final assembly.
7. **Edit the final document in segments.** Start with a small skeleton and patch one section at a time. Do not build an append-only document whose later sections contradict earlier ones.
8. **Add compact traceability.** Include a source-to-mechanism map showing what each source contributed and which claims were merged, downgraded, or removed.
9. **Run the final review loop.** Check requirement coverage, duplicate residue, overclaims, placeholders, table/fence balance, link reachability, and source-to-conclusion traceability. Apply only evidence-backed corrections.

## Preferred final shape

- conclusion or recommended architecture;
- evidence levels and de-duplication rules;
- data models and schemas;
- lifecycle and state transitions;
- retrieval, context, token, latency, or pollution controls when relevant;
- de-duplicated mechanism/reference matrix;
- phased roadmap and evaluation plan;
- guardrails and failure modes;
- source-to-mechanism map.

## Pitfalls

- Do not trust a report's self-claim of complete verification. Preserve useful mechanisms and downgrade venue, performance, adoption, or community claims unless independently checked.
- Do not copy every named candidate. Keep core references once and group uncertain items as inspirations or follow-up evidence gaps.
- Do not let traceability become a second copy of every source; use a compact mapping table.
- Do not treat transient link timeouts as definitive breakage. Retry with bounded lower concurrency or a longer timeout before replacing or removing links.
- Do not let multiple children edit the final document concurrently. Children produce notes; the controller owns synthesis and final assembly.
