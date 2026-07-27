from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from . import artifacts, campaign, reports, source_proof
from .controller_testkit import (
    bundle_source_tree,
    controller_tree,
    hash_value,
    initialize,
    initialize_existing,
    receipt,
    request_entry,
    reserve,
)


def test_nofollow_helper_rejects_dangling_and_intermediate_symlinks(
    tmp_path: Path,
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "middle").symlink_to(tmp_path / "real", target_is_directory=True)
    (tmp_path / "dangling").symlink_to(tmp_path / "absent")
    with pytest.raises(artifacts.StateError):
        artifacts.assert_nofollow(tmp_path / "middle" / "child")
    with pytest.raises(artifacts.StateError):
        artifacts.assert_nofollow(tmp_path / "dangling", allow_absent_leaf=True)


def test_contained_file_rejects_escape_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "value.txt").write_text("bound", encoding="utf-8")
    (root / "link").symlink_to(root / "value.txt")
    assert artifacts.contained_file(root, "value.txt", "value").read_text() == "bound"
    binding = artifacts.artifact_binding(root / "value.txt", root)
    assert artifacts.verified_artifact(root, binding, "value").name == "value.txt"
    with pytest.raises(artifacts.StateError):
        artifacts.verified_artifact(
            root,
            {**binding, "sha256": "sha256:" + "0" * 64},
            "value",
        )
    with pytest.raises(artifacts.StateError):
        artifacts.contained_file(root, "../value.txt", "value")
    with pytest.raises(artifacts.StateError):
        artifacts.contained_file(root, "link", "value")


def test_audit_inventory_hash_preserves_root_then_nested_order(
    tmp_path: Path,
) -> None:
    (tmp_path / "a").mkdir()
    files = {
        "opaque.md": b"\0",
        "z.txt": b"root\n",
        "a/nested.txt": b"nested\n",
    }
    for relative, payload in files.items():
        (tmp_path / relative).write_bytes(payload)
    rows = [
        (
            f"{relative}\ttext\t"
            f"{artifacts.raw_hash(files[relative]).removeprefix('sha256:')}\t"
        )
        for relative in ("opaque.md", "z.txt", "a/nested.txt")
    ]
    assert source_proof.audit_inventory_hash(tmp_path) == (
        artifacts.raw_hash("\n".join(rows).encode()).removeprefix("sha256:")
    )


def test_corpus_freeze_is_bound_and_no_overwrite(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    manifest = corpus / "manifest.json"
    manifest.write_text('{"bound":true}\n', encoding="utf-8")
    output = tmp_path / "freeze.json"
    first = source_proof.freeze_corpus(
        kind="formal",
        corpus_root=corpus,
        manifest_path=manifest,
        output=output,
    )
    assert first["file_count"] == 1
    with pytest.raises(source_proof.ProofError, match="already exists"):
        source_proof.freeze_corpus(
            kind="formal",
            corpus_root=corpus,
            manifest_path=manifest,
            output=output,
        )


def test_controller_closure_requires_workspace_and_rejects_extra_files(
    tmp_path: Path,
) -> None:
    root = controller_tree(tmp_path / "controller")
    sources = source_proof.controller_sources(root)
    assert {path.name for path in sources} == source_proof.CONTROLLER_FILES
    assert "workspace.py" in source_proof.CONTROLLER_FILES
    (root / "unexpected.py").write_text("extra\n", encoding="utf-8")
    with pytest.raises(source_proof.ProofError, match="extra=.*unexpected"):
        source_proof.controller_sources(root)


def test_tracked_controller_matches_frozen_inventory() -> None:
    root = Path(__file__).parent
    assert {
        path.name for path in source_proof.controller_sources(root)
    } == source_proof.CONTROLLER_FILES


def test_controller_freeze_binds_live_codex_runtime(tmp_path: Path) -> None:
    controller = controller_tree(tmp_path / "controller")
    plugin = tmp_path / "plugin"
    evaluator = tmp_path / "evaluator"
    (evaluator / "scripts").mkdir(parents=True)
    (evaluator / "scripts/analyze_runs.py").write_text(
        "pass\n",
        encoding="utf-8",
    )
    plugin.mkdir()
    (plugin / "SKILL.md").write_text("skill\n", encoding="utf-8")
    runtime_path = Path("/bin/true").resolve()
    runtime = {
        "executable": {
            "path": str(runtime_path),
            "sha256": artifacts.file_hash(runtime_path),
        }
    }
    preflight = artifacts.self_hashed({
        "schema_version": "frontier-app-server-preflight/2.0",
        "codex_runtime": runtime,
    }, "preflight_hash")
    preflight_path = tmp_path / "app-server-preflight.json"
    artifacts.write_json(preflight_path, preflight)
    corpora = {}
    for kind in ("formal", "p4"):
        path = tmp_path / f"{kind}.json"
        artifacts.write_json(path, {"kind": kind})
        corpora[kind] = path
    test_gate = {
        "argv": [
            "python",
            "-m",
            "pytest",
            *[
                f"evaluation/controller/{name}"
                for name in sorted(source_proof.CONTROLLER_FILES)
                if name.startswith("test_") and name.endswith(".py")
            ],
        ],
        "cwd": ".worktrees/frontier-5.0",
        "returncode": 0,
        "stdout_bytes": 1,
        "stdout_sha256": artifacts.canonical_hash("stdout"),
        "stderr_bytes": 0,
        "stderr_sha256": artifacts.canonical_hash("stderr"),
    }
    manifest = source_proof.freeze_controller(
        controller_root=controller,
        candidate_identity={
            "candidate_revision": "a" * 40,
            "candidate_source_tree_hash": artifacts.canonical_hash("source"),
        },
        candidate_plugin_root=plugin,
        evaluator_root=evaluator,
        app_server_preflight=preflight_path,
        codex_runtime=runtime,
        corpora=corpora,
        controller_test_gate=test_gate,
        output_root=tmp_path / "freeze",
    )
    assert manifest["app_server"]["codex_runtime"] == runtime
    assert manifest["controller_test_gate"] == test_gate
    assert reports.load_controller_manifest(
        tmp_path / "freeze/controller-manifest.json"
    ) == manifest


def test_bundle_source_hash_accepts_strict_formatted_manifest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    skills = bundle_source_tree(root)
    first = artifacts.bundle_source_hash(root, skills)
    second = artifacts.bundle_source_hash(root, skills)
    assert first == second
    assert first.startswith("sha256:")
    with pytest.raises(artifacts.StateError, match="manifest differs"):
        artifacts.bundle_source_hash(root, skills | {"missing-skill"})


def test_p4_reserved_nonterminal_request_resumes_same_id(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    initialize(attempt)
    entry = campaign.request_entry(attempt, "request-1")
    reserve(attempt, entry["request_id"])
    calls = []
    result_root = tmp_path / "result"
    result, *_ = campaign.execute_bound_entry(
        attempt_root=attempt,
        entry=entry,
        request={"request_id": entry["request_id"]},
        effect_root=result_root / "effect",
        result_root=result_root,
        effect=lambda: (
            calls.append(entry["request_id"])
            or {"terminal_status": "completed"}
        ),
    )
    assert result == {"terminal_status": "completed"}
    assert calls == ["request-1"]
    replayed, *_ = campaign.execute_bound_entry(
        attempt_root=attempt,
        entry=entry,
        request={"request_id": entry["request_id"]},
        effect_root=result_root / "effect",
        result_root=result_root,
        effect=lambda: (
            calls.append("resent")
            or {"terminal_status": "completed"}
        ),
    )
    assert replayed == result
    assert calls == ["request-1"]
    assert len(campaign.verify_ledger(attempt / "provider-ledger.jsonl")) == 1


def test_p4_custom_exception_is_terminal_and_non_retryable(
    tmp_path: Path,
) -> None:
    attempt = tmp_path / "attempt"
    initialize(attempt)
    entry = campaign.request_entry(attempt, "request-1")
    result_root = tmp_path / "result"

    def fail():
        raise RuntimeError("server overloaded; please retry")

    result, receipt_binding, *_ = campaign.execute_bound_entry(
        attempt_root=attempt,
        entry=entry,
        request={"request_id": entry["request_id"]},
        effect_root=result_root / "effect",
        result_root=result_root,
        effect=fail,
    )
    receipt_path = result_root / receipt_binding["path"]
    receipt_value = campaign.validate_native_attempt_receipt(
        artifacts.load_json(receipt_path),
    )
    assert result["terminal_status"] == "failed"
    assert receipt_value["failure_class"] is None


def test_compiled_plan_closes_scored_ledger_without_replay(
    tmp_path: Path,
) -> None:
    attempt = tmp_path / "attempt"
    required = [
        request_entry("execute-1"),
        request_entry("grade-1", request_kind="model_grade"),
    ]
    initialize(attempt, required=required)
    study = tmp_path / "study"
    study.mkdir()
    plan = artifacts.self_hashed(
        {"entries": [{"entry_id": "entry-1"}]},
        "plan_hash",
    )
    plan_path = study / "execution-plan-v1.json"
    artifacts.write_json(plan_path, plan)
    index = study / "artifacts/index.jsonl"
    runner = tmp_path / "runner.py"
    runner.write_text(
        """
import argparse
import hashlib
import json
from pathlib import Path
from evaluation.controller import campaign as imported_campaign

p = argparse.ArgumentParser()
p.add_argument("plan")
p.add_argument("--index")
p.add_argument("--entry-id")
p.add_argument("--resume", action="store_true")
a = p.parse_args()
index = Path(a.index)
receipt = index.parent / "entries/entry-1/attempt-0001/receipt.json"
receipt.parent.mkdir(parents=True)
plan = json.loads(Path(a.plan).read_text())
value = {"run": {
    "entry_id": a.entry_id,
    "plan_hash": plan["plan_hash"],
    "terminal": "completed",
    "valid": True,
}}
canonical = lambda item: json.dumps(
    item, sort_keys=True, separators=(",", ":"),
).encode()
value["receipt_hash"] = "sha256:" + hashlib.sha256(canonical(value)).hexdigest()
receipt.write_bytes(canonical(value) + b"\\n")
row = {"entry_id": a.entry_id, "receipt": {
    "path": receipt.relative_to(index.parent).as_posix(),
    "sha256": "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest(),
}}
index.write_bytes(canonical(row) + b"\\n")
""".lstrip(),
        encoding="utf-8",
    )
    arguments = {
        "attempt_root": attempt,
        "study_root": study,
        "runner_path": runner,
        "plan_path": plan_path,
        "index_path": index,
        "bindings": [{
            "entry_id": "entry-1",
            "request_ids": ["execute-1", "grade-1"],
        }],
    }
    first = campaign.execute_compiled_plan(**arguments)
    runner.unlink()
    second = campaign.execute_compiled_plan(**arguments)
    assert first == second
    assert {item["request_id"] for item in first} == {
        "execute-1",
        "grade-1",
    }
    assert len(campaign.verify_ledger(attempt / "provider-ledger.jsonl")) == 2


def test_compiled_plan_rejects_reserved_entry_without_runner_evidence(
    tmp_path: Path,
) -> None:
    attempt = tmp_path / "attempt"
    initialize(attempt)
    reserve(attempt, "request-1")
    study = tmp_path / "study"
    study.mkdir()
    plan = artifacts.self_hashed(
        {"entries": [{"entry_id": "entry-1"}]},
        "plan_hash",
    )
    plan_path = study / "execution-plan-v1.json"
    artifacts.write_json(plan_path, plan)
    with pytest.raises(
        artifacts.StateError,
        match="lacks closed runner evidence",
    ):
        campaign.execute_compiled_plan(
            attempt_root=attempt,
            study_root=study,
            runner_path=tmp_path / "unused.py",
            plan_path=plan_path,
            index_path=study / "artifacts/index.jsonl",
            bindings=[{
                "entry_id": "entry-1",
                "request_ids": ["request-1"],
            }],
        )
    unreserved = tmp_path / "unreserved"
    initialize(unreserved)
    index = study / "artifacts/index.jsonl"
    index.parent.mkdir()
    index.write_bytes(artifacts.canonical_bytes({
        "entry_id": "entry-1",
        "receipt": {},
    }) + b"\n")
    with pytest.raises(
        artifacts.StateError,
        match="lacks closed runner evidence",
    ):
        campaign.execute_compiled_plan(
            attempt_root=unreserved,
            study_root=study,
            runner_path=tmp_path / "unused.py",
            plan_path=plan_path,
            index_path=index,
            bindings=[{
                "entry_id": "entry-1",
                "request_ids": ["request-1"],
            }],
        )


def test_action_context_pins_cwd_lease_and_closes_fds(tmp_path: Path) -> None:
    original = Path.cwd()
    descriptors = set(os.listdir("/proc/self/fd"))
    with campaign.action_context(tmp_path):
        assert Path.cwd() == tmp_path
        assert (tmp_path / ".action.lease").is_file()
    assert Path.cwd() == original
    assert set(os.listdir("/proc/self/fd")) == descriptors


def test_registry_state_hash_chain_cas_and_post_read(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    state = initialize(root)
    next_state = campaign.transition(
        root,
        expected_state_hash=state["state_hash"],
        stage="r1-proof",
        status="running",
    )
    assert next_state["previous_state_hash"] == state["state_hash"]
    assert next_state["sequence"] == 1
    assert campaign.load_attempt(root)[1] == next_state
    with pytest.raises(artifacts.StateError):
        campaign.transition(
            root,
            expected_state_hash=state["state_hash"],
            stage="stale",
            status="running",
        )
    state_path = root / "stage-state.json"
    tampered = json.loads(state_path.read_text(encoding="utf-8"))
    tampered["stage"] = "tampered"
    state_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(artifacts.StateError):
        campaign.load_attempt(root)


def test_resume_complete_terminal_and_token_single_consumption(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    initialize(root)
    resumed = campaign.consume_continuation_token(root, "continue-once")
    assert resumed["continuation_token_consumed"]
    with pytest.raises(artifacts.StateError):
        campaign.consume_continuation_token(root, "continue-once")
    complete = campaign.transition(
        root,
        expected_state_hash=resumed["state_hash"],
        stage="r1-proof",
        status="complete",
    )
    with pytest.raises(artifacts.StateError):
        campaign.transition(
            root,
            expected_state_hash=complete["state_hash"],
            stage="r2",
            status="running",
        )


def test_zero_call_restart_is_once_and_preserves_attempt(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    initialize(root)
    restarted = campaign.zero_call_restart(root, next_stage="r1-restart")
    assert restarted["zero_call_restart_used"]
    assert (root / "attempt-registry.json").is_file()
    with pytest.raises(artifacts.StateError):
        campaign.zero_call_restart(root, next_stage="again")
    called = tmp_path / "called"
    initialize(called)
    reserve(called, "request-1")
    with pytest.raises(artifacts.StateError):
        campaign.zero_call_restart(called, next_stage="forbidden")


def test_manifest_entry_is_only_descriptor_and_resume_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "attempt"
    initialize(
        root,
        required=[
            request_entry("request-1"),
            request_entry("request-2", request_kind="model_grade"),
        ],
    )
    manifest = campaign.load_request_manifest(root / "request-manifest.json")
    assert manifest["budget"] == {
        "scored_call_hard_cap": 2,
        "grader_calibration_call_hard_cap": 0,
        "reviewer_calibration_call_hard_cap": 0,
        "scheduled_provider_calls": 2,
        "retry_provider_call_cap": 0,
        "provider_call_hard_cap": 2,
    }
    row = reserve(root, "request-1")
    assert campaign.verify_ledger(root / "provider-ledger.jsonl") == [row]
    assert reserve(root, "request-1") == row
    for request_id, entry_hash in (
        ("request-1", hash_value("9")),
        ("outside-manifest", hash_value("9")),
    ):
        with pytest.raises(artifacts.StateError):
            campaign.reserve_provider_request(
                root,
                request_id=request_id,
                entry_hash=entry_hash,
            )


def test_conditional_pair_requires_closed_official_transient(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    activation = {
        "predicate": "official_transient_pair",
        "pair_predecessor_request_ids": ["execute-0", "grade-0"],
    }
    initialize(
        root,
        required=[
            request_entry("execute-0"),
            request_entry("grade-0", request_kind="model_grade"),
        ],
        conditional=[
            request_entry(
                "execute-1",
                attempt_index=1,
                predecessor_request_id="execute-0",
                activation=activation,
            ),
            request_entry(
                "grade-1",
                request_kind="model_grade",
                attempt_index=1,
                predecessor_request_id="grade-0",
                activation=activation,
            ),
        ],
    )
    manifest = campaign.load_request_manifest(root / "request-manifest.json")
    assert tuple(
        manifest["budget"][key]
        for key in (
            "scheduled_provider_calls",
            "retry_provider_call_cap",
            "provider_call_hard_cap",
        )
    ) == (2, 2, 4)
    reserve(root, "execute-0")
    reserve(root, "grade-0")
    execute_receipt = receipt(
        root,
        "execute-0",
        terminal_status="failed",
        failure_class="official_transient",
    )
    grade_receipt = receipt(root, "grade-0")
    with pytest.raises(artifacts.StateError):
        reserve(root, "execute-1", [execute_receipt])
    with pytest.raises(artifacts.StateError):
        reserve(root, "execute-1", [receipt(root, "execute-0"), grade_receipt])
    reserve(root, "execute-1", [execute_receipt, grade_receipt])
    reserve(root, "grade-1", [execute_receipt, grade_receipt])
    campaign.verify_request_completion(
        root,
        [
            execute_receipt,
            grade_receipt,
            receipt(root, "execute-1"),
            receipt(root, "grade-1"),
        ],
    )


@pytest.mark.parametrize(
    "raw",
    [b'{"value":1,"value":2}', b'{"value":NaN}', b'{"value":Infinity}'],
)
def test_manifest_shape_fail_closed(raw: bytes) -> None:
    with pytest.raises(artifacts.StateError):
        artifacts.strict_json_loads(raw, "test input")


def test_manifest_no_overwrite_and_shape_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError):
        artifacts.canonical_bytes({"value": float("nan")})
    root = tmp_path / "race"
    root.mkdir()
    manifest_path = root / "request-manifest.json"
    real_link = artifacts.os.link

    def destination_appears(
        source: str | bytes | os.PathLike[str],
        destination: str | bytes | os.PathLike[str],
        *args: object,
        **kwargs: object,
    ) -> None:
        Path(destination).write_bytes(b"foreign\n")
        real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(artifacts.os, "link", destination_appears)
    with pytest.raises(artifacts.StateError):
        campaign.write_request_manifest(
            manifest_path,
            campaign_id="campaign-race",
            required_requests=[request_entry("race-request")],
            conditional_requests=[],
        )
    assert manifest_path.read_bytes() == b"foreign\n"
    monkeypatch.setattr(artifacts.os, "link", real_link)
    initialization_race = tmp_path / "initialization-race"
    initialization_race.mkdir()
    campaign.write_request_manifest(
        initialization_race / "request-manifest.json",
        campaign_id="campaign-01",
        required_requests=[request_entry("request-1")],
        conditional_requests=[],
    )
    (initialization_race / "phase-contract.json").write_text(
        '{"schema_version":"test-phase-contract/1.0"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(artifacts.os, "link", destination_appears)
    with pytest.raises(artifacts.StateError):
        initialize_existing(initialization_race)
    assert (
        initialization_race / "attempt-registry.json"
    ).read_bytes() == b"foreign\n"
    monkeypatch.setattr(artifacts.os, "link", real_link)
    attempt = tmp_path / "attempt"
    initialize(attempt)
    with pytest.raises(artifacts.StateError):
        campaign.write_request_manifest(
            attempt / "request-manifest.json",
            campaign_id="campaign-01",
            required_requests=[request_entry("replacement")],
            conditional_requests=[],
        )
    tampered = campaign.load_request_manifest(attempt / "request-manifest.json")
    tampered["budget"]["provider_call_hard_cap"] = 99
    (attempt / "request-manifest.json").write_text(
        json.dumps(tampered, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(artifacts.StateError):
        campaign.load_attempt(attempt)


def test_nonempty_attempt_root_fails_before_initialization(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    root.mkdir()
    campaign.write_request_manifest(
        root / "request-manifest.json",
        campaign_id="campaign-01",
        required_requests=[request_entry("request-1")],
        conditional_requests=[],
    )
    (root / "receipt.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(artifacts.StateError):
        initialize_existing(root)
