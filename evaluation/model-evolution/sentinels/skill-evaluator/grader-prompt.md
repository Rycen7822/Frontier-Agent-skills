# Blinded sentinel grader for skill-evaluator

Judge only the supplied candidate evidence. Score `quality-check` for a complete, usable result. Score `process-check` against every declared mechanism the stated task marks as relevant; do not require mechanisms from this contract list that the task does not mark as relevant: level-selection, deterministic-first, evidence-qualified-comparison. When evidence is insufficient, set `uncertainty` to `high`; the required boolean is ignored for that abstention. Do not infer tool use, routing, file changes, or safety from prose.
