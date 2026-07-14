#!/usr/bin/env python3
"""Freeze a validated Closure Contract into a separate immutable lock file."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from _closure_contract import ContractInputError, canonical_contract_hash, load_contract
from validate_closure_contract import AUTHORITY_RANK, validate_contract


def _atomic_create_read_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o400)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ContractInputError(f"refusing to overwrite existing contract lock: {path}") from exc
        os.chmod(path, 0o444)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def freeze_contract(
    draft_path: str | Path,
    output_path: str | Path,
    schema_path: str | Path,
    *,
    frozen_at: str,
    expected_scope_hash: str | None = None,
    authority_ceiling: str | None = None,
    expected_base_revision: str | None = None,
    expected_policy_bundle_hash: str | None = None,
    expected_authority_hash: str | None = None,
) -> dict[str, Any]:
    draft_file = Path(draft_path)
    output_file = Path(output_path)
    if any(value is None for value in (expected_scope_hash, authority_ceiling, expected_base_revision, expected_policy_bundle_hash, expected_authority_hash)):
        raise ContractInputError("freeze requires admitted source, scope, policy bundle, and authority bindings")
    if draft_file.resolve() == output_file.resolve():
        raise ContractInputError("draft and frozen lock paths must be different")
    if output_file.exists():
        raise ContractInputError(f"refusing to overwrite existing contract lock: {output_file}")
    draft = load_contract(draft_file)
    schema = load_contract(schema_path)
    violations = validate_contract(
        draft,
        schema,
        for_freeze=True,
        expected_scope_hash=expected_scope_hash,
        authority_ceiling=authority_ceiling,
        expected_base_revision=expected_base_revision,
        expected_policy_bundle_hash=expected_policy_bundle_hash,
        expected_authority_hash=expected_authority_hash,
    )
    if violations:
        codes = sorted({item.code for item in violations})
        raise ContractInputError(f"contract is not freezable: {codes}")
    frozen = deepcopy(draft)
    frozen["status"] = "frozen"
    frozen["frozen_at"] = frozen_at
    frozen["content_hash"] = canonical_contract_hash(frozen)
    post_violations = validate_contract(
        frozen,
        schema,
        expected_scope_hash=expected_scope_hash,
        authority_ceiling=authority_ceiling,
        expected_base_revision=expected_base_revision,
        expected_policy_bundle_hash=expected_policy_bundle_hash,
        expected_authority_hash=expected_authority_hash,
    )
    if post_violations:
        codes = sorted({item.code for item in post_violations})
        raise ContractInputError(f"frozen contract failed self-validation: {codes}")
    payload = (json.dumps(frozen, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_create_read_only(output_file, payload)
    return {
        "ok": True,
        "output": str(output_file),
        "contract_id": frozen["contract_id"],
        "content_hash": frozen["content_hash"],
        "epoch": frozen["epoch"],
        "event": {
            "event_type": "contract_frozen",
            "contract_id": frozen["contract_id"],
            "content_hash": frozen["content_hash"],
            "epoch": frozen["epoch"],
            "source_revision": frozen["source"]["base_revision"],
            "scope_hash": frozen["source"]["scope_hash"],
            "policy_bundle_hash": frozen["source"]["policy_bundle_hash"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--expected-scope-hash", required=True)
    parser.add_argument("--authority-ceiling", required=True, choices=sorted(AUTHORITY_RANK))
    parser.add_argument("--expected-base-revision", required=True)
    parser.add_argument("--expected-policy-bundle-hash", required=True)
    parser.add_argument("--expected-authority-hash", required=True)
    args = parser.parse_args(argv)
    try:
        result = freeze_contract(
            args.draft,
            args.output,
            args.schema,
            frozen_at=args.frozen_at,
            expected_scope_hash=args.expected_scope_hash,
            authority_ceiling=args.authority_ceiling,
            expected_base_revision=args.expected_base_revision,
            expected_policy_bundle_hash=args.expected_policy_bundle_hash,
            expected_authority_hash=args.expected_authority_hash,
        )
    except (ContractInputError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "contract.freeze", "message": str(exc)}}, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
