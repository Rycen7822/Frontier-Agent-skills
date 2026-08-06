"""Human-owned sentinel definition for Writing Plans."""

DEFINITION = {
    "name": "Writing Plans",
    "version": "8.2.3",
    "context_ceiling": 24576,
    "regression_origin": "writing-plans-description-semantic-collapse",
    "verifier_source": "writing_plans_verifier.py",
    "claims": [
        "source-bound-planning",
        "unambiguous-handoff",
        "continuous-execution",
    ],
    "grader_rules": [
        "For writing-plans-explicit-handoff-heldout, quality and process require a minimal State, Next action, and Proof contract, the exact bound unittest command, the release-engineering publication boundary, and explicit omission of Resume because only immutable artifact verification remains.",
    ],
    "process_evidence": [
        "each implementation step names its exact source owner and verification command",
        "the handoff records its artifacts, authority limit, and next executable command",
        "ordered steps have explicit prerequisites and exits with no unstated choice",
    ],
    "fixtures": {
        "fixtures/src/config.py": "timeout_ms = 30000\n",
        "fixtures/src/client.py": "from .config import timeout_ms\n\ndef request():\n    return timeout_ms\n",
        "fixtures/tests/test_client.py": "from src.client import request\n\ndef test_timeout():\n    assert request() == 30000\n",
        "fixtures/resume-state.md": "Commit abc123 added the parser and unit tests. Pending: docs/config.md and the integration check.\n",
        "fixtures/docs/config.md": "# Configuration\n\nParser configuration is not yet documented.\n",
        "fixtures/schema.json": '{"type": "object", "properties": {"mode": {"type": "string"}}}\n',
        "fixtures/src/parser.py": "def parse(value):\n    return value.strip()\n",
        "fixtures/scripts/build_package.py": "def build():\n    return 'package'\n",
        "fixtures/release-status.md": "Implementation commit: signed. Unit tests: pass. Verification command: PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_release. Publish authority: release engineering. Only immutable artifact verification remains; no later source-changing slice is pending.\n",
        "fixtures/cli.py": "def main(argv):\n    return 0\n",
        "fixtures/tests/test_cli.py": "def test_cli_smoke():\n    assert True\n",
        "fixtures/README.md": "# CLI\n",
        "fixtures/agents/openai.yaml": "version: 8.2.0\ndescription: Write source-bound software implementation Handoffs and multi-session Programs from settled decisions; not diagnosis or execution.\n",
    },
    "cases": [
        {
            "id": "source-bound-plan",
            "coverage": "source-bound",
            "task": "Plan the rename `timeout_ms` to `request_timeout_ms` using `fixtures/src/config.py`, `fixtures/src/client.py`, and `fixtures/tests/test_client.py`. Bind every step to exact files and checks.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/src/config.py",
                "fixtures/src/client.py",
                "fixtures/tests/test_client.py",
            ],
            "semantic_oracle": [
                "definition, consumer, and test owners are ordered with exact checks"
            ],
        },
        {
            "id": "resume-preflight",
            "coverage": "resume-preflight",
            "task": "This is a two-turn planning handoff. Read `fixtures/resume-state.md` and `fixtures/docs/config.md`; record completed and pending state and the next executable documentation step without repeating completed work or editing files. After the continuation request, return that state as a self-contained final handoff.",
            "continuation": "Return the self-contained planning handoff now: restate completed and pending state and the next executable documentation step. Do not perform the source change.",
            "protected": False,
            "turns": 2,
            "initial_files": [
                "fixtures/resume-state.md",
                "fixtures/docs/config.md",
            ],
            "semantic_oracle": [
                "abc123 work remains complete and documentation is the next source change"
            ],
        },
        {
            "id": "proof-owner",
            "coverage": "proof-owner",
            "task": "Using `fixtures/schema.json`, `fixtures/src/parser.py`, and `fixtures/scripts/build_package.py`, assign one evidence owner and one measurable exit condition to each stage.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/schema.json",
                "fixtures/src/parser.py",
                "fixtures/scripts/build_package.py",
            ],
            "semantic_oracle": [
                "each stage has one exact file owner and measurable exit"
            ],
        },
        {
            "id": "explicit-handoff",
            "coverage": "handoff",
            "task": "Read `fixtures/release-status.md`. Define the exact handoff artifacts, the publish authority boundary, and the next executable verification command.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/release-status.md"],
            "semantic_oracle": ["release engineering retains publish authority"],
        },
        {
            "id": "continuous-execution",
            "coverage": "continuous-execution",
            "task": "Read `fixtures/cli.py`, `fixtures/tests/test_cli.py`, and `fixtures/README.md`, then produce consecutive implementation steps for adding `--dry-run` as a Boolean argparse option. Both `main([])` and `main([\"--dry-run\"])` must return 0 without output; unknown options must fail through argparse. Ground the plan in the observed source and include the exact import, parser calls, tests, documentation, checks, expected results, and failure exits.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/cli.py",
                "fixtures/tests/test_cli.py",
                "fixtures/README.md",
            ],
            "semantic_oracle": [
                "the exact argparse implementation, return behavior, tests, docs, and smoke verification form one executable sequence"
            ],
        },
        {
            "id": "protected-description",
            "coverage": "protected",
            "task": "Plan only a version bump from 8.2.0 to 8.2.1 in `fixtures/agents/openai.yaml`. Preserve its full description verbatim and do not shorten it.",
            "protected": True,
            "turns": 1,
            "initial_files": ["fixtures/agents/openai.yaml"],
            "semantic_oracle": [
                "only the version changes and the complete description remains intact"
            ],
        },
    ],
}
