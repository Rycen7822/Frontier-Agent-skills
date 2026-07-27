from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from . import artifacts, cli, host_contract, specs, studies
from .controller_testkit import HASH, host_request


def _validator(repo: Path):
    path = repo / "skill-evaluator/scripts/validate_eval_suite.py"
    module_spec = importlib.util.spec_from_file_location(
        "frontier_host_contract_validator",
        path,
    )
    assert module_spec is not None and module_spec.loader is not None
    validator = importlib.util.module_from_spec(module_spec)
    sys.path.insert(0, str(path.parent))
    try:
        module_spec.loader.exec_module(validator)
    finally:
        sys.path.pop(0)
    return validator


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


def test_rebind_study_inputs_updates_every_host_binding() -> None:
    scenarios = [{"fixture": {"manifest": "old", "sha256": HASH}}]
    assert host_contract.rebind_scenarios(
        scenarios,
        "sha256:" + "1" * 64,
    )[0]["fixture"] == {
        "manifest": "host-manifest-v1.json",
        "sha256": "sha256:" + "1" * 64,
    }
    spec = {
        "host": {"manifest": {"sha256": HASH}},
        "suite": {
            "scenarios": {"sha256": HASH},
            "public_scenarios": {"sha256": HASH},
            "holdout": {
                "payload": {"sha256": HASH},
                "manifest": {"sha256": HASH},
            },
        },
        "graders": [
            {"type": "deterministic", "verifier": {"sha256": HASH}},
            {
                "type": "model",
                "prompt": {"sha256": HASH},
                "output_schema": {"sha256": HASH},
            },
        ],
    }
    assets = {name: "sha256:" + str(index) * 64 for index, name in enumerate(
        host_contract.HOST_ASSETS,
        2,
    )}
    rebound = host_contract.rebind_spec(
        spec,
        host_manifest_hash="sha256:" + "1" * 64,
        scenarios_hash="sha256:" + "5" * 64,
        holdout_payload_hash="sha256:" + "6" * 64,
        holdout_manifest_hash="sha256:" + "7" * 64,
        host_asset_hashes=assets,
    )
    assert rebound["graders"][0]["verifier"]["sha256"] == assets[
        "host_grader.py"
    ]
    assert rebound["graders"][1]["prompt"]["sha256"] == assets[
        "model_grader_prompt.md"
    ]


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
    validator = _validator(repo)
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


def test_quality_proof_binds_tracked_adapter(tmp_path: Path) -> None:
    repo = Path(__file__).parents[2]
    fixture = repo / "tests/fixtures/skill_evaluator"
    spec = json.loads(
        (fixture / "spec-v5.json").read_text(encoding="utf-8")
    )
    scenarios = [
        json.loads(line)
        for line in (fixture / "scenarios-v1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    scenarios[0]["execution_context"]["context_sources"] = [
        "fixture-boundary"
    ]
    (tmp_path / "host").mkdir()
    artifacts.write_json(
        tmp_path / "host/adapter-binding.json",
        {"binding": "tracked"},
    )
    proof = studies.quality_proof(
        spec=spec,
        scenarios=scenarios,
        study_root=tmp_path,
        validator=_validator(repo),
    )
    assert proof["leakage_probes"][0]["artifact"]["path"] == (
        "host/adapter-binding.json"
    )
