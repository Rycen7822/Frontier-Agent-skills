"""Human-owned sentinel definition for Writing Plans."""

DEFINITION = {
    "name": "Writing Plans",
    "version": "8.2.5",
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
        "A case-specific rule applies only when task_evidence.case_id is byte-for-byte equal to the full named ID; ignore it for every shorter, longer, prefix, suffix, or semantically similar ID.",
        "For writing-plans-source-bound-plan, resolve each relative proof path against the working directory stated in that same answer even when transport replaces the concrete directory with local-path-redacted. Quality and process require ordered bindings to all three task files and an executable behavior and residual-name check; a raw substring exclusion of timeout_ms fails because request_timeout_ms contains that substring.",
        "For writing-plans-continuous-execution, exact import means a concrete valid argparse import and matching parser call. Both import argparse with argparse.ArgumentParser and from argparse import ArgumentParser with ArgumentParser satisfy it. Do not require an unbound repository-wide check or require documentation to repeat every test assertion.",
        "For writing-plans-protected-description, the observed fixture is exactly the version line and the full description line. Quality and process pass when the plan changes only the version, preserves that complete description verbatim, and verifies those two observed lines exactly; do not label that exact fixture assertion an invented file-shape requirement.",
        "For writing-plans-explicit-handoff, quality and process require the exact handoff artifacts, publication authority boundary, and next executable verification command requested by the task; do not require State, Next action, or Proof labels, or any Resume statement or omission.",
        "For writing-plans-resumable-program-heldout, quality and process require a Program with explicit non-Git identity, a freshness-bound attestation acceptance or one combined preflight for later source-changing resumption, named milestones whose dependencies cite milestone names, the parser compatibility owner and one-release zero-legacy removal condition, the exact bound unittest command, and the package switch retained as blocked because its target is absent. Reject Git checks, source execution, ordinal-only dependencies, or an unbound repository-wide check.",
        "For writing-plans-multi-session-program, quality and process require the explicit non-Git identity, a freshness-bound attestation or one combined preflight for resumption, named milestones whose dependencies cite milestone names, the parser migration owner and one-release zero-legacy removal condition, and the exact bound unittest command. Reject Git checks, source execution, ordinal-only dependencies, or an unbound repository-wide check.",
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
            "id": "multi-session-program",
            "coverage": "program",
            "task": "Read `fixtures/program-state.md`, `fixtures/schema.json`, `fixtures/src/parser.py`, and `fixtures/scripts/build_package.py`. Write a multi-session implementation Program for the settled mode migration that another session can resume safely. Do not edit files or execute the plan.",
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
