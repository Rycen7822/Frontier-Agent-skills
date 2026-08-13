#!/usr/bin/env python3
"""Create one canonical release-owner authorization for a frozen plugin."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import _release_authorization as release_contract
import build_codex_plugin as builder
import evaluate_static_contracts as static_contracts


ROOT = Path(__file__).resolve().parents[1]


def create_authorization(
    source_root: Path,
    plugin_root: Path,
    qualification_path: Path,
    *,
    authority_id: str,
    signature_attestation_path: Path,
) -> dict[str, object]:
    source_root = source_root.resolve(strict=True)
    plugin_root = plugin_root.resolve(strict=True)
    qualification_path = qualification_path.resolve(strict=True)
    qualification = builder._strict_json(qualification_path)
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
    static_report = static_contracts.build_report(source_root)
    if static_contracts.blocking_fact_count(static_report):
        raise ValueError("static contract gate has blocking facts")
    authorization = release_contract.create_authorization(
        qualification,
        static_gate={
            "schema_version": static_report["schema_version"],
            "status": "pass",
        },
        authority_id=authority_id,
        signature_attestation=attestation,
    )
    return builder._validate_release_authorization(
        authorization,
        qualification,
        source_root=source_root,
        manifest=manifest,
        source_tree_hash=builder.tree_hash(source_records),
        plugin_tree_hash=builder.tree_hash(plugin_records),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
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
            args.qualification,
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
    print(json.dumps({
        "ok": True,
        "bundle_id": authorization["bundle_id"],
        "bundle_version": authorization["bundle_version"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
