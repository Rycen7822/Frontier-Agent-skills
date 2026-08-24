"""Prospectively frozen 48-case Skill Evaluator confirmatory definition."""

STRATA = (
    ("deterministic-validation", "deterministic-first validation", "skill-evaluator/SKILL.md#deterministic-first"),
    ("analyzer-exit", "analyzer acceptable-exit contract", "skill-evaluator/SKILL.md#analysis"),
    ("cli-schema-owner", "CLI schema diagnosis and owner selection", "skill-evaluator/SKILL.md#levels"),
    ("comparison-class", "level ownership and transition-versus-revision classification", "skill-evaluator/SKILL.md#comparison"),
    ("authority-boundary", "no-reviewer and evidence-authority protection", "skill-evaluator/SKILL.md#authority"),
    ("negative-control", "adversarial negative controls and protected failure handling", "skill-evaluator/SKILL.md#fail-closed"),
)


def _definition() -> dict:
    fixtures: dict[str, str] = {}
    cases: list[dict] = []
    lineage: list[dict] = []
    for stratum_index, (stratum, requirement, source) in enumerate(STRATA, start=1):
        for ordinal in range(1, 9):
            shape = "ordinary" if ordinal <= 4 else "boundary"
            slug = f"confirmatory-{stratum}-{ordinal:02d}"
            fixture = f"fixtures/{slug}.md"
            marker = f"SE-C{stratum_index}-{ordinal:02d}"
            fixtures[fixture] = (
                f"Normative source: {source}\n"
                f"Requirement: {requirement}\n"
                f"Input shape: {shape}\n"
                f"Independent marker: {marker}\n"
                "Treat the supplied facts as authoritative and return a bounded diagnosis.\n"
            )
            task = (
                f"Read `{fixture}`. Apply the named Skill Evaluator requirement to "
                f"the {shape} input and return a concise diagnosis that identifies "
                f"the controlling evidence owner and preserves marker `{marker}`."
            )
            protected = shape == "boundary"
            cases.append({
                "id": slug,
                "coverage": stratum,
                "task": task,
                "protected": protected,
                "turns": 1,
                "initial_files": [fixture],
                "semantic_oracle": [
                    f"applies {requirement}",
                    f"preserves {marker}",
                ],
            })
            lineage.append({
                "case_id": f"skill-evaluator-{slug}",
                "stratum": stratum,
                "input_shape": shape,
                "normative_requirement": requirement,
                "normative_source": source,
                "fixture": fixture,
                "deterministic_oracle": f"terminal envelope is valid and marker {marker} remains attributable",
                "model_grade_required": True,
                "protected_boundary": protected,
                "independence": f"unique fixture, prompt marker, and case ID {marker}",
            })
    return {
        "name": "Skill Evaluator",
        "version": "5.0.0",
        "repeats": 3,
        "context_ceiling": 28672,
        "minimum_baseline_failure_cases": 2,
        "regression_origin": "prospective-se-confirmatory-v1",
        "claims": [
            "level-selection",
            "deterministic-first",
            "evidence-qualified-comparison",
        ],
        "grader_rules": [
            "Judge only the case-specific normative source, fixture facts, and requested bounded diagnosis.",
            "Require the answer to preserve the supplied independent marker and identify a controlling evidence owner.",
            "Do not infer hidden execution, reviewer activity, or external effects from prose.",
        ],
        "process_evidence": [
            "the least expensive valid evidence owner is identified",
            "deterministic facts are closed before semantic judgment",
            "unsupported authority is not inferred",
        ],
        "fixtures": fixtures,
        "cases": cases,
        "case_lineage": lineage,
    }


DEFINITION = _definition()
