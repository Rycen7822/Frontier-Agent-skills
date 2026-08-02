from __future__ import annotations

import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BUILDER_PATH = SCRIPTS / "build_codex_plugin.py"
GENERATOR_PATH = SCRIPTS / "create_release_authorization.py"
REVISION = "a" * 40


def load_module(name: str, path: Path):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_bytes(value: dict) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


class ExtendedReleaseAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = load_module("release_authorization_builder", BUILDER_PATH)
        self.manifest = self.builder._strict_json(ROOT / "bundle-manifest.json")
        self.source_tree_hash = self.builder.tree_hash(
            self.builder.validate_source(ROOT, self.manifest)
        )
        self.plugin_tree_hash = "sha256:" + "2" * 64
        self.revision = self.builder._source_revision(ROOT)

    def authorization(self) -> dict:
        bundle = self.builder._strict_json(
            ROOT / "frontier-engineering.bundle.json"
        )
        static = self.builder._strict_json(
            ROOT / "evaluation" / "static-contract-diagnostic.json"
        )
        value = {
            "schema_version": "release-authorization/1",
            "bundle_id": bundle["bundle_id"],
            "bundle_version": self.manifest["bundle_version"],
            "source_revision": self.revision,
            "source_tree_hash": self.source_tree_hash,
            "plugin_tree_hash": self.plugin_tree_hash,
            "deterministic_report_hash": static["report_hash"],
            "approved_skill_activation": dict(
                self.builder.EXPECTED_APPROVED_ACTIVATION
            ),
            "remote_writes": False,
            "authority": {
                "authority_id": "release-owner-1",
                "role": "release_owner",
                "decision": "approve",
                "signature_attestation": "approved in signed release record",
            },
        }
        value["authorization_hash"] = self.builder._self_hash_field(
            value,
            "authorization_hash",
        )
        return value

    def validate(self, value: dict) -> dict:
        with mock.patch.object(
            self.builder,
            "_git_release_source_ok",
            side_effect=lambda _root, revision: revision == self.revision,
        ):
            return self.builder._validate_release_authorization(
                value,
                source_root=ROOT,
                manifest=self.manifest,
                source_tree_hash=self.source_tree_hash,
                plugin_tree_hash=self.plugin_tree_hash,
            )

    def test_schema_and_positive_contract_are_exact(self) -> None:
        authorization = self.authorization()
        schema = self.builder._strict_json(
            ROOT / "packaging" / "schemas"
            / "release-authorization-v1.schema.json"
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(authorization)
        self.assertEqual(authorization, self.validate(authorization))

    def test_identity_authority_and_hash_mutations_fail_closed(self) -> None:
        mutations = {
            "source revision": lambda value: value.__setitem__(
                "source_revision", "b" * 40
            ),
            "source tree": lambda value: value.__setitem__(
                "source_tree_hash", "sha256:" + "3" * 64
            ),
            "plugin tree": lambda value: value.__setitem__(
                "plugin_tree_hash", "sha256:" + "3" * 64
            ),
            "bundle id": lambda value: value.__setitem__(
                "bundle_id", "frontier-engineering/other"
            ),
            "bundle version": lambda value: value.__setitem__(
                "bundle_version", "0.0.0"
            ),
            "static report": lambda value: value.__setitem__(
                "deterministic_report_hash", "sha256:" + "3" * 64
            ),
            "activation": lambda value: value["approved_skill_activation"].__setitem__(
                "skill-evaluator", "implicit"
            ),
            "remote writes": lambda value: value.__setitem__(
                "remote_writes", True
            ),
            "authority role": lambda value: value["authority"].__setitem__(
                "role", "reviewer"
            ),
            "authority decision": lambda value: value["authority"].__setitem__(
                "decision", "reject"
            ),
            "empty authority id": lambda value: value["authority"].__setitem__(
                "authority_id", ""
            ),
            "empty signature": lambda value: value["authority"].__setitem__(
                "signature_attestation", ""
            ),
            "blank signature": lambda value: value["authority"].__setitem__(
                "signature_attestation", "   "
            ),
            "extra field": lambda value: value.__setitem__("extra", True),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value = copy.deepcopy(self.authorization())
                mutate(value)
                value["authorization_hash"] = self.builder._self_hash_field(
                    value,
                    "authorization_hash",
                )
                with self.assertRaises(ValueError):
                    self.validate(value)

        invalid_hash = self.authorization()
        invalid_hash["authorization_hash"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "identity"):
            self.validate(invalid_hash)

    def test_dirty_and_unsigned_sources_fail_independently(self) -> None:
        completed = subprocess.CompletedProcess
        cases = {
            "dirty": [
                completed([], 0, REVISION + "\n", ""),
                completed([], 0, " M tracked.py\n", ""),
                completed([], 0, "", ""),
            ],
            "unsigned": [
                completed([], 0, REVISION + "\n", ""),
                completed([], 0, "", ""),
                completed([], 1, "", "no signature"),
            ],
        }
        for label, results in cases.items():
            with self.subTest(label=label), mock.patch.object(
                self.builder.subprocess,
                "run",
                side_effect=results,
            ):
                self.assertFalse(
                    self.builder._git_release_source_ok(ROOT, REVISION)
                )

    def test_symlink_authorization_and_legacy_cli_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "authorization.json"
            real.write_bytes(canonical_bytes(self.authorization()))
            linked = root / "linked.json"
            linked.symlink_to(real)
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.builder.validate_release_authorization(
                    linked,
                    source_root=ROOT,
                    manifest=self.manifest,
                    source_tree_hash=self.source_tree_hash,
                    plugin_tree_hash=self.plugin_tree_hash,
                )
        legacy = subprocess.run(
            [
                sys.executable,
                str(BUILDER_PATH),
                "--release-" + "evidence",
                "x",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(2, legacy.returncode)
        self.assertIn("unrecognized arguments", legacy.stderr)

    def test_generator_is_canonical_no_overwrite_and_release_bound(self) -> None:
        generator = load_module("release_authorization_generator", GENERATOR_PATH)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging" / "frontier-engineering-plugin"
            staging_evidence = root / "staging-build.json"
            with mock.patch.object(
                generator.builder,
                "_source_revision",
                return_value=REVISION,
            ):
                generator.builder.build(
                    ROOT,
                    staging,
                    None,
                    staging_evidence,
                )
            attestation = root / "attestation.txt"
            attestation.write_text("approved in signed release record\n")
            output = root / "release-authorization.json"
            argv = [
                "--source-root", str(ROOT),
                "--plugin-root", str(staging),
                "--authority-id", "release-owner-1",
                "--signature-attestation", str(attestation),
                "--output", str(output),
            ]
            with (
                mock.patch.object(
                    generator.builder,
                    "_source_revision",
                    return_value=REVISION,
                ),
                mock.patch.object(
                    generator.builder,
                    "_git_release_source_ok",
                    return_value=True,
                ),
            ):
                self.assertEqual(0, generator.main(argv))
                self.assertEqual(1, generator.main(argv))
            authorization = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(canonical_bytes(authorization), output.read_bytes())
            with (
                mock.patch.object(
                    generator.builder,
                    "_source_revision",
                    return_value=REVISION,
                ),
                self.assertRaisesRegex(ValueError, "staging validation forbids"),
            ):
                generator.builder.validate_plugin_build(
                    staging,
                    staging_evidence,
                    source_root=ROOT,
                    release_authorization=output,
                )

            marketplace = root / "release" / "marketplace"
            plugin = marketplace / "plugins" / "frontier-engineering-plugin"
            build_evidence = root / "release-build.json"
            with (
                mock.patch.object(
                    generator.builder,
                    "_source_revision",
                    return_value=REVISION,
                ),
                mock.patch.object(
                    generator.builder,
                    "_git_release_source_ok",
                    return_value=True,
                ),
            ):
                build = generator.builder.build(
                    ROOT,
                    plugin,
                    output,
                    build_evidence,
                    marketplace,
                )
            self.assertEqual("release", build["output_class"])
            self.assertEqual(
                "sha256:" + sha256(output.read_bytes()).hexdigest(),
                build["release_authorization_hash"],
            )
            with (
                mock.patch.object(
                    generator.builder,
                    "_source_revision",
                    return_value=REVISION,
                ),
                self.assertRaisesRegex(ValueError, "requires release authorization"),
            ):
                generator.builder.validate_plugin_build(
                    plugin,
                    build_evidence,
                    source_root=ROOT,
                    release_authorization=None,
                )


if __name__ == "__main__":
    unittest.main()
