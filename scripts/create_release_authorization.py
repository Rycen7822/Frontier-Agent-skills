#!/usr/bin/env python3
"""Create one canonical release-owner authorization for a frozen plugin."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import build_codex_plugin as builder


ROOT = Path(__file__).resolve().parents[1]


def create_authorization(
    source_root: Path,
    plugin_root: Path,
    *,
    authority_id: str,
    signature_attestation_path: Path,
) -> dict[str, object]:
    source_root = source_root.resolve(strict=True)
    plugin_root = plugin_root.resolve(strict=True)
    manifest = builder._strict_json(source_root / "bundle-manifest.json")
    source_records = builder.validate_source(source_root, manifest)
    plugin_records = builder._validate_staging(
        plugin_root,
        "frontier-engineering-plugin",
    )
    attestation = builder._regular_bytes(
        signature_attestation_path,
        16 * 1024,
    ).decode("utf-8", errors="strict").strip()
    authority_id = authority_id.strip()
    if not authority_id or not attestation:
        raise ValueError("release authority id and signature attestation are required")
    static_report = builder._strict_json(
        source_root / "evaluation" / "static-contract-diagnostic.json"
    )
    bundle = builder._strict_json(
        source_root / "frontier-engineering.bundle.json"
    )
    authorization: dict[str, object] = {
        "schema_version": "release-authorization/1",
        "bundle_id": bundle["bundle_id"],
        "bundle_version": manifest["bundle_version"],
        "source_revision": builder._source_revision(source_root),
        "source_tree_hash": builder.tree_hash(source_records),
        "plugin_tree_hash": builder.tree_hash(plugin_records),
        "deterministic_report_hash": static_report["report_hash"],
        "approved_skill_activation": dict(builder.EXPECTED_APPROVED_ACTIVATION),
        "remote_writes": False,
        "authority": {
            "authority_id": authority_id,
            "role": "release_owner",
            "decision": "approve",
            "signature_attestation": attestation,
        },
    }
    authorization["authorization_hash"] = builder._self_hash_field(
        authorization,
        "authorization_hash",
    )
    return builder._validate_release_authorization(
        authorization,
        source_root=source_root,
        manifest=manifest,
        source_tree_hash=str(authorization["source_tree_hash"]),
        plugin_tree_hash=str(authorization["plugin_tree_hash"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--signature-attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source_root = args.source_root.resolve(strict=True)
        output = args.output.absolute()
        if output == source_root or output.is_relative_to(source_root):
            raise ValueError("authorization output must be outside the source tree")
        builder._reject_symlink_components(output)
        if output.exists() or output.is_symlink():
            raise ValueError("authorization output is no-overwrite")
        authorization = create_authorization(
            source_root,
            args.plugin_root,
            authority_id=args.authority_id,
            signature_attestation_path=args.signature_attestation,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        builder._reject_symlink_components(output)
        payload = (
            json.dumps(
                authorization,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
        descriptor = os.open(
            output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "authorization_hash": authorization["authorization_hash"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
