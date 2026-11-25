# Segmented assembly

Use the [Markdown assembler](../scripts/assemble_markdown.py) when independently maintained sections form one final document. Keep draft pieces in the task's existing workspace, with coherent edit boundaries. Resolve `LONG_DOCUMENT_SKILL_ROOT` to the directory containing this skill's `SKILL.md`.

Supply every section explicitly in final order:

```bash
python3 "$LONG_DOCUMENT_SKILL_ROOT/scripts/assemble_markdown.py" \
  --section path/to/00_summary.md \
  --section path/to/01_design.md \
  --output path/to/final.md
```

The assembler validates inputs before writing, preserves section bytes except trailing blank lines, separates sections with one blank line and ends with one LF. Publication is atomic; identical output is a zero-write no-op. Verify assembly with the same ordered arguments plus `--check`.

To check Markdown prose without assembly, use:

```bash
python3 "$LONG_DOCUMENT_SKILL_ROOT/scripts/assemble_markdown.py" \
  --check-source-style path/to/final.md
```

This validates source style without rewriting it. Successful output contains `status` and `bytes`; it does not establish factual correctness.

Review the final document for coverage, source support, cross-references and consistency. Repair the owning draft section and reassemble when pieces remain canonical; editing only the assembled output would lose the repair on the next build. Directly written documents need no section files or assembly proof.
