"""Human-owned sentinel definition for Writing Plans."""

DEFINITION = {
    "name": "Writing Plans",
    "version": "8.2.0",
    "context_ceiling": 24576,
    "regression_origin": "writing-plans-description-semantic-collapse",
    "claims": [
        "source-bound-planning",
        "unambiguous-handoff",
        "continuous-execution",
    ],
    "process_evidence": [
        "each implementation step names its exact source owner and verification command",
        "the handoff records its artifacts, authority limit, and next executable command",
        "ordered steps have explicit prerequisites and exits with no unstated choice",
    ],
    "cases": [
        (
            "source-bound-plan",
            "source-bound",
            "Plan a rename of `timeout_ms` to `request_timeout_ms` owned by `src/config.py`, with consumers in `src/client.py` and tests in `tests/test_client.py`. Bind every step to exact files and checks.",
            False,
            1,
        ),
        (
            "resume-preflight",
            "resume-preflight",
            "Commit `abc123` already added the parser and its unit tests; only `docs/config.md` and the integration check remain. Record completed and pending state, then give the next executable step without repeats.",
            False,
            2,
        ),
        (
            "proof-owner",
            "proof-owner",
            "For stages schema update, parser update, and release packaging, assign one evidence owner and one measurable exit condition to each. The owners are `schema.json`, `src/parser.py`, and `scripts/build_package.py`.",
            False,
            1,
        ),
        (
            "explicit-handoff",
            "handoff",
            "The implementation commit is signed and unit tests pass, but publishing is owned by release engineering. Define the exact handoff artifacts, authority boundary, and next executable verification command.",
            False,
            1,
        ),
        (
            "continuous-execution",
            "continuous-execution",
            "Produce consecutive steps to add `--dry-run` in `cli.py`, cover it in `tests/test_cli.py`, update `README.md`, and run the existing CLI smoke command. Include prerequisites and exits without unstated choices.",
            False,
            1,
        ),
        (
            "protected-description",
            "protected",
            "Plan a metadata-only version bump in `agents/openai.yaml` from `8.1.0` to `8.1.1` while preserving this description verbatim: 'Use when a plan must bind exact source owners, verification commands, handoff authority, and consecutive execution steps.'",
            True,
            1,
        ),
    ],
}
