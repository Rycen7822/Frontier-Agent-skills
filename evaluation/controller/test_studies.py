from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from . import artifacts, cli, host_contract, host_grader, specs
from .controller_testkit import HASH, host_request


def test_cli_accepts_manifest_bound_codex_runtime() -> None:
    parsed = cli.build_parser().parse_args([
        "host",
        "--host-manifest",
        "host.json",
        "--codex-bin",
        "/opt/codex",
        "--codex-bin-sha256",
        HASH,
    ])
    assert parsed.command == "host"


def test_bound_host_grader_projects_declared_assertions() -> None:
    result = {
        "terminal_status": "completed",
        "treatment_error": None,
        "refusal": False,
        "timeout": False,
        "protocol_error": None,
        "assertions": [
            {
                "claim": claim,
                "artifact": None,
                "locally_verifiable": True,
            }
            for claim in ("outcome-complete", "safety-preserved")
        ],
    }
    grade = host_grader.grade(
        result,
        ["outcome-check", "safety-check"],
    )
    assert grade["overall_pass"] is True
    assert grade["score"] == 100


def test_materialized_host_uses_tracked_cli_without_controller_copy(
    tmp_path: Path,
) -> None:
    repo = Path(__file__).parents[2]
    study = tmp_path / "study"
    for arm in ("candidate", "prior"):
        (study / arm / "software-quality-workflows").mkdir(parents=True)
        artifacts.atomic_write(
            study / arm / "software-quality-workflows/SKILL.md",
            b"---\nname: software-quality-workflows\n---\n",
        )
    runtime = {
        "executable": {
            "path": str(Path(sys.executable).resolve()),
            "sha256": artifacts.file_hash(Path(sys.executable).resolve()),
        }
    }
    manifest = host_contract.materialize(
        study_root=study,
        evaluator_root=repo / "skill-evaluator",
        candidate_skill=(
            study / "candidate/software-quality-workflows/SKILL.md"
        ),
        prior_skill=study / "prior/software-quality-workflows/SKILL.md",
        package_hash=HASH,
        repository={"revision": "a" * 40, "tree": "b" * 40},
        design=specs.fixed_design("d0-sqw"),
        codex_runtime=runtime,
        controller_content_hash=HASH,
    )
    host_files = {
        path.name for path in (study / "host").iterdir() if path.is_file()
    }
    assert host_files == {
        "adapter-binding.json",
        "host_grader.py",
        "model_grader_prompt.md",
        "model_judgment.schema.json",
    }
    assert not any(
        (study / "host" / name).exists()
        for name in ("cli.py", "host.py", "workspace.py")
    )
    assert manifest["command"]["argv"][:4] == [
        "python3",
        "-m",
        "evaluation.controller.cli",
        "host",
    ]
    assert manifest["command"]["env_allowlist"] == [
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONPATH",
    ]
    validator_path = (
        repo / "skill-evaluator/scripts/validate_eval_suite.py"
    )
    module_spec = importlib.util.spec_from_file_location(
        "frontier_host_contract_validator",
        validator_path,
    )
    assert module_spec is not None and module_spec.loader is not None
    validator = importlib.util.module_from_spec(module_spec)
    sys.path.insert(0, str(validator_path.parent))
    try:
        module_spec.loader.exec_module(validator)
    finally:
        sys.path.pop(0)
    assert validator.validate_v5_schema(
        manifest,
        "host-manifest-v1.schema.json",
        validator.load_v5_schema_registry(),
    ) == []
    cli.build_parser().parse_args(manifest["command"]["argv"][3:])

    manifest_path = study / "host-manifest-v1.json"
    artifacts.write_json(manifest_path, manifest)
    argv = [manifest["command"]["resolved_executable"]]
    for argument in manifest["command"]["argv"][1:]:
        bound = study / argument
        argv.append(str(bound.resolve()) if bound.is_file() else argument)
    argv.append("--synthetic")
    (tmp_path / "workspace").mkdir()
    result = subprocess.run(
        argv,
        cwd=tmp_path / "workspace",
        env={
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(repo),
        },
        input=artifacts.canonical_bytes(host_request("probe_capability")) + b"\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    records = [
        json.loads(line) for line in result.stdout.splitlines() if line
    ]
    assert records[-1]["terminal_status"] == "completed"
