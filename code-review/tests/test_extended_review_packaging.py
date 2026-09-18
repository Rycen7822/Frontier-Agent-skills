"""P1: the built plugin runs the shipped capture and check logic on a real repository."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TESTS_DIR.parent
ROOT = SKILL_ROOT.parent
for path in (str(TESTS_DIR), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

import _review_fixtures as fixtures  # noqa: E402


def repository_state(repo: Path) -> dict:
    """Everything a review must leave untouched, read straight from disk and Git."""
    tracked = sorted(fixtures.git(repo, "ls-files").stdout.decode("utf-8").split())
    return {"status": fixtures.git(repo, "status", "--porcelain=v1").stdout,
        "config": fixtures.git(repo, "config", "--list").stdout,
        "staged": fixtures.git(repo, "ls-files", "--stage", "-z").stdout,
        "contents": {path: (repo / path).read_bytes() for path in tracked}}


class ExtendedReviewPackagingTests(unittest.TestCase):
    def test_p1_packaged_helper_runs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            repo = fixtures.init_repo(work)
            fixtures.commit(repo, {"src/module.py": "value = 1\n", "config.py": "LIMIT = 1\n",
                    "docs/readme.md": "docs\n"})
            fixtures.write(repo, "src/module.py", "value = 2\n")
            from build_codex_plugin import build, validate_plugin_build  # noqa: PLC0415

            marketplace = work / "marketplace"
            plugin = marketplace / "plugins" / "frontier-engineering-plugin"
            evidence = work / "build-evidence.json"
            build(ROOT, plugin, evidence, marketplace, work / "marketplace.zip")
            validate_plugin_build(plugin, evidence, source_root=ROOT)
            helper = plugin / "skills" / "code-review" / "scripts" / "review_support.py"
            self.assertTrue(helper.is_file())
            unrelated_cwd = work / "unrelated-cwd"
            unrelated_cwd.mkdir()
            environment = {"PATH": "/usr/bin:/bin", "HOME": str(work / "home"),
                "PYTHONDONTWRITEBYTECODE": "1"}

            def packaged(*arguments: str) -> tuple[int, dict | None]:
                finished = subprocess.run([sys.executable, str(helper), *arguments],
                    cwd=unrelated_cwd, env=environment, capture_output=True, text=True, timeout=180,
                    check=False)
                payload = finished.stdout.strip()
                return finished.returncode, (json.loads(payload) if payload else None)

            packet = work / "packet"
            before = repository_state(repo)
            capture = ["scope", "--repo", str(repo), "--mode", "workspace", "--path", "src",
                       "--context-path", "config.py", "--output", str(packet)]
            code, payload = packaged(*capture)
            self.assertEqual(0, code, payload)
            self.assertEqual(payload["scope_sha256"],
                             fixtures.digest((packet / "scope.json").read_bytes()))
            record = fixtures.write_json(work / "record.json",
                                         fixtures.hand_record(fixtures.packet_view(packet)))
            verify = ["check", "--repo", str(repo), "--packet", str(packet),
                      "--record", str(record)]
            report = work / "report.json"
            code, payload = packaged(*verify, "--output", str(report))
            self.assertEqual(0, code, payload)
            self.assertEqual("captured_inputs_match", payload["freshness"])
            self.assertEqual(before, repository_state(repo))
            with self.subTest("the packaged helper applies the current context rules"):
                fixtures.write(repo, "config.py", "LIMIT = 2\n")
                context_report = work / "report-context.json"
                code, payload = packaged(*verify, "--output", str(context_report))
                self.assertEqual(4, code, payload)
                written = json.loads(context_report.read_text(encoding="utf-8"))
                self.assertEqual("changed", written["freshness"]["status"])
                self.assertEqual(["config.py"], written["freshness"]["changed_paths"])
                fixtures.write(repo, "config.py", "LIMIT = 1\n")
                self.assertEqual(before, repository_state(repo))


if __name__ == "__main__":
    unittest.main()
