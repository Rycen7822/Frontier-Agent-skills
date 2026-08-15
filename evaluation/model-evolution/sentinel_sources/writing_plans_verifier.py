#!/usr/bin/env python3
"""Deterministic envelope and fully mechanical case checks for Writing Plans."""

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from verify_common import emit, terminal_checks  # noqa: E402


SOURCE_BOUND_PATHS = (
    "fixtures/src/config.py",
    "fixtures/src/client.py",
    "fixtures/tests/test_client.py",
)
CASE_PATHS = {
    "source-bound-plan": frozenset(SOURCE_BOUND_PATHS),
    "resume-preflight": frozenset({
        "fixtures/resume-state.md",
        "fixtures/docs/config.md",
    }),
    "continuous-execution": frozenset({
        "fixtures/cli.py",
        "fixtures/tests/test_cli.py",
        "fixtures/README.md",
    }),
    "protected-description": frozenset({"fixtures/agents/openai.yaml"}),
    "explicit-handoff": frozenset({"fixtures/release-status.md"}),
}
DESCRIPTION = (
    "description: Use after software decisions and diagnosis are settled to write "
    "source-bound software implementation Handoffs and durable multi-session Programs."
)
DESCRIPTION_VALUE = DESCRIPTION.removeprefix("description: ")


def _case_id(workspace: dict) -> str | None:
    initial = workspace.get("initial")
    if not isinstance(initial, list):
        return None
    paths = {
        item.get("path")
        for item in initial
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    fixture_paths = frozenset(path for path in paths if path.startswith("fixtures/"))
    return next(
        (case_id for case_id, expected in CASE_PATHS.items() if fixture_paths == expected),
        None,
    )


def _paired_checks(passed: bool, label: str) -> dict[str, tuple[bool, str]]:
    observation = (
        f"the final plan satisfies the exact {label} contract"
        if passed
        else f"the exact {label} contract is incomplete or contradictory"
    )
    return {
        "task-quality-check": (passed, observation),
        "task-process-check": (passed, observation),
    }


def _action_position(answer: str, path: str, actions: tuple[str, ...]) -> int:
    for match in re.finditer(re.escape(path), answer):
        start = answer.rfind("\n", 0, match.start()) + 1
        end = answer.find("\n", match.end())
        line = answer[start:] if end < 0 else answer[start:end]
        if any(action in line.lower() for action in actions):
            return match.start()
    return -1


def _observed_mapping(
    answer: str,
    *,
    path: str,
    line_number: int,
    role: str,
    old: str,
    new: str,
) -> bool:
    owner = f"{path}:{line_number}"
    return any(
        owner in line and role in line.lower() and old in line and new in line
        for line in answer.splitlines()
    )


def _proof_only_position(answer: str, path: str, *, after: int) -> int:
    for match in re.finditer(re.escape(path), answer):
        if match.start() <= after:
            continue
        start = answer.rfind("\n", 0, match.start()) + 1
        end = answer.find("\n", match.end())
        line = (answer[start:] if end < 0 else answer[start:end]).lower()
        if any(term in line for term in (
            "leave",
            "do not",
            "make no edit",
            "check",
            "preserve",
            "proof-only",
            "proof only",
            "python -m pytest",
        )):
            return match.start()
        if "unchanged" in line and not any(
            term in line for term in ("edit", "change", "update", "rename")
        ):
            return match.start()
    return -1


def _asserted_collection(
    answer: str,
    literal: str,
    relation: str,
) -> tuple[str, int] | None:
    pattern = re.compile(
        rf"assert\s+(?P<subject>['\"]{re.escape(literal)}['\"]|[A-Za-z_]\w*)"
        rf"\s+{relation}\s+(?P<collection>[A-Za-z_]\w*)",
    )
    for match in pattern.finditer(answer):
        subject = match.group("subject")
        if subject[0] in "'\"" or re.search(
            rf"\b{re.escape(subject)}\s*=\s*['\"]{re.escape(literal)}['\"]",
            answer[:match.start()],
        ):
            return match.group("collection"), match.start()
    return None


def _source_bound_checks(answer: str) -> dict[str, tuple[bool, str]]:
    edit_actions = ("edit", "change", "update", "replace", "rename")
    config_start = _action_position(answer, SOURCE_BOUND_PATHS[0], edit_actions)
    client_start = _action_position(answer, SOURCE_BOUND_PATHS[1], edit_actions)
    test_start = _proof_only_position(
        answer,
        SOURCE_BOUND_PATHS[2],
        after=client_start,
    )
    ordered = (
        min(config_start, client_start, test_start) >= 0
        and config_start < client_start < test_start
    )
    config = answer[config_start:client_start] if ordered else ""
    client = answer[client_start:test_start] if ordered else ""
    test = answer[test_start:] if ordered else ""
    normalized_test = test.replace("`", "")
    behavior_bound = bool(re.search(
        r"request\(\)\s+(?:==\s*|(?:(?:still|continues(?:\s+to)?)\s+)?return(?:s|ing)?\s+)30000",
        normalized_test,
    ))
    config_bound = bool(
        "timeout_ms = 30000" in config and "request_timeout_ms" in config
    ) or _observed_mapping(
        answer,
        path=SOURCE_BOUND_PATHS[0],
        line_number=1,
        role="",
        old="timeout_ms = 30000",
        new="request_timeout_ms = 30000",
    )
    import_bound = bool(
        "from .config import timeout_ms" in client
        and "from .config import request_timeout_ms" in client
    ) or bool(
        _observed_mapping(
            answer,
            path=SOURCE_BOUND_PATHS[1],
            line_number=1,
            role="imported symbol",
            old="timeout_ms",
            new="request_timeout_ms",
        ) and (
            "from .config import request_timeout_ms" in answer
            or r"from \.config import request_timeout_ms" in answer
        )
    )
    return_bound = bool(
        "return timeout_ms" in client and "return request_timeout_ms" in client
    ) or bool(
        _observed_mapping(
            answer,
            path=SOURCE_BOUND_PATHS[1],
            line_number=4,
            role="returned symbol",
            old="timeout_ms",
            new="request_timeout_ms",
        ) and "return request_timeout_ms" in answer
    )
    misowned_assignment = any(
        SOURCE_BOUND_PATHS[1] in line and "request_timeout_ms = 30000" in line
        for line in answer.splitlines()
    )
    quality = bool(
        ordered
        and config_bound
        and "request_timeout_ms = 30000" in answer
        and "return timeout_ms" not in config
        and "return request_timeout_ms" not in config
        and import_bound
        and return_bound
        and not misowned_assignment
        and (behavior_bound or ("calls `request()`" in test and "asserts `30000`" in test))
    )

    lower = answer.lower()
    root_bound = any(
        marker in lower
        for marker in (
            "starting cwd: `<workspace>`",
            "starting directory: `<workspace>`",
            "from `<workspace>`",
            "work from `<workspace>`",
            "run commands from `<workspace>`",
        )
    ) or "repository root" in lower or "workspace root" in lower or (
        f"<workspace>/{SOURCE_BOUND_PATHS[0]}" in lower
    )
    fixtures_bound = any(
        marker in lower
        for marker in (
            "starting cwd: `<workspace>/fixtures`",
            "starting directory: `<workspace>/fixtures`",
            "from `<workspace>/fixtures`",
            "work from `<workspace>/fixtures`",
            "run commands from `<workspace>/fixtures`",
        )
    )
    pytest_lines = [
        line for line in answer.splitlines() if "python -m pytest" in line
    ]
    root_pytest = any(
        "PYTHONPATH=fixtures" in line
        and "-p no:cacheprovider" in line
        and "fixtures/tests/test_client.py" in line
        for line in pytest_lines
    )
    fixtures_pytest = any(
        "PYTHONPATH=" not in line
        and "-p no:cacheprovider" in line
        and "fixtures/tests/test_client.py" not in line
        and "tests/test_client.py" in line
        for line in pytest_lines
    )
    old_absent = _asserted_collection(answer, "timeout_ms", r"not\s+in")
    new_present = _asserted_collection(answer, "request_timeout_ms", "in")
    old_absence = old_absent or re.search(
        r"assert\s+not\s+any\s*\([\s\S]{0,400}?==\s*['\"]timeout_ms['\"]",
        answer,
    ) or re.search(
        r"['\"]timeout_ms['\"]\s+not\s+in\s+[A-Za-z_]\w*",
        answer,
    )
    new_presence = new_present or re.search(
        r"assert\s+any\s*\([\s\S]{0,400}?==\s*['\"]request_timeout_ms['\"]",
        answer,
    ) or re.search(
        r"\.count\([\s\S]{0,160}?['\"]request_timeout_ms['\"][\s\S]{0,80}?\)\s*==\s*[1-9]\d*",
        answer,
    )
    extractor = (
        ("ast.parse" in answer and "ast.walk" in answer)
        or (
            ("generate_tokens" in answer or "tokenize.tokenize" in answer)
            and (
                re.search(
                    r"\b[A-Za-z_]\w*\.type\s*==\s*(?:tokenize\.)?NAME\b",
                    answer,
                )
                or ".isidentifier()" in answer
            )
        )
    )
    python_identifier_aware = bool(
        old_absence
        and new_presence
        and extractor
        and (not old_absent or not new_present or old_absent[0] == new_present[0])
    )
    old_position = old_absent[1] if old_absent else (
        old_absence.start() if old_absence else -1
    )
    residual_start = answer.rfind("python - <<", 0, old_position)
    residual_end = answer.find("```", old_position)
    residual = (
        answer[residual_start:residual_end]
        if residual_start >= 0 and residual_end > residual_start
        else ""
    )
    if not residual and old_position >= 0:
        line_start = answer.rfind("\n", 0, old_position) + 1
        line_end = answer.find("\n", old_position)
        residual = answer[line_start:line_end if line_end >= 0 else len(answer)]
    root_paths = all(
        f'"{path}"' in residual or f"'{path}'" in residual
        for path in SOURCE_BOUND_PATHS
    )
    fixture_paths = all(
        f'"{path}"' in residual or f"'{path}'" in residual
        for path in ("src/config.py", "src/client.py", "tests/test_client.py")
    )
    old_rg_line = next(
        (
            line
            for line in answer.splitlines()
            if "\\btimeout_ms\\b" in line
            and all(path in line for path in SOURCE_BOUND_PATHS)
        ),
        "",
    )
    old_rg_absent = old_rg_line.lstrip().startswith("! rg ") or bool(
        re.search(r"\bif\s+rg\b.*\bthen\s+exit\s+1\b", old_rg_line)
    )
    python_process = python_identifier_aware and (
        (root_bound and root_pytest and root_paths)
        or (fixtures_bound and fixtures_pytest and fixture_paths)
    )
    rg_process = bool(
        quality
        and old_rg_absent
        and root_pytest
        and (root_bound or all(path in old_rg_line for path in SOURCE_BOUND_PATHS))
    )
    process = len(pytest_lines) == 1 and (
        python_process or rg_process
    )
    return {
        "task-quality-check": (
            quality,
            "ordered config, consumer, and test bindings preserve the exact rename behavior"
            if quality
            else "the exact source-bound rename ownership or behavior is incomplete",
        ),
        "task-process-check": (
            process,
            "cwd-bound no-cache pytest and identifier-aware residual checks are executable"
            if process
            else "the cwd, no-cache pytest, or identifier-aware residual check is incomplete",
        ),
    }


def _fixed_case_checks(case_id: str, answer: str) -> dict[str, tuple[bool, str]]:
    lower = answer.lower()
    if case_id == "continuous-execution":
        required = (
            "fixtures/cli.py",
            "fixtures/tests/test_cli.py",
            "fixtures/readme.md",
            "argumentparser",
            "--dry-run",
            "store_true",
            "parse_args(argv)",
            "return 0",
            "pytest.raises(systemexit)",
            ".value.code == 2",
            "-p no:cacheprovider",
        )
        pytest_lines = [
            line for line in answer.splitlines() if "python -m pytest" in line
        ]
        import_bound = len(pytest_lines) == 1 and (
            (
                "from cli import main" in answer
                and "PYTHONPATH=fixtures" in pytest_lines[0]
            )
            or (
                "from fixtures.cli import main" in answer
                and (
                    "PYTHONPATH=" not in pytest_lines[0]
                    or re.search(r"(?:^|\s)PYTHONPATH=\.(?:\s|$)", pytest_lines[0])
                )
            )
        )
        capsys_output = all(
            f"captured.{stream} == \"\"" in answer
            or f"captured.{stream} == ''" in answer
            for stream in ("out", "err")
        )
        redirected_output = all(term in answer for term in (
            "redirect_stdout",
            "redirect_stderr",
            "stdout.getvalue() == \"\"",
            "stderr.getvalue() == \"\"",
        ))
        output_bound = ("readouterr()" in answer and capsys_output) or redirected_output
        invocation_bound = "main([])" in answer or (
            "pytest.mark.parametrize" in answer and "[]" in answer
        )
        passed = (
            all(term in lower for term in required)
            and import_bound
            and output_bound
            and invocation_bound
        )
        return _paired_checks(passed, "argparse implementation/test/documentation")

    if case_id == "protected-description":
        required = (
            "fixtures/agents/openai.yaml",
            "version: 8.2.0",
            "version: 8.2.1",
        )
        joined_literals = re.sub(r"([\"'])\s*\n\s*\1", "", answer)
        description_proof = DESCRIPTION in joined_literals or (
            'line.startswith("description:")' in answer
            and "descriptions ==" in answer
            and DESCRIPTION_VALUE in answer
        )
        exact_proof = (
            ("python" in lower and "assert" in answer and ".read_text(" in answer)
            or ("sed -n '1p'" in answer and "sed -n '2p'" in answer)
        )
        return _paired_checks(
            all(term in answer for term in required)
            and description_proof
            and exact_proof,
            "version-and-description",
        )

    if case_id == "explicit-handoff":
        required = (
            "signed implementation commit",
            "passing",
            "pythondontwritebytecode=1 python -m unittest tests.test_release",
            "release engineering",
            "immutable",
            "artifact",
            "verification",
        )
        pending = "pending" in lower or "remains" in lower
        authority = "publish" in lower or "publication" in lower
        return _paired_checks(
            all(term in lower for term in required) and pending and authority,
            "release-handoff",
        )

    if case_id == "resume-preflight":
        required = (
            "abc123",
            "parser",
            "unit tests",
            "fixtures/docs/config.md",
            "integration check",
            "# configuration",
            "parser configuration is not yet documented.",
        )
        replacement = "replac" in lower
        return _paired_checks(
            all(term in lower for term in required)
            and replacement
            and "attestation" in lower
            and "combined preflight" in lower,
            "resume documentation handoff",
        )

    raise ValueError(f"unsupported deterministic Writing Plans case: {case_id}")


def main() -> int:
    result = json.loads(Path("result.json").read_text(encoding="utf-8"))
    checks = terminal_checks(result)
    workspace_path = Path("workspace/workspace-evidence.json")
    answer_path = Path("workspace/final-answer.md")
    if workspace_path.is_file() and answer_path.is_file():
        workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
        case_id = _case_id(workspace)
        if case_id == "source-bound-plan":
            checks.update(_source_bound_checks(answer_path.read_text(encoding="utf-8")))
        elif case_id is not None:
            checks.update(
                _fixed_case_checks(case_id, answer_path.read_text(encoding="utf-8")),
            )
    return emit(
        "writing-plans",
        checks,
        evidence_artifacts={
            "task-quality-check": "workspace/final-answer.md",
            "task-process-check": "workspace/final-answer.md",
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
