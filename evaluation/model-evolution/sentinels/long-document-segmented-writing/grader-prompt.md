# Blinded sentinel grader for long-document-segmented-writing

Judge only the supplied candidate evidence. Score `quality-check` for a complete, usable result and `process-check` for faithful application of the declared contract: segmented-writing, compaction-recovery, whole-draft-review. When evidence is insufficient, set `uncertainty` to `high`; the required boolean is ignored for that abstention. Do not infer tool use, routing, file changes, or safety from prose.
