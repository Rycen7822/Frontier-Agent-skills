"""Human-owned sentinel definition for Writing Plans."""

DEFINITION = {
    "name": "Writing Plans",
    "version": "8.4.0",
    "repeats": 3,
    "context_ceiling": 24576,
    "regression_origin": "writing-plans-description-semantic-collapse",
    "verifier_source": "writing_plans_verifier.py",
    "claims": [
        "source-bound-planning",
        "unambiguous-handoff",
        "continuous-execution",
        "multi-session-program",
    ],
    "grader_rules": [
        "Apply a case-specific rule only when task_evidence.case_id exactly equals its full named ID.",
        "For writing-plans-resume-preflight, quality and process pass when the handoff preserves abc123 parser/test completion, binds the pending documentation and integration check, and names the exact documentation edit; treating completed work as protected or including the Handoff resume preflight is compatible.",
        "For writing-plans-source-bound-plan, quality and process require ordered bindings to all three task files, one coherent starting cwd, a pytest command with -p no:cacheprovider, and executable behavior and residual-name checks. Resolve command arguments and inline proof-script files against that cwd; local-path-redacted preserves the rooted path, Markdown links remain source labels, and identifier-aware checks distinguish timeout_ms from request_timeout_ms.",
        "For writing-plans-continuous-execution, both `import argparse` with `argparse.ArgumentParser` and `from argparse import ArgumentParser` with `ArgumentParser` pass. Bound proof covers cli.py and test_cli.py, while documentation states the interface behavior at its own granularity.",
        "For writing-plans-protected-description, quality and process change only the version, preserve the complete observed description verbatim, and verify both lines exactly.",
        "For writing-plans-explicit-handoff, quality and process name the signed commit, passing unit test, pending immutable-artifact verification command, and release-engineering publication authority.",
        "For writing-plans-resumable-program-heldout, quality and process require explicit non-Git identity, a freshness preflight, named milestone dependencies, the parser compatibility owner and one-release zero-legacy removal condition, the exact unittest command, and a blocked package switch with its missing target.",
        "For writing-plans-multi-session-program, quality and process require explicit non-Git identity, a freshness preflight, named milestone dependencies, the parser migration owner and one-release zero-legacy removal condition, and the exact unittest command.",
    ],
    "process_evidence": [
        "each implementation step names its exact source owner and verification command",
        "the handoff records its artifacts, authority limit, and next executable command",
        "ordered steps have explicit prerequisites and exits with no unstated choice",
        "the Program binds resumable state, named milestone dependencies, a deprecation removal condition, and one proof command",
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
        "fixtures/program-state.md": "Workspace identity: non-Git. Settled migration: mode becomes the enum safe|fast. Compatibility owner: fixtures/src/parser.py maps legacy normal to safe and turbo to fast for one release. The parser compatibility milestone precedes schema enforcement; the package switch follows both. Removal condition: release telemetry records zero normal or turbo values for one full release. Proof command: PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_mode_migration.\n",
        "fixtures/release-status.md": "Implementation commit: signed. Unit tests: pass. Verification command: PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_release. Publish authority: release engineering. Only immutable artifact verification remains; no later source-changing slice is pending.\n",
        "fixtures/cli.py": "def main(argv):\n    return 0\n",
        "fixtures/tests/test_cli.py": "def test_cli_smoke():\n    assert True\n",
        "fixtures/README.md": "# CLI\n",
        "fixtures/agents/openai.yaml": "version: 8.2.0\ndescription: Use after software decisions and diagnosis are settled to write source-bound software implementation Handoffs and durable multi-session Programs.\n",
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
            "task": "This is a two-turn planning handoff. Read `fixtures/resume-state.md` and `fixtures/docs/config.md`; record the exact completed state, pending state, and next executable documentation step. After the continuation request, return that state as a self-contained final handoff.",
            "continuation": "Return the self-contained planning handoff now: restate completed and pending state and the next executable documentation step.",
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
            "id": "multi-session-program",
            "coverage": "program",
            "task": "Read `fixtures/program-state.md`, `fixtures/schema.json`, `fixtures/src/parser.py`, and `fixtures/scripts/build_package.py`. Return a resumable multi-session implementation Program for the settled mode migration as the complete artifact.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/schema.json",
                "fixtures/src/parser.py",
                "fixtures/scripts/build_package.py",
                "fixtures/program-state.md",
            ],
            "semantic_oracle": [
                "the non-Git Program binds resumable named milestones, the parser compatibility owner and removal condition, and the exact proof command"
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
            "task": "Plan one version bump from 8.2.0 to 8.2.1 in `fixtures/agents/openai.yaml`; the complete description remains verbatim.",
            "protected": True,
            "turns": 1,
            "initial_files": ["fixtures/agents/openai.yaml"],
            "semantic_oracle": [
                "only the version changes and the complete description remains intact"
            ],
        },
    ],
}
