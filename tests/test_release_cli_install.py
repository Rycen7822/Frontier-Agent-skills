from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_codex_plugin import build, _strict_json  # noqa: E402
from smoke_codex_plugin import isolated_smoke  # noqa: E402
from smoke_codex_cli_install import run_cli_smoke  # noqa: E402


class ReleaseCliInstallTests(unittest.TestCase):
    def test_real_isolated_install_and_remove(self) -> None:
        codex = shutil.which(os.environ.get("FRONTIER_CODEX_BIN", "codex"))
        if codex is None:
            self.skipTest("Codex CLI is not installed")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            marketplace = work / "marketplace"
            plugin = marketplace / "plugins" / "frontier-engineering-plugin"
            evidence = work / "build.json"
            build(ROOT, plugin, evidence, marketplace, work / "marketplace.zip")
            static_path = work / "static.json"
            static_path.write_text(json.dumps(isolated_smoke(plugin, evidence)))
            isolated_work = work / "install"
            isolated_work.mkdir()
            result = run_cli_smoke(
                plugin, Path(os.path.relpath(evidence)), Path(os.path.relpath(static_path)), marketplace, isolated_work,
                codex_command=codex,
            )
            schema = _strict_json(ROOT / "packaging" / "schemas" / "cli-install-smoke.schema.json")
            Draft202012Validator(schema).validate(result)
            self.assertTrue(result["cache_matches_staging"])
            self.assertTrue(result["uninstall_clean"])
            self.assertFalse(result["model_invoked"])
            self.assertEqual([], list(isolated_work.iterdir()))


if __name__ == "__main__":
    unittest.main()
