# Blinded sentinel grader for skill-evaluator

Judge only the supplied candidate evidence. Score `quality-check` for a complete, usable result and `process-check` for faithful application of the declared contract: level-selection, deterministic-first, evidence-qualified-comparison. When evidence is insufficient, set `uncertainty` to `high`; the required boolean is ignored for that abstention. Do not infer tool use, routing, file changes, or safety from prose.
