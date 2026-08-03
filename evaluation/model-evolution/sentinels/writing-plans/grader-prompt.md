# Blinded sentinel grader for writing-plans

Judge only the supplied candidate evidence. Score `quality-check` for a complete, usable result and `process-check` for faithful application of the declared contract: source-bound-planning, unambiguous-handoff, continuous-execution. When evidence is insufficient, set `uncertainty` to `high`; the required boolean is ignored for that abstention. Do not infer tool use, routing, file changes, or safety from prose.
