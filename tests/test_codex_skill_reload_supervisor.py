from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_skill_reload_supervisor.py"
SPEC = importlib.util.spec_from_file_location("codex_skill_reload_supervisor", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


class FakeClient:
    def __init__(self, responses: dict[str, list[dict[str, object]] | dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object], float]] = []

    def request(
        self,
        method: str,
        params: dict[str, object],
        *,
        timeout: float = 15,
    ) -> dict[str, object]:
        self.calls.append((method, params, timeout))
        response = self.responses[method]
        if isinstance(response, list):
            if not response:
                raise AssertionError(f"no fake response left for {method}")
            return response.pop(0)
        return response


def write_skill(path: Path, body: str = "# Skill\n") -> Path:
    path.mkdir(parents=True)
    skill_md = path / "SKILL.md"
    skill_md.write_text(body, encoding="utf-8")
    return skill_md


def write_plugin(path: Path, name: str, version: str, skill_ids: tuple[str, ...]) -> None:
    (path / ".codex-plugin").mkdir(parents=True)
    (path / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": name, "version": version, "skills": "./skills/"}),
        encoding="utf-8",
    )
    for skill_id in skill_ids:
        skill_md = write_skill(path / "skills" / skill_id, f"# {skill_id}\n")
        (skill_md.parent / "reference.md").write_text("exact bytes\n", encoding="utf-8")


class StateTests(unittest.TestCase):
    def test_state_is_one_compact_private_atomic_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = {"schema_version": supervisor.STATE_SCHEMA, "phase": "running", "owner_pid": os.getpid()}
            supervisor.write_state(state_path, state)
            self.assertEqual("running", supervisor.read_state(state_path)["phase"])
            payload = state_path.read_bytes()
            self.assertEqual(1, payload.count(b"\n"))
            self.assertNotIn(b"\n  ", payload)
            self.assertEqual(0o600, stat.S_IMODE(state_path.stat().st_mode))
            self.assertEqual([state_path], list(Path(directory).iterdir()))

    def test_notify_commits_only_a_pending_exact_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            thread_id = "11111111-1111-4111-8111-111111111111"
            state = {
                "schema_version": supervisor.STATE_SCHEMA,
                "phase": "reload_requested",
                "owner_pid": os.getpid(),
                "thread_id": thread_id,
                "cwd": directory,
            }
            supervisor.write_state(state_path, state)
            wrong = argparse.Namespace(
                state=str(state_path),
                payload=json.dumps({
                    "type": "agent-turn-complete",
                    "thread-id": "22222222-2222-4222-8222-222222222222",
                    "cwd": directory,
                }),
            )
            with self.assertRaisesRegex(supervisor.SupervisorError, "thread id"):
                supervisor.command_notify(wrong)
            self.assertEqual("reload_requested", supervisor.read_state(state_path)["phase"])

            args = argparse.Namespace(
                state=str(state_path),
                payload=json.dumps({"type": "agent-turn-complete", "thread-id": thread_id, "cwd": directory}),
            )
            self.assertEqual(0, supervisor.command_notify(args))
            self.assertEqual("turn_complete", supervisor.read_state(state_path)["phase"])
            self.assertEqual(0, supervisor.command_notify(wrong))
            self.assertEqual("turn_complete", supervisor.read_state(state_path)["phase"])

    def test_checkpoint_verifies_all_skills_but_selects_only_named_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = {
                "schema_version": supervisor.STATE_SCHEMA,
                "phase": "running",
                "owner_pid": os.getpid(),
                "thread_id": "11111111-1111-4111-8111-111111111111",
                "cwd": directory,
                "codex": "/usr/bin/codex",
                "codex_home": str(Path(directory) / "codex-home"),
                "expected_skills": [],
                "continuation_skills": [],
            }
            supervisor.write_state(state_path, state)
            expected = [
                {"name": "sample:alpha", "path": "/cache/alpha/SKILL.md", "tree_hash": "sha256:a"},
                {"name": "sample:beta", "path": "/cache/beta/SKILL.md", "tree_hash": "sha256:b"},
            ]
            base = dict(
                state=str(state_path),
                plugin=["sample@personal"],
                skill=[],
                message="continue",
            )
            with mock.patch.object(supervisor, "discover_plugin_skills", return_value=expected):
                with self.assertRaisesRegex(supervisor.SupervisorError, "--continue-skill"):
                    supervisor.command_checkpoint(argparse.Namespace(**base, continue_skill=[]))
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        0,
                        supervisor.command_checkpoint(
                            argparse.Namespace(**base, continue_skill=["sample:beta"])
                        ),
                    )
            observed = supervisor.read_state(state_path)
            self.assertEqual(expected, observed["expected_skills"])
            self.assertEqual(["sample:beta"], observed["continuation_skills"])


class SkillIdentityTests(unittest.TestCase):
    def test_skill_tree_hash_is_deterministic_and_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skill"
            skill_md = write_skill(root)
            (root / "references").mkdir()
            reference = root / "references" / "contract.md"
            reference.write_text("v1\n", encoding="utf-8")
            first = supervisor.skill_tree_hash(skill_md)
            self.assertEqual(first, supervisor.skill_tree_hash(skill_md))
            reference.write_text("v2\n", encoding="utf-8")
            self.assertNotEqual(first, supervisor.skill_tree_hash(skill_md))
            (root / "linked.md").symlink_to(reference)
            with self.assertRaisesRegex(supervisor.SupervisorError, "symlink"):
                supervisor.skill_tree_hash(skill_md)

    def test_local_plugin_checkpoint_matches_source_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            codex_home = root / "codex-home"
            cache = codex_home / "plugins" / "cache" / "personal" / "sample-plugin" / "1.2.3"
            write_plugin(source, "sample-plugin", "1.2.3", ("alpha", "beta"))
            write_plugin(cache, "sample-plugin", "1.2.3", ("alpha", "beta"))
            listing = {
                "installed": [{
                    "pluginId": "sample-plugin@personal",
                    "name": "sample-plugin",
                    "marketplaceName": "personal",
                    "version": "1.2.3",
                    "installed": True,
                    "enabled": True,
                    "source": {"source": "local", "path": str(source)},
                }]
            }
            with mock.patch.object(supervisor, "_run_json", return_value=listing):
                expected = supervisor.discover_plugin_skills("codex", codex_home, "sample-plugin@personal")
            self.assertEqual(
                ["sample-plugin:alpha", "sample-plugin:beta"],
                [item["name"] for item in expected],
            )
            self.assertTrue(all(item["path"].startswith(str(cache)) for item in expected))

            (cache / "skills" / "beta" / "reference.md").write_text("drift\n", encoding="utf-8")
            with mock.patch.object(supervisor, "_run_json", return_value=listing):
                with self.assertRaisesRegex(supervisor.SupervisorError, "differ"):
                    supervisor.discover_plugin_skills("codex", codex_home, "sample-plugin@personal")

            with mock.patch.object(supervisor, "_run_json") as run_json:
                with self.assertRaisesRegex(supervisor.SupervisorError, "path-safe"):
                    supervisor.discover_plugin_skills("codex", codex_home, "../sample@personal")
                run_json.assert_not_called()

    def test_skills_list_requires_exact_enabled_path_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory).resolve()
            skill_md = write_skill(cwd / "skill")
            expected = [{
                "name": "sample:skill",
                "path": str(skill_md),
                "tree_hash": supervisor.skill_tree_hash(skill_md),
            }]
            client = FakeClient({
                "skills/list": {
                    "data": [{
                        "cwd": str(cwd),
                        "skills": [{"name": "sample:skill", "path": str(skill_md), "enabled": True}],
                        "errors": [],
                    }]
                }
            })
            self.assertEqual(expected, supervisor.verify_expected_skills(client, cwd, expected))
            self.assertEqual(
                {"cwds": [str(cwd)], "forceReload": True},
                client.calls[0][1],
            )


class ResumeAndGoalTests(unittest.TestCase):
    THREAD_ID = "33333333-3333-4333-8333-333333333333"

    def test_resume_proof_requires_exact_thread_full_access_and_never(self) -> None:
        cwd = Path("/").resolve()
        valid = {
            "thread": {"id": self.THREAD_ID},
            "approvalPolicy": "never",
            "sandbox": {"type": "dangerFullAccess"},
            "cwd": str(cwd),
        }
        supervisor.validate_resume_response(valid, self.THREAD_ID, cwd)
        for key, value in (
            ("approvalPolicy", "on-request"),
            ("sandbox", {"type": "workspaceWrite"}),
            ("thread", {"id": "different"}),
        ):
            invalid = dict(valid)
            invalid[key] = value
            with self.assertRaises(supervisor.SupervisorError):
                supervisor.validate_resume_response(invalid, self.THREAD_ID, cwd)

    def test_only_a_previously_active_goal_is_automatically_restored(self) -> None:
        paused_goal = {"threadId": self.THREAD_ID, "status": "paused"}
        active_goal = {"threadId": self.THREAD_ID, "status": "active"}
        client = FakeClient({
            "thread/goal/get": [{"goal": paused_goal}],
            "thread/goal/set": {"goal": active_goal},
        })
        self.assertTrue(supervisor.restore_goal_if_required(client, self.THREAD_ID, "active"))
        self.assertEqual(["thread/goal/get", "thread/goal/set"], [call[0] for call in client.calls])

        intentionally_paused = FakeClient({"thread/goal/get": {"goal": paused_goal}})
        self.assertFalse(supervisor.restore_goal_if_required(intentionally_paused, self.THREAD_ID, "paused"))
        self.assertEqual(["thread/goal/get"], [call[0] for call in intentionally_paused.calls])

        limited = FakeClient({
            "thread/goal/get": {"goal": {"threadId": self.THREAD_ID, "status": "usageLimited"}}
        })
        with self.assertRaisesRegex(supervisor.SupervisorError, "non-resumable"):
            supervisor.restore_goal_if_required(limited, self.THREAD_ID, "active")

    def test_tui_and_turn_commands_never_fork_or_select_last(self) -> None:
        cwd = Path("/").resolve()
        command = supervisor.build_tui_command(
            "/usr/bin/codex",
            Path("/tmp/supervisor.sock"),
            cwd,
            self.THREAD_ID,
            no_alt_screen=True,
        )
        self.assertIn(self.THREAD_ID, command)
        self.assertIn("danger-full-access", command)
        self.assertIn("never", command)
        self.assertNotIn("fork", command)
        self.assertNotIn("--last", command)

        client = FakeClient({"turn/start": {"turn": {"id": "turn-1"}}})
        expected = [{"name": "sample:skill", "path": "/installed/skill/SKILL.md", "tree_hash": "sha256:x"}]
        self.assertEqual(
            "turn-1",
            supervisor.start_continuation_turn(client, self.THREAD_ID, cwd, expected, "continue"),
        )
        params = client.calls[0][1]
        self.assertEqual("never", params["approvalPolicy"])
        self.assertEqual({"type": "dangerFullAccess"}, params["sandboxPolicy"])
        self.assertEqual(
            {"type": "skill", "name": "sample:skill", "path": "/installed/skill/SKILL.md"},
            params["input"][0],
        )


if __name__ == "__main__":
    unittest.main()
