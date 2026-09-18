"""P01-P06: packaging, standalone placement, dependency bounds, and repository safety."""

from __future__ import annotations

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TESTS_DIR.parent
ROOT = SKILL_ROOT.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
for path in (str(TESTS_DIR), str(SCRIPTS_DIR), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

import _review_fixtures as fixtures  # noqa: E402

PRODUCTION_MODULES = ("review_support.py", "_review_git.py", "_review_record.py")
ALLOWED_IMPORTS = {
    "argparse",
    "dataclasses",
    "errno",
    "functools",
    "__future__",
    "hashlib",
    "json",
    "jsonschema",
    "os",
    "pathlib",
    "re",
    "shutil",
    "stat",
    "subprocess",
    "sys",
    "tempfile",
    "typing",
}
LOCAL_MODULES = {"_review_git", "_review_record"}
RETIRED_NAMES = (
    "review-result",
    "publication-readiness",
    "codex-task-result",
    "result-consistency",
    "operator/review",
)
RETIRED_NAME_HISTORY = {
    "docs/fas-v11-migration.md",
    "RELEASE_NOTES.md",
    "code-review/tests/test_extended_review_packaging.py",
}
SHIPPED_PARTS = ("SKILL.md", "agents", "licenses", "references", "schemas", "scripts")


def digest_of(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class ExtendedReviewPackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repo = fixtures.init_repo(self.root)
        fixtures.commit_files(self.repo, {"src/module.py": "value = 1\n"})
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")

    def standalone_skill(self) -> Path:
        target = self.root / "standalone" / "code-review"
        target.mkdir(parents=True)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for part in SHIPPED_PARTS:
            source = SKILL_ROOT / part
            if source.is_dir():
                shutil.copytree(source, target / part, ignore=ignore)
            else:
                shutil.copy2(source, target / part)
        return target

    def run_helper(self, script: Path, arguments: list[str], cwd: Path):
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=cwd,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def write_record(self, packet: Path, scope_sha256: str) -> Path:
        scope = json.loads((packet / "scope.json").read_text(encoding="utf-8"))
        record = {
            "schema_version": "fas-review-record/1",
            "scope_ref": "scope.json",
            "scope_sha256": scope_sha256,
            "coverage": [
                {"item_id": item["id"], "status": "reviewed", "reason": None}
                for item in scope["items"]
            ],
            "findings": [],
            "concerns": [],
            "verification": [],
            "limitations": [],
        }
        return fixtures.write_json(self.root / "record.json", record)

    def test_p01_standalone_copy_runs_both_commands(self) -> None:
        skill = self.standalone_skill()
        unrelated = self.root / "cwd"
        unrelated.mkdir()
        packet = self.root / "standalone-packet"
        scoped = self.run_helper(
            skill / "scripts" / "review_support.py",
            [
                "scope",
                "--repo",
                str(self.repo),
                "--mode",
                "workspace",
                "--path",
                ".",
                "--output",
                str(packet),
            ],
            unrelated,
        )
        self.assertEqual(0, scoped.returncode, scoped.stdout + scoped.stderr)
        payload = json.loads(scoped.stdout)
        record = self.write_record(packet, payload["scope_sha256"])
        report = self.root / "standalone-report.json"
        checked = self.run_helper(
            skill / "scripts" / "review_support.py",
            [
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(packet),
                "--record",
                str(record),
                "--output",
                str(report),
            ],
            unrelated,
        )
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        self.assertEqual("all_declared_reviewed", json.loads(checked.stdout)["coverage_status"])
        self.assertTrue(report.is_file())
        self.assertFalse((skill / "scripts" / "__pycache__").exists())

    def test_p02_packaged_helper_matches_the_source_helper(self) -> None:
        skill = self.standalone_skill()
        unrelated = self.root / "cwd"
        unrelated.mkdir()
        source_packet = self.root / "source-packet"
        packaged_packet = self.root / "packaged-packet"
        source_run = self.run_helper(
            SCRIPTS_DIR / "review_support.py",
            ["scope", "--repo", str(self.repo), "--mode", "workspace", "--path", ".", "--output", str(source_packet)],
            unrelated,
        )
        packaged_run = self.run_helper(
            skill / "scripts" / "review_support.py",
            ["scope", "--repo", str(self.repo), "--mode", "workspace", "--path", ".", "--output", str(packaged_packet)],
            unrelated,
        )
        self.assertEqual(0, source_run.returncode, source_run.stdout + source_run.stderr)
        self.assertEqual(0, packaged_run.returncode, packaged_run.stdout + packaged_run.stderr)
        self.assertEqual(
            (source_packet / "scope.json").read_bytes(),
            (packaged_packet / "scope.json").read_bytes(),
        )
        self.assertEqual(
            json.loads(source_run.stdout)["scope_sha256"],
            json.loads(packaged_run.stdout)["scope_sha256"],
        )
        self.assertEqual(
            {path.name for path in (source_packet / "objects").iterdir()},
            {path.name for path in (packaged_packet / "objects").iterdir()},
        )

    def test_p03_production_modules_have_bounded_acyclic_dependencies(self) -> None:
        graph: dict[str, set[str]] = {}
        for name in PRODUCTION_MODULES:
            tree = ast.parse((SCRIPTS_DIR / name).read_text(encoding="utf-8"), filename=name)
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            module = Path(name).stem
            graph[module] = {item for item in imported if item in LOCAL_MODULES}
            with self.subTest(f"P03 {name}"):
                self.assertLessEqual(imported, ALLOWED_IMPORTS | LOCAL_MODULES, imported)
        self.assertEqual(set(), graph["_review_record"])
        self.assertLessEqual(graph["_review_git"], {"_review_record"})
        self.assertLessEqual(graph["review_support"], {"_review_git", "_review_record"})
        ordered: list[str] = []
        pending = dict(graph)
        while pending:
            ready = sorted(name for name, deps in pending.items() if not deps - set(ordered))
            self.assertTrue(ready, f"import cycle among {sorted(pending)}")
            for name in ready:
                ordered.append(name)
                pending.pop(name)

    def test_p04_scope_and_check_do_not_modify_the_repository(self) -> None:
        def snapshot() -> dict:
            refs = fixtures.git(self.repo, "show-ref", "--head").stdout
            tracked = fixtures.git(self.repo, "ls-files", "-z").stdout.decode("utf-8").split("\0")
            contents = {}
            for name in tracked:
                if not name:
                    continue
                info = os.lstat(self.repo / name)
                if os.path.stat.S_ISREG(info.st_mode):
                    contents[name] = digest_of(self.repo / name)
            status = fixtures.git(self.repo, "status", "--porcelain=v1", "-z").stdout
            return {
                "index": digest_of(self.repo / ".git" / "index"),
                "refs": refs,
                "status": status,
                "contents": contents,
            }

        before = snapshot()
        packet = self.root / "safe-packet"
        scoped = self.run_helper(
            SCRIPTS_DIR / "review_support.py",
            ["scope", "--repo", str(self.repo), "--mode", "workspace", "--path", ".", "--output", str(packet)],
            self.root,
        )
        self.assertEqual(0, scoped.returncode, scoped.stdout + scoped.stderr)
        record = self.write_record(packet, json.loads(scoped.stdout)["scope_sha256"])
        report = self.root / "safe-report.json"
        checked = self.run_helper(
            SCRIPTS_DIR / "review_support.py",
            ["check", "--repo", str(self.repo), "--packet", str(packet), "--record", str(record), "--output", str(report)],
            self.root,
        )
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        self.assertEqual(before, snapshot())

    def test_p05_two_marketplace_builds_are_reproducible(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from build_codex_plugin import build, validate_plugin_build  # noqa: PLC0415

        archives = []
        evidence_records = []
        for index in range(2):
            work = self.root / f"build-{index}"
            marketplace = work / "marketplace"
            plugin = marketplace / "plugins" / "frontier-engineering-plugin"
            evidence = work / "build.json"
            archive = work / "marketplace.zip"
            build(ROOT, plugin, evidence, marketplace, archive)
            validate_plugin_build(plugin, evidence, source_root=ROOT)
            evidence_record = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual("frontier-engineering/11.0.2", evidence_record["bundle_id"])
            self.assertEqual(10, len(evidence_record["skill_versions"]))
            self.assertIs(
                False, evidence_record["skill_activation"]["software-quality-workflows"]
            )
            self.assertIs(False, evidence_record["skill_activation"]["skill-evaluator"])
            shipped = {path.name for path in (plugin / "skills" / "code-review").iterdir()}
            self.assertLessEqual(
                {"SKILL.md", "agents", "references", "schemas", "scripts"}, shipped
            )
            for unwanted in ("operator", "__pycache__", ".git"):
                self.assertNotIn(unwanted, shipped)
            archives.append(archive.read_bytes())
            evidence_records.append(evidence_record["plugin_tree_hash"])
        self.assertEqual(archives[0], archives[1])
        self.assertEqual(evidence_records[0], evidence_records[1])

    def test_n13_packaged_helper_keeps_the_repaired_behaviors(self) -> None:
        fixtures.commit_files(
            self.repo,
            {"src/module.py": "value = 1\n", "config/runtime.json": '{"limit": 32}\n'},
        )
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        skill = self.standalone_skill()
        script = skill / "scripts" / "review_support.py"
        cwd = self.root / "n13-cwd"
        cwd.mkdir()
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        def packaged(*arguments: str):
            completed = subprocess.run(
                [sys.executable, str(script), *arguments],
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            payload = json.loads(completed.stdout) if completed.stdout.strip() else None
            return completed.returncode, payload

        packet = self.root / "n13-packet"
        code, payload = packaged(
            "scope",
            "--repo",
            str(self.repo),
            "--mode",
            "workspace",
            "--path",
            "src/module.py",
            "--context-path",
            "config/runtime.json",
            "--output",
            str(packet),
        )
        self.assertEqual(0, code, payload)
        scope = json.loads((packet / "scope.json").read_text(encoding="utf-8"))
        self.assertEqual(1, len(scope["items"]))
        record = {
            "schema_version": "fas-review-record/1",
            "scope_ref": "scope.json",
            "scope_sha256": payload["scope_sha256"],
            "coverage": [
                {"item_id": item["id"], "status": "reviewed", "reason": None}
                for item in scope["items"]
            ],
            "findings": [],
            "concerns": [],
            "verification": [],
            "limitations": [],
        }
        record_path = fixtures.write_json(self.root / "n13-record.json", record)

        def check(name: str, repo_argument: Path | None = None):
            report = self.root / f"n13-{name}-report.json"
            code, payload = packaged(
                "check",
                "--repo",
                str(repo_argument or self.repo),
                "--packet",
                str(packet),
                "--record",
                str(record_path),
                "--output",
                str(report),
            )
            return code, payload, report

        with self.subTest("N13 packaged check matches on the captured inputs"):
            code, payload, report = check("baseline")
            self.assertEqual(0, code, payload)
            self.assertEqual("captured_inputs_match", payload["freshness"])
        with self.subTest("N13 packaged check sees a context change"):
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 64}\n')
            code, payload, report = check("context")
            self.assertEqual(4, code, payload)
            self.assertEqual("changed", payload["freshness"])
            self.assertIn(
                "config/runtime.json",
                json.loads(report.read_text(encoding="utf-8"))["freshness"]["changed_paths"],
            )
        with self.subTest("N13 packaged invalid input yields a bounded report"):
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 32}\n')
            sentinel = "S" * 9000
            broken_path = fixtures.write_json(
                self.root / "n13-broken-record.json", {**record, "limitations": [sentinel]}
            )
            report = self.root / "n13-bounded-report.json"
            code, payload = packaged(
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(packet),
                "--record",
                str(broken_path),
                "--output",
                str(report),
            )
            self.assertEqual(2, code, payload)
            written = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual("invalid", written["validation"])
            self.assertLessEqual(len(written["problems"][0]["message"]), 512)
            self.assertNotIn(sentinel, report.read_text(encoding="utf-8"))
        with self.subTest("N13 packaged check uses the real repository root"):
            inside = self.repo / "n13-inside.json"
            code, payload = packaged(
                "check",
                "--repo",
                str(self.repo / "src"),
                "--packet",
                str(packet),
                "--record",
                str(record_path),
                "--output",
                str(inside),
            )
            self.assertEqual(2, code, payload)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertFalse(inside.exists())
            outside = self.root / "n13-outside.json"
            code, payload = packaged(
                "check",
                "--repo",
                str(self.repo / "src"),
                "--packet",
                str(packet),
                "--record",
                str(record_path),
                "--output",
                str(outside),
            )
            self.assertEqual(0, code, payload)
            self.assertTrue(outside.is_file())

    def test_p06_no_active_consumer_uses_retired_interfaces(self) -> None:
        listing = fixtures.git(ROOT, "ls-files", "-z")
        tracked = [name for name in listing.stdout.decode("utf-8").split("\0") if name]
        offenders: dict[str, list[str]] = {}
        for name in tracked:
            if name in RETIRED_NAME_HISTORY:
                continue
            path = ROOT / name
            if not path.is_file() or path.is_symlink():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            matches = [token for token in RETIRED_NAMES if token in text]
            if matches:
                offenders[name] = matches
        self.assertEqual({}, offenders)
        for name in RETIRED_NAME_HISTORY:
            self.assertTrue((ROOT / name).is_file(), name)
        for part in ("SKILL.md", "references", "schemas", "scripts"):
            self.assertTrue((SKILL_ROOT / part).exists(), part)
        self.assertFalse((SKILL_ROOT / "operator").exists())
        retired_schemas = [
            path.name
            for path in (SKILL_ROOT / "schemas").glob("*.json")
            if path.name != "review-record.schema.json"
        ]
        self.assertEqual([], retired_schemas)


if __name__ == "__main__":
    unittest.main()
