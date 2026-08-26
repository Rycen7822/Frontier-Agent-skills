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
from _codex_eval_isolation import (
    ISOLATED_PERMISSION_PROFILES,
    command_permission_argv,
    proxy_environment_projection,
    request_codex_home,
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
                self.assertEqual(argv[1:3], command_permission_argv("read-only"))
                self.assertNotIn("--sandbox", argv)
                self.assertEqual(
                    sum(value.startswith("model_catalog_json=\"/") for value in argv),
                    1,
                )

    def test_request_codex_home_binds_strict_command_permission_profiles(self) -> None:
        with request_codex_home(Path("/usr/bin/bwrap")) as home:
            self.assertIsNotNone(home)
            config = (home / "config.toml").read_text(encoding="utf-8")
            for sandbox, profile in ISOLATED_PERMISSION_PROFILES.items():
                self.assertIn(f"[permissions.{profile}]", config)
                self.assertIn(f'extends = ":{sandbox if sandbox == "read-only" else "workspace"}"', config)
            self.assertEqual(config.count('"/run/frontier-codex-home" = "deny"'), 2)

    def test_proxy_environment_projection_excludes_values_and_detects_credentials(self) -> None:
        rows = proxy_environment_projection(
            ["HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"],
            {
                "HTTPS_PROXY": "http://user:pass@example.invalid:8080",
                "HTTP_PROXY": "http://example.invalid:8080?token=value",
                "NO_PROXY": "localhost",
            },
        )
        self.assertTrue(rows[0]["url_userinfo"])
        self.assertTrue(rows[0]["credential_like_component"])
        self.assertFalse(rows[1]["url_userinfo"])
        self.assertTrue(rows[1]["credential_like_component"])
        self.assertFalse(rows[2]["credential_like_component"])
        serialized = json.dumps(rows, sort_keys=True)
        for forbidden in ("pass", "example.invalid", "value", "localhost"):
            self.assertNotIn(forbidden, serialized)

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

    def test_runtime_host_parser_accepts_bound_relative_catalog_path(self) -> None:
        parser = host._parser()
        args = parser.parse_args(
            [
                "--codex", "/runtime/codex",
                "--codex-sha256", "sha256:" + "0" * 64,
                "--codex-version", "0.149.1",
                "--host-manifest", "/runtime/host.json",
                "--model", "gpt-5.6-sol",
                "--effort", "xhigh",
                "--profile", "none",
                "--model-catalog-snapshot", "/runtime/host.runtime/models_cache.json",
                "--model-catalog-relative-path", "host.runtime/models_cache.json",
                "--model-catalog-sha256", "sha256:" + "1" * 64,
                "--model-catalog-client-version", "0.149.1",
                "--runtime-surface-version", RUNTIME_SURFACE_VERSION,
                "--sandbox", "read-only",
                "--timeout", "900",
            ]
        )
        self.assertEqual(args.model_catalog_relative_path, "host.runtime/models_cache.json")


if __name__ == "__main__":
    unittest.main()
