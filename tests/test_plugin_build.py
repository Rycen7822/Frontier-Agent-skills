from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_codex_plugin.py"
SPEC = importlib.util.spec_from_file_location("build_codex_plugin", BUILDER_PATH)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
SMOKE_PATH = ROOT / "scripts" / "smoke_codex_plugin.py"
SMOKE_SPEC = importlib.util.spec_from_file_location("smoke_codex_plugin", SMOKE_PATH)
assert SMOKE_SPEC is not None and SMOKE_SPEC.loader is not None
smoke = importlib.util.module_from_spec(SMOKE_SPEC)
SMOKE_SPEC.loader.exec_module(smoke)
CLI_SMOKE_PATH = ROOT / "scripts" / "smoke_codex_cli_install.py"
CLI_SMOKE_SPEC = importlib.util.spec_from_file_location("smoke_codex_cli_install", CLI_SMOKE_PATH)
assert CLI_SMOKE_SPEC is not None and CLI_SMOKE_SPEC.loader is not None
cli_smoke = importlib.util.module_from_spec(CLI_SMOKE_SPEC)
CLI_SMOKE_SPEC.loader.exec_module(cli_smoke)
PLUGIN_VALIDATOR = Path.home() / ".codex" / "skills" / ".system" / "plugin-creator" / "scripts" / "validate_plugin.py"
PLUGIN_SCAFFOLDER = Path.home() / ".codex" / "skills" / ".system" / "plugin-creator" / "scripts" / "create_basic_plugin.py"


class PluginBuildTests(unittest.TestCase):
    @staticmethod
    def _schema(name: str) -> dict[str, object]:
        return json.loads((ROOT / "packaging" / "schemas" / name).read_text(encoding="utf-8"))

    def test_staging_build_is_deterministic_hashed_and_ingestion_valid(self) -> None:
        evidences = []
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for directory in (first, second):
                parent = Path(directory)
                output = parent / "frontier-engineering-plugin"
                evidence = parent / "build-evidence.json"
                observed = builder.build(ROOT, output, None, evidence)
                self.assertEqual({".codex-plugin", "skills"}, {path.name for path in output.iterdir()})
                manifest = json.loads((output / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(output.name, manifest["name"])
                self.assertEqual("4.0.0", manifest["version"])
                self.assertEqual("./skills/", manifest["skills"])
                self.assertTrue({"author", "interface"} <= set(manifest))
                self.assertEqual({"writing-plans", "software-quality-workflows"}, {path.name for path in (output / "skills").iterdir()})
                self.assertEqual(observed, json.loads(evidence.read_text(encoding="utf-8")))
                self.assertEqual(observed["plugin_file_count"], len(observed["files"]))
                self.assertEqual(len(observed["files"]), len({item["path"] for item in observed["files"]}))
                self.assertEqual("plugin-build-evidence/2.0", observed["schema_version"])
                self.assertEqual(
                    (None, "implicit_local_pilot"),
                    (observed["release_evidence_hash"], observed["activation_ceiling"]),
                )
                schema = json.loads((ROOT / "packaging" / "schemas" / "plugin-build-evidence.schema.json").read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                self.assertEqual([], list(Draft202012Validator(schema).iter_errors(observed)))
                unhashed = deepcopy(observed)
                observed_hash = unhashed.pop("evidence_hash")
                self.assertEqual(
                    observed_hash,
                    "sha256:" + sha256(json.dumps(unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
                )
                evidences.append(observed)
            self.assertEqual(evidences[0], evidences[1])

    def test_build_and_release_evidence_conditions_are_closed(self) -> None:
        build_schema = self._schema("plugin-build-evidence.schema.json")
        release_schema = self._schema("release-evidence.schema.json")
        Draft202012Validator.check_schema(build_schema)
        Draft202012Validator.check_schema(release_schema)
        valid_release = {
            "schema_version": "release-evidence/2.0",
            "bundle_id": "frontier-engineering/8.0.0+7.0.0",
            "bundle_version": "4.0.0",
            "source_tree_hash": "sha256:" + "1" * 64,
            "source_revision": "a" * 40,
            "source_revision_signed": True,
            "source_clean": True,
            "deterministic_report_hash": "sha256:" + "2" * 64,
            "l2_scored_report_hash": "sha256:" + "3" * 64,
            "activation_decision_hash": "sha256:" + "4" * 64,
            "release_gate": "passed",
            "approved_activation_level": "implicit_local_pilot",
        }
        self.assertEqual([], list(Draft202012Validator(release_schema).iter_errors(valid_release)))
        for key in ("deterministic_report_hash", "l2_scored_report_hash", "activation_decision_hash"):
            invalid = deepcopy(valid_release)
            invalid.pop(key)
            self.assertTrue(list(Draft202012Validator(release_schema).iter_errors(invalid)), key)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            evidence_path = parent / "build.json"
            staging = builder.build(ROOT, parent / "frontier-engineering-plugin", None, evidence_path)
            release = deepcopy(staging)
            release.update({
                "output_class": "release",
                "release_evidence_hash": "sha256:" + "5" * 64,
                "activation_ceiling": "implicit_local_pilot",
            })
            self.assertEqual([], list(Draft202012Validator(build_schema).iter_errors(release)))
            invalid_staging = deepcopy(staging)
            invalid_staging["release_evidence_hash"] = "sha256:" + "6" * 64
            self.assertTrue(list(Draft202012Validator(build_schema).iter_errors(invalid_staging)))
            invalid_release = deepcopy(release)
            invalid_release["activation_ceiling"] = "shadow"
            self.assertTrue(list(Draft202012Validator(build_schema).iter_errors(invalid_release)))

    def test_staging_passes_installed_plugin_ingestion_validator_when_available(self) -> None:
        if not PLUGIN_VALIDATOR.is_file():
            self.skipTest("plugin-creator validator is not installed")
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "frontier-engineering-plugin"
            builder.build(ROOT, output, None, parent / "evidence.json")
            completed = subprocess.run(
                [sys.executable, str(PLUGIN_VALIDATOR), str(output)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)

    def test_output_and_evidence_are_both_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "frontier-engineering-plugin"
            evidence = parent / "build-evidence.json"
            builder.build(ROOT, output, None, evidence)
            with self.assertRaises(ValueError):
                builder.build(ROOT, output, None, parent / "second-evidence.json")
            with self.assertRaises(ValueError):
                builder.build(ROOT, parent / "second-plugin", None, evidence)

    def test_release_build_rejects_missing_or_forged_external_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "dist" / "frontier-engineering-plugin"
            evidence = parent / "build-evidence.json"
            with self.assertRaisesRegex(ValueError, "release evidence"):
                builder.build(ROOT, output, None, evidence)
            forged = parent / "release.json"
            forged.write_text(json.dumps({
                "schema_version": "release-evidence/2.0",
                "bundle_id": "frontier-engineering/8.0.0+7.0.0",
                "bundle_version": "4.0.0",
                "source_tree_hash": "sha256:" + "1" * 64,
                "source_revision": "a" * 40,
                "source_revision_signed": True,
                "source_clean": True,
                "deterministic_report_hash": "sha256:" + "2" * 64,
                "l2_scored_report_hash": "sha256:" + "3" * 64,
                "activation_decision_hash": "sha256:" + "4" * 64,
                "release_gate": "passed",
                "approved_activation_level": "implicit_local_pilot",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source tree|deterministic report"):
                builder.build(ROOT, output, forged, evidence)
            self.assertFalse(output.exists())
            self.assertFalse(evidence.exists())

    def test_source_symlink_and_manifest_version_drift_fail_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            copied = parent / "bundle"
            shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            target = copied / "writing-plans" / "references" / "profiles" / "brief.md"
            target.unlink()
            target.symlink_to(copied / "README.md")
            output = parent / "frontier-engineering-plugin"
            evidence = parent / "evidence.json"
            with self.assertRaisesRegex(ValueError, "symlink"):
                builder.build(copied, output, None, evidence)
            self.assertFalse(output.exists())
            target.unlink()
            shutil.copy2(ROOT / "writing-plans" / "references" / "profiles" / "brief.md", target)
            policy_path = copied / "software-quality-workflows" / "registries" / "policy-owners.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["policies"][0]["owner_id"] = "scripts/tampered-owner.py"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact two-skill source"):
                builder.build(copied, output, None, evidence)
            self.assertFalse(output.exists())
            shutil.copy2(
                ROOT / "software-quality-workflows" / "registries" / "policy-owners.json",
                policy_path,
            )
            manifest_path = copied / "bundle-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["skills"][0]["version"] = "9.9.9"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "version mismatch"):
                builder.build(copied, output, None, evidence)
            self.assertFalse(output.exists())

    def test_static_discovery_install_and_uninstall_smoke_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "frontier-engineering-plugin"
            evidence = parent / "evidence.json"
            builder.build(ROOT, output, None, evidence)
            result = smoke.isolated_smoke(output, evidence)
            self.assertEqual({"writing-plans", "software-quality-workflows"}, set(result["discovered_skills"]))
            self.assertTrue(result["isolated_install_discovery"])
            self.assertTrue(result["uninstall_clean"])
            self.assertFalse(result["actual_codex_cli_install"])
            self.assertFalse(result["model_invoked"])
            self.assertEqual("implicit_local_pilot", result["activation_ceiling"])
            self.assertTrue(all(item["implicit_eligible"] for item in result["discovered_skills"].values()))
            schema = json.loads((ROOT / "packaging" / "schemas" / "static-plugin-smoke.schema.json").read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(result)))
            target = output / "skills" / "writing-plans" / "SKILL.md"
            target.write_text(target.read_text(encoding="utf-8") + "\nmutation\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                smoke.isolated_smoke(output, evidence)

    def test_actual_codex_cli_install_and_remove_smoke_is_isolated_and_hash_bound(self) -> None:
        if shutil.which("codex") is None or not PLUGIN_VALIDATOR.is_file() or not PLUGIN_SCAFFOLDER.is_file():
            self.skipTest("Codex plugin CLI or plugin-creator helpers are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            marketplace = parent / "marketplace"
            work = parent / "work"
            work.mkdir()
            scaffold = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN_SCAFFOLDER),
                    "frontier-engineering-plugin",
                    "--path",
                    str(marketplace / "plugins"),
                    "--with-skills",
                    "--with-marketplace",
                    "--marketplace-path",
                    str(marketplace / ".agents" / "plugins" / "marketplace.json"),
                    "--marketplace-name",
                    "frontier-engineering-implicit-local",
                    "--install-policy",
                    "AVAILABLE",
                    "--auth-policy",
                    "ON_INSTALL",
                    "--category",
                    "Developer Tools",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, scaffold.returncode, scaffold.stderr or scaffold.stdout)
            plugin = marketplace / "plugins" / "frontier-engineering-plugin"
            scaffold_backup = parent / "scaffold-backup"
            plugin.rename(scaffold_backup)
            evidence = parent / "build-evidence.json"
            builder.build(ROOT, plugin, None, evidence)
            static_path = parent / "static-smoke.json"
            static_path.write_text(
                json.dumps(smoke.isolated_smoke(plugin, evidence), sort_keys=True),
                encoding="utf-8",
            )
            result = cli_smoke.run_cli_smoke(
                plugin,
                evidence,
                static_path,
                marketplace,
                work,
                PLUGIN_VALIDATOR,
            )
            schema = json.loads((ROOT / "packaging" / "schemas" / "cli-install-smoke.schema.json").read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(result)))
            self.assertTrue(result["actual_codex_cli_install"])
            self.assertTrue(result["uninstall_clean"])
            self.assertTrue(result["marketplace_removed"])
            self.assertEqual("not_run_model_free", result["implicit_route_invocation"])
            self.assertEqual("implicit_local_pilot", result["activation_ceiling"])
            self.assertFalse(result["release_eligible"])
            self.assertEqual(
                ["scored_l2_gate", "activation_decision", "signed_clean_source_revision"],
                result["blocking_prerequisites"],
            )
            unhashed = deepcopy(result)
            observed_hash = unhashed.pop("evidence_hash")
            self.assertEqual(
                observed_hash,
                "sha256:" + sha256(json.dumps(unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            )
            self.assertEqual([], list(work.iterdir()))

            tampered = parent / "tampered-build-evidence.json"
            tampered_payload = json.loads(evidence.read_text(encoding="utf-8"))
            tampered_payload["source_file_count"] += 1
            tampered.write_text(json.dumps(tampered_payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "self-hash"):
                cli_smoke.run_cli_smoke(
                    plugin,
                    tampered,
                    static_path,
                    marketplace,
                    work,
                    PLUGIN_VALIDATOR,
                )
            real_agents = marketplace / "real-agents"
            (marketplace / ".agents").rename(real_agents)
            (marketplace / ".agents").symlink_to(real_agents.name, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinked marketplace"):
                cli_smoke.run_cli_smoke(
                    plugin,
                    evidence,
                    static_path,
                    marketplace,
                    work,
                    PLUGIN_VALIDATOR,
                )

    def test_cli_smoke_strips_credentials_and_rehomes_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            isolated = Path(directory)
            with mock.patch.dict(
                cli_smoke.os.environ,
                {
                    "PATH": cli_smoke.os.environ.get("PATH", ""),
                    "OPENAI_API_KEY": "secret",
                    "CUSTOM_TOKEN": "secret",
                    "SESSION_COOKIE": "secret",
                    "CODEX_HOME": "/not-isolated",
                    "XDG_CONFIG_HOME": "/not-isolated",
                    "SAFE_VALUE": "kept",
                },
                clear=True,
            ):
                environment = cli_smoke._safe_environment(isolated)
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("CUSTOM_TOKEN", environment)
            self.assertNotIn("SESSION_COOKIE", environment)
            self.assertEqual("kept", environment["SAFE_VALUE"])
            self.assertEqual(str(isolated), environment["HOME"])
            self.assertEqual(str(isolated / ".codex"), environment["CODEX_HOME"])
            self.assertEqual(str(isolated / ".config"), environment["XDG_CONFIG_HOME"])

    def test_source_drift_during_copy_aborts_and_cleans_partial_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            copied = parent / "bundle"
            shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            output = parent / "frontier-engineering-plugin"
            evidence = parent / "evidence.json"
            original_copytree = builder.shutil.copytree
            changed = False

            def drifting_copytree(source: Path, destination: Path, *args: object, **kwargs: object) -> Path:
                nonlocal changed
                result = original_copytree(source, destination, *args, **kwargs)
                if not changed:
                    changed = True
                    target = copied / "writing-plans" / "references" / "profiles" / "brief.md"
                    target.write_text(target.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
                return result

            with mock.patch.object(builder.shutil, "copytree", side_effect=drifting_copytree):
                with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
                    builder.build(copied, output, None, evidence)
            self.assertFalse(output.exists())
            self.assertFalse(evidence.exists())
            self.assertTrue((parent / "plugin-build-staging").is_dir())


if __name__ == "__main__":
    unittest.main()
