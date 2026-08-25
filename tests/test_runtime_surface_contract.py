import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import codex_eval_host as host  # noqa: E402
from _codex_eval_delivery import (  # noqa: E402
    RUNTIME_SURFACE_VERSION,
    isolated_tool_schema_id,
    skill_isolation_argv,
)


class RuntimeSurfaceContractTests(unittest.TestCase):
    def _args(self, root: Path) -> SimpleNamespace:
        return SimpleNamespace(
            codex=Path("/runtime/codex"),
            model="gpt-5.6-sol",
            profile="none",
            isolation_tool=Path("/runtime/bwrap"),
            runtime_surface_version=RUNTIME_SURFACE_VERSION,
            model_catalog_snapshot=root / "models_cache.json",
            effort="xhigh",
            sandbox="read-only",
            plugin_root=Path("/runtime/plugin"),
        )

    def test_runtime_tool_schema_and_disabled_apps_are_versioned(self) -> None:
        self.assertEqual(
            isolated_tool_schema_id("sha", "sha", "sha"),
            "codex-tools-workspace-isolated-v2",
        )
        self.assertEqual(
            isolated_tool_schema_id(
                "sha", "sha", "sha", RUNTIME_SURFACE_VERSION
            ),
            "codex-tools-workspace-isolated-v3",
        )
        argv = skill_isolation_argv(include_installed_skills=False, include_apps=True)
        self.assertIn("--disable", argv)
        self.assertIn("apps", argv)

    def test_fresh_and_resume_bind_the_same_isolated_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self._args(root)
            fresh = host._fresh_argv(args, root, root / "last", ephemeral=True)
            resume = host._resume_argv(args, "thread-1", root / "last")
            for argv in (fresh, resume):
                self.assertEqual(argv.count("apps"), 1)
                self.assertEqual(
                    sum(value.startswith("model_catalog_json=\"/") for value in argv),
                    1,
                )

    def test_catalog_snapshot_identity_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models_cache.json"
            path.write_text(
                json.dumps(
                    {
                        "client_version": "0.149.1",
                        "models": [{"slug": "gpt-5.6-sol"}],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            digest = "sha256:" + __import__("hashlib").sha256(
                path.read_bytes()
            ).hexdigest()
            host._validate_model_catalog_snapshot(
                path,
                digest=digest,
                client_version="0.149.1",
                model="gpt-5.6-sol",
            )
            with self.assertRaises(host.AdapterError):
                host._validate_model_catalog_snapshot(
                    path,
                    digest=digest,
                    client_version="0.149.1",
                    model="gpt-5.6-solx",
                )


if __name__ == "__main__":
    unittest.main()
