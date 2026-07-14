from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import canonical_hash, load_json  # noqa: E402
from local_workflow_adapter import AdapterConflict, LocalWorkflowAdapter  # noqa: E402


STATE_SCHEMA = load_json(ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(ROOT / "schemas" / "workflow-event.schema.json")
REGISTRY = load_json(ROOT / "references" / "owner-registry.json")


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.strip()


def _repository(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "config", "user.name", "SQW Test")
    _git(repo, "config", "user.email", "sqw@example.invalid")
    (repo / ".gitignore").write_text(".closure/\n", encoding="utf-8")
    (repo / "src" / "payments").mkdir(parents=True)
    (repo / "src" / "payments" / "charge.py").write_text("def charge():\n    return 'old'\n", encoding="utf-8")
    (repo / "tests" / "payments").mkdir(parents=True)
    (repo / "tests" / "payments" / "test_charge.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    (repo / "tests" / "holdout").mkdir(parents=True)
    (repo / "tests" / "holdout" / "secret_case.py").write_text("HIDDEN = True\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _closure_state(revision: str) -> dict:
    state = load_json(ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json")
    state["execution_policy"] = "autonomous_closure"
    state["request_mode"] = "change"
    state["source"]["base_revision"] = revision
    state["source"]["observed_revision"] = revision
    paths = {item["id"]: item["path"] for item in REGISTRY["owners"]}
    normative = ["authority-and-scope", "verifier-kernel", "workflow-state-contract", "workflow-modes", "verification-discipline"]
    state["active_owners"] = {
        "primary": "autonomous-closure",
        "normative": normative,
        "companions": [],
        "loaded_references": [
            {"owner_id": owner, "path": paths[owner], "reason_code": "closure_owner_required", "phase": "SPEC_COMPILING"}
            for owner in ["autonomous-closure", *normative]
        ],
    }
    state["closure_run"] = {
        "phase": "SPEC_COMPILING",
        "policy_bundle_hash": state["policy_bundle_hash"],
        "active_candidate_refs": [],
        "active_counterexample_refs": [],
        "budget": {"iterations_used": 0, "iterations_limit": 8, "candidate_evaluations_used": 0, "candidate_evaluations_limit": 10, "review_rounds_used": 0, "review_rounds_limit": 2},
        "terminal_status": None,
        "terminal_certificate_ref": None,
    }
    state["scope"].update({
        "allowed_reads": ["src/**", "tests/**"],
        "allowed_writes": ["src/manifest/**", "tests/manifest/**", "src/payments/**", "tests/payments/**"],
        "protected_paths": [".closure/**", ".closure-view/**", "tests/holdout/**"],
    })
    state.pop("state_hash", None)
    state["state_hash"] = canonical_hash(state)
    return state


def _adapter(repo: Path, revision: str) -> LocalWorkflowAdapter:
    adapter = LocalWorkflowAdapter(repo / ".closure", STATE_SCHEMA, EVENT_SCHEMA)
    adapter.initialize(_closure_state(revision))
    return adapter


class ClosureWorktreeAdapterTests(unittest.TestCase):
    def test_candidate_worktree_is_created_once_from_the_frozen_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _adapter(repo, revision)
            hook_marker = Path(directory) / "hook-ran"
            hook = repo / ".git" / "hooks" / "post-checkout"
            hook.write_text(f"#!/bin/sh\nprintf unsafe > {hook_marker}\n", encoding="utf-8")
            hook.chmod(0o755)
            result = adapter.create_candidate_worktree(
                repo,
                candidate_id="CAND-0001",
                base_revision=revision,
                writer_id="worker-01",
                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                protected_paths=[".closure/**", ".closure-view/**", "tests/holdout/**"],
                view_artifacts={"contract.json": b"{}\n"},
            )
            worktree = Path(result["worktree_path"])
            self.assertEqual(revision, _git(worktree, "rev-parse", "HEAD"))
            self.assertEqual("candidate_created", result["event_proposal"]["type"])
            self.assertFalse(hook_marker.exists(), "controller worktree creation must disable repository hooks")
            self.assertTrue((adapter.root / result["metadata_artifact"]["artifact_ref"]).is_file())
            self.assertEqual(0o444, (worktree / ".closure-view" / "contract.json").stat().st_mode & 0o777)
            with self.assertRaises(AdapterConflict):
                adapter.create_candidate_worktree(
                    repo,
                    candidate_id="CAND-0001",
                    base_revision=revision,
                    writer_id="worker-02",
                    allowed_write_paths=["src/payments/**"],
                    protected_paths=[".closure/**"],
                )

    def test_snapshot_binds_tracked_untracked_scope_protected_and_symlink_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _adapter(repo, revision)
            created = adapter.create_candidate_worktree(
                repo, candidate_id="CAND-0002", base_revision=revision, writer_id="worker-01",
                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                protected_paths=[".closure/**", ".closure-view/**", "tests/holdout/**"],
            )
            worktree = Path(created["worktree_path"])
            (worktree / "src" / "payments" / "charge.py").write_text("def charge():\n    return 'new'\n", encoding="utf-8")
            (worktree / "tests" / "payments" / "new_case.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")
            (worktree / "tests" / "holdout" / "secret_case.py").write_text("HIDDEN = False\n", encoding="utf-8")
            os.symlink(Path(directory) / "outside", worktree / "src" / "payments" / "outside-link")
            snapshot = adapter.inspect_candidate_snapshot(
                repo, candidate_id="CAND-0002", expected_base_revision=revision,
                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                protected_paths=[".closure/**", ".closure-view/**", "tests/holdout/**"],
            )
            self.assertTrue({"src/payments/charge.py", "tests/payments/new_case.py", "tests/holdout/secret_case.py"}.issubset(snapshot["changed_paths"]))
            self.assertEqual(["tests/holdout/secret_case.py"], snapshot["protected_surface_changes"])
            self.assertIn("src/payments/outside-link", snapshot["unsafe_paths"])
            self.assertRegex(snapshot["patch_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(snapshot["tree_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(snapshot["snapshot_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertFalse(snapshot["eligible_for_archive"])

    def test_archive_is_content_addressed_and_required_before_remove(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _adapter(repo, revision)
            created = adapter.create_candidate_worktree(
                repo, candidate_id="CAND-0003", base_revision=revision, writer_id="worker-01",
                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                protected_paths=[".closure/**", ".closure-view/**", "tests/holdout/**"],
            )
            worktree = Path(created["worktree_path"])
            (worktree / "src" / "payments" / "charge.py").write_text("def charge():\n    return 'archived'\n", encoding="utf-8")
            (worktree / "tests" / "payments" / "new_case.py").write_text("ARCHIVED = True\n", encoding="utf-8")
            snapshot = adapter.inspect_candidate_snapshot(
                repo, candidate_id="CAND-0003", expected_base_revision=revision,
                allowed_write_paths=["src/payments/**", "tests/payments/**"], protected_paths=[".closure/**", ".closure-view/**", "tests/holdout/**"],
            )
            forged = adapter.store_artifact(
                json.dumps({"candidate_id": "CAND-0003", "snapshot_hash": snapshot["snapshot_hash"]}).encode("utf-8"),
                sensitive=False,
            )
            with self.assertRaises(AdapterConflict):
                adapter.remove_candidate_worktree(repo, candidate_id="CAND-0003", expected_snapshot_hash=snapshot["snapshot_hash"], archive_artifact=None)
            with self.assertRaises(AdapterConflict):
                adapter.remove_candidate_worktree(repo, candidate_id="CAND-0003", expected_snapshot_hash=snapshot["snapshot_hash"], archive_artifact=forged)
            archive = adapter.archive_candidate(
                repo, candidate_id="CAND-0003", expected_base_revision=revision, expected_snapshot_hash=snapshot["snapshot_hash"],
                allowed_write_paths=["src/payments/**", "tests/payments/**"], protected_paths=[".closure/**", ".closure-view/**", "tests/holdout/**"],
            )
            archive_path = adapter.root / archive["archive_artifact"]["artifact_ref"]
            self.assertTrue(archive_path.is_file())
            payload = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual("CAND-0003", payload["candidate_id"])
            self.assertIn("tests/payments/new_case.py", payload["untracked_files"])
            (worktree / "src" / "payments" / "charge.py").write_text("tampered after archive\n", encoding="utf-8")
            with self.assertRaises(AdapterConflict):
                adapter.remove_candidate_worktree(repo, candidate_id="CAND-0003", expected_snapshot_hash=snapshot["snapshot_hash"], archive_artifact=archive["archive_artifact"])
            (worktree / "src" / "payments" / "charge.py").write_text("def charge():\n    return 'archived'\n", encoding="utf-8")
            removed = adapter.remove_candidate_worktree(repo, candidate_id="CAND-0003", expected_snapshot_hash=snapshot["snapshot_hash"], archive_artifact=archive["archive_artifact"])
            self.assertFalse(worktree.exists())
            self.assertEqual("candidate_pruned", removed["event_proposal"]["type"])

    def test_integration_worktree_is_clean_and_git_failure_never_mutates_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _adapter(repo, revision)
            before_state = adapter.state_path.read_bytes()
            before_events = adapter.events_path.read_bytes()
            with self.assertRaises(AdapterConflict):
                adapter.create_candidate_worktree(
                    repo, candidate_id="CAND-BAD", base_revision="f" * 40, writer_id="worker-01",
                    allowed_write_paths=["src/payments/**"], protected_paths=[".closure/**"],
                )
            self.assertEqual(before_state, adapter.state_path.read_bytes())
            self.assertEqual(before_events, adapter.events_path.read_bytes())
            integration = adapter.create_integration_worktree(repo, integration_id="INTEGRATION-0001", base_revision=revision)
            worktree = Path(integration["worktree_path"])
            self.assertEqual("", _git(worktree, "status", "--porcelain"))
            self.assertEqual(revision, _git(worktree, "rev-parse", "HEAD"))
            self.assertEqual("artifact_observed", integration["event_proposal"]["type"])

    def test_content_addressed_artifacts_reject_symlink_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _adapter(repo, revision)
            stored = adapter.store_artifact(b"immutable\n", sensitive=False)
            target = adapter.root / stored["artifact_ref"]
            external = Path(directory) / "external.bin"
            external.write_bytes(b"immutable\n")
            target.unlink()
            os.symlink(external, target)
            with self.assertRaises(AdapterConflict):
                adapter.store_artifact(b"immutable\n", sensitive=False)
            self.assertEqual(b"immutable\n", external.read_bytes())

            artifacts = adapter.root / "artifacts"
            for child in artifacts.iterdir():
                child.unlink()
            artifacts.rmdir()
            external_dir = Path(directory) / "external-artifacts"
            external_dir.mkdir()
            os.symlink(external_dir, artifacts)
            with self.assertRaises(AdapterConflict):
                adapter.store_artifact(b"must-not-escape\n", sensitive=False)
            self.assertEqual([], list(external_dir.iterdir()))

    def test_candidate_creation_rejects_checkout_filters_without_executing_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, _revision = _repository(Path(directory))
            marker = Path(directory) / "filter-ran"
            (repo / ".gitattributes").write_text("*.py filter=unsafe\n", encoding="utf-8")
            _git(repo, "config", "filter.unsafe.smudge", f"sh -c 'touch {marker}; cat'")
            _git(repo, "config", "filter.unsafe.clean", "cat")
            _git(repo, "add", ".gitattributes")
            _git(repo, "commit", "-qm", "add unsafe filter")
            revision = _git(repo, "rev-parse", "HEAD")
            adapter = _adapter(repo, revision)
            with self.assertRaises(AdapterConflict):
                adapter.create_candidate_worktree(
                    repo, candidate_id="CAND-FILTER", base_revision=revision, writer_id="worker-01",
                    allowed_write_paths=["src/payments/**"], protected_paths=[".closure/**", ".closure-view/**"],
                )
            self.assertFalse(marker.exists())
            self.assertFalse((adapter.root / "worktrees" / "CAND-FILTER").exists())


if __name__ == "__main__":
    unittest.main()
