from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_codex_plugin import _strict_json  # noqa: E402
from smoke_codex_cli_install import run_cli_smoke  # noqa: E402


def required_absolute_path(name: str, *, directory: bool = False) -> Path:
    value = os.environ.get(name)
    if not value:
        raise AssertionError(f"required release environment variable is missing: {name}")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise AssertionError(f"{name} must be an absolute non-symlink path")
    resolved = path.resolve(strict=True)
    if directory and not resolved.is_dir():
        raise AssertionError(f"{name} must be a directory")
    if not directory and not resolved.is_file():
        raise AssertionError(f"{name} must be a file")
    return resolved


def content_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


class ReleaseCliInstallTests(unittest.TestCase):
    def test_real_isolated_install_and_remove(self) -> None:
        run_root = required_absolute_path("FRONTIER_RUN_ROOT", directory=True)
        release_evidence_path = required_absolute_path("FRONTIER_RELEASE_EVIDENCE")
        validator = required_absolute_path("FRONTIER_PLUGIN_VALIDATOR")
        codex_bin = required_absolute_path("FRONTIER_CODEX_BIN")
        self.assertEqual(run_root / "release-evidence.json", release_evidence_path)
        self.assertEqual(
            ("skills", ".system", "plugin-creator", "scripts", "validate_plugin.py"),
            validator.parts[-5:],
            "release requires the installed official plugin-creator validator",
        )
        self.assertTrue(codex_bin.stat().st_mode & stat.S_IXUSR, "Codex binary is not executable")

        release_root = run_root / "release"
        marketplace = release_root / "marketplace"
        plugin = marketplace / "plugins" / "frontier-engineering-plugin"
        build_path = release_root / "plugin-build-evidence.json"
        static_path = release_root / "static-plugin-smoke.json"
        work_root = release_root / "cli-work"
        output = release_root / "cli-install-smoke.json"
        for path in (release_root, marketplace, plugin, work_root):
            self.assertTrue(path.is_dir() and not path.is_symlink(), path)
        for path in (build_path, static_path):
            self.assertTrue(path.is_file() and not path.is_symlink(), path)
        self.assertFalse(output.exists() or output.is_symlink(), "CLI evidence output is no-overwrite")

        release = _strict_json(release_evidence_path)
        build = _strict_json(build_path)
        self.assertEqual("release", build.get("output_class"))
        self.assertEqual(content_hash(release_evidence_path), build.get("release_evidence_hash"))
        self.assertEqual(release.get("source_revision"), build.get("source_revision"))
        self.assertEqual(release.get("source_tree_hash"), build.get("source_tree_hash"))
        self.assertEqual(release.get("plugin_tree_hash"), build.get("plugin_tree_hash"))

        result = run_cli_smoke(
            plugin,
            build_path,
            static_path,
            marketplace,
            work_root,
            validator,
            codex_command=str(codex_bin),
        )
        schema = _strict_json(ROOT / "packaging" / "schemas" / "cli-install-smoke.schema.json")
        Draft202012Validator(schema).validate(result)
        self.assertEqual("cli-install-smoke/3.0", result["schema_version"])
        self.assertEqual("passed", result["release_gate"])
        self.assertTrue(result["release_eligible"])
        self.assertFalse(result["model_invoked"])
        self.assertEqual([], list(work_root.iterdir()))

        descriptor = os.open(
            output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")


if __name__ == "__main__":
    unittest.main()
