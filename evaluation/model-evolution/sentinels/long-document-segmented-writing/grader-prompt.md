# Blinded sentinel grader for long-document-segmented-writing

Judge only the supplied candidate evidence. Score `quality-check` for a complete, usable result. Score `process-check` only against the declared mechanism relevant to the stated task; do not require unrelated mechanisms from this contract list: segmented-writing, compaction-recovery, whole-draft-review. When evidence is insufficient, set `uncertainty` to `high`; the required boolean is ignored for that abstention. Do not infer tool use, routing, file changes, or safety from prose.
