#!/usr/bin/env python3
"""Run one bounded Writing Plans route or card completion cycle."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator

from _writing_reference_cards import load_json, strict_json_bytes
from assess_plan_mode import assess, validate_plan_route_result
from render_plan_profile import render_brief


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "card-protocol.schema.json"
REGISTRY_PATH = ROOT / "registries" / "artifact-family-contracts.json"
MANIFEST_PATH = ROOT / "registries" / "reference-cards.manifest.json"
COMMAND_MAX_BYTES = 65_536
RECEIPT_MAX_BYTES = 12_288
SOURCE_FILE_MAX_BYTES = 8 * 1024 * 1024
SOURCE_TOTAL_MAX_BYTES = 32 * 1024 * 1024
SOURCE_MAX_FILES = 4_096


class CycleError(ValueError):
    def __init__(self, code: str, message: str, *, exit_code: int = 2, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.retryable = retryable


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_json(value: Any) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _load_contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    schema = load_json(SCHEMA_PATH)
    registry = load_json(REGISTRY_PATH)
    manifest = load_json(MANIFEST_PATH)
    try:
        Draft202012Validator.check_schema(schema)
        registry_schema = {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": "#/$defs/artifactContractRegistry",
        }
        errors = list(Draft202012Validator(registry_schema).iter_errors(registry))
    except (KeyError, TypeError, ValueError) as exc:
        raise CycleError("E_CONTRACT_INVALID", "card protocol contract is invalid", exit_code=5) from exc
    if errors:
        raise CycleError("E_CONTRACT_INVALID", "artifact registry is invalid", exit_code=5)
    families = registry["families"]
    if set(registry["artifacts"].values()) != set(families):
        raise CycleError("E_CONTRACT_INVALID", "artifact registry contains missing or unused families", exit_code=5)
    for family in families.values():
        for field in ("human_def", "payload_def"):
            if family[field].split("/")[-1] not in schema["$defs"]:
                raise CycleError("E_CONTRACT_INVALID", "artifact registry references an unknown definition", exit_code=5)
    return schema, registry, manifest


def _read_command() -> dict[str, Any]:
    data = sys.stdin.buffer.read(COMMAND_MAX_BYTES + 1)
    if len(data) > COMMAND_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "command exceeds the byte limit", exit_code=4)
    try:
        command = strict_json_bytes(data, source="stdin")
    except ValueError as exc:
        raise CycleError("E_COMMAND_SCHEMA", "command is not strict UTF-8 JSON") from exc
    if not isinstance(command, dict):
        raise CycleError("E_COMMAND_SCHEMA", "command must be one JSON object")
    return command


def _validate(
    schema: dict[str, Any],
    definition: str,
    value: Any,
    code: str,
    *,
    exit_code: int = 2,
) -> None:
    validator_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    errors = sorted(Draft202012Validator(validator_schema).iter_errors(value), key=lambda item: list(item.path))
    if errors:
        field = "/".join(str(part) for part in errors[0].absolute_path) or definition
        raise CycleError(code, f"{definition} field is invalid: {field}", exit_code=exit_code)


def _stable_stat(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_source_file(path: Path) -> tuple[str, int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source file cannot be opened", exit_code=5) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > SOURCE_FILE_MAX_BYTES:
            raise CycleError("E_SOURCE_UNAVAILABLE", "source contains an unsafe file", exit_code=5)
        payload = bytearray()
        while len(payload) <= SOURCE_FILE_MAX_BYTES:
            chunk = os.read(descriptor, min(65_536, SOURCE_FILE_MAX_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if len(payload) > SOURCE_FILE_MAX_BYTES or _stable_stat(before) != _stable_stat(after):
            raise CycleError("E_SOURCE_DRIFT", "source changed during observation", exit_code=3, retryable=True)
        data = bytes(payload)
        return _hash_bytes(data), len(data), f"{stat.S_IMODE(before.st_mode):04o}"
    finally:
        os.close(descriptor)


def _source_observation(source_root: Path) -> dict[str, Any]:
    try:
        info = source_root.lstat()
        resolved = source_root.resolve(strict=True)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root is unavailable", exit_code=5) from exc
    if source_root.is_symlink() or not stat.S_ISDIR(info.st_mode) or resolved != source_root.absolute():
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root is not canonical", exit_code=5)
    if (resolved / ".git").exists():
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository source support is not active in this slice", exit_code=5)

    records: list[dict[str, Any]] = []
    total = 0
    for current, directories, filenames in os.walk(resolved, followlinks=False):
        directories.sort()
        filenames.sort()
        current_path = Path(current)
        for name in directories:
            entry_info = (current_path / name).lstat()
            if stat.S_ISLNK(entry_info.st_mode) or not stat.S_ISDIR(entry_info.st_mode):
                raise CycleError("E_SOURCE_UNAVAILABLE", "source contains an unsafe directory", exit_code=5)
        for name in filenames:
            entry = current_path / name
            relative = entry.relative_to(resolved).as_posix()
            if any(ord(character) < 32 for character in relative):
                raise CycleError("E_SOURCE_UNAVAILABLE", "source contains an invalid path", exit_code=5)
            content_hash, size, mode = _read_source_file(entry)
            total += size
            if total > SOURCE_TOTAL_MAX_BYTES or len(records) >= SOURCE_MAX_FILES:
                raise CycleError("E_SOURCE_UNAVAILABLE", "source observation exceeds its bound", exit_code=5)
            records.append({"path": relative, "content_hash": content_hash, "bytes": size, "mode": mode})
    return {"kind": "unversioned", "root_binding": {"dev": info.st_dev, "ino": info.st_ino}, "records": records}


def _capture_source(source_root: Path) -> dict[str, str]:
    opening = _source_observation(source_root)
    closing = _source_observation(source_root)
    if opening != closing:
        raise CycleError("E_SOURCE_DRIFT", "source changed during the stability fence", exit_code=3, retryable=True)
    return {"kind": "unversioned", "identity_hash": _hash_json(opening)}


def _validate_delivery_root(path: Path) -> tuple[Path, dict[str, int]]:
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CycleError("E_ROOT_ROLE", "projection root is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or resolved != path.absolute()
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise CycleError("E_ROOT_ROLE", "projection root is unsafe")
    return resolved, {"dev": info.st_dev, "ino": info.st_ino}


def _receipt_id(receipt: dict[str, Any]) -> str:
    return _hash_json({key: value for key, value in receipt.items() if key != "receipt_id"})


def _base_receipt(manifest: dict[str, Any], source_identity: dict[str, str], next_step: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "wp-card-receipt/1",
        "receipt_kind": "route",
        "receipt_id": "",
        "bundle_id": manifest["bundle_id"],
        "skill_id": "writing-plans",
        "source_identity": source_identity,
        "next_step": next_step,
        "route_context": None,
        "completion": None,
        "planning_scope_binding": None,
        "content_locator": None,
    }


def _card(manifest: dict[str, Any], card_id: str) -> dict[str, Any]:
    matches = [card for card in manifest.get("cards", []) if card.get("card_id") == card_id]
    if len(matches) != 1:
        raise CycleError("E_CONTRACT_INVALID", "selected card is unavailable", exit_code=5)
    return matches[0]


def _next_card(manifest: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    if route.get("route_action") != "select_card" or route.get("primary_card") is None:
        raise CycleError("E_UNSUPPORTED_VARIANT", "this slice requires a card route", exit_code=4)
    card = _card(manifest, route["primary_card"]["card_id"])
    return {
        "kind": "card",
        "decision_id": route["selected_decision_id"],
        "card_id": card["card_id"],
        "card_path": card["path"],
        "card_hash": card["sha256"],
    }


def _route_initial(command: dict[str, Any], manifest: dict[str, Any], source_identity: dict[str, str]) -> dict[str, Any]:
    facts = {
        "schema_version": "2.0",
        "route_phase": "entry",
        **command["fields"],
        "pending_decision_ids": [],
        "available_artifact_ids": [],
        "completed_decision_ids": [],
        "just_completed_card_id": None,
        "decision_request": None,
    }
    route = assess(facts)
    if validate_plan_route_result(route):
        raise CycleError("E_CONTRACT_INVALID", "plan route result is invalid", exit_code=5)
    receipt = _base_receipt(manifest, source_identity, _next_card(manifest, route))
    receipt["route_context"] = command["fields"]
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _validate_previous(schema: dict[str, Any], previous: Any, source_identity: dict[str, str]) -> dict[str, Any]:
    _validate(schema, "receipt", previous, "E_RECEIPT_INVALID", exit_code=3)
    if previous["receipt_id"] != _receipt_id(previous):
        raise CycleError("E_RECEIPT_INVALID", "previous receipt hash is invalid", exit_code=3)
    if previous["source_identity"] != source_identity:
        raise CycleError("E_SOURCE_REVISION_CHANGED", "source identity changed", exit_code=3)
    return previous


def _enforce_brief_budget(registry: dict[str, Any], fields: dict[str, Any], outcome: dict[str, Any]) -> None:
    family = registry["families"][registry["artifacts"]["plan-brief"]]
    if len(_canonical({"fields": fields, "outcome": outcome})) > family["human_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "human input exceeds its family budget", exit_code=4)


def _read_regular(path: Path) -> tuple[bytes, os.stat_result]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise CycleError("E_ORPHAN_CONFLICT", "projection target is unsafe", exit_code=5) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink not in {1, 2}:
            raise CycleError("E_ORPHAN_CONFLICT", "projection target is unsafe", exit_code=5)
        payload = bytearray()
        while len(payload) <= 32_768:
            chunk = os.read(descriptor, min(65_536, 32_769 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if len(payload) > 32_768 or _stable_stat(before) != _stable_stat(after):
            raise CycleError("E_ORPHAN_CONFLICT", "projection target is unstable", exit_code=5)
        return bytes(payload), before
    finally:
        os.close(descriptor)


def _fsync_directory(root: Path) -> None:
    descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _publish_immutable(root: Path, filename: str, payload: bytes) -> None:
    final = root / filename
    temporary = root / f"{filename}.tmp"
    final_info = _lstat_optional(final)
    temp_info = _lstat_optional(temporary)

    if final_info is not None:
        final_bytes, final_stat = _read_regular(final)
        if final_bytes != payload or stat.S_IMODE(final_stat.st_mode) != 0o600:
            raise CycleError("E_ORPHAN_CONFLICT", "projection final conflicts", exit_code=5)
        if temp_info is None:
            return
        temp_bytes, temp_stat = _read_regular(temporary)
        if temp_bytes != payload or (final_stat.st_dev, final_stat.st_ino) != (temp_stat.st_dev, temp_stat.st_ino):
            raise CycleError("E_ORPHAN_CONFLICT", "projection temp conflicts", exit_code=5)
        temporary.unlink()
        _fsync_directory(root)
        return

    if temp_info is not None:
        temp_bytes, temp_stat = _read_regular(temporary)
        if temp_bytes != payload or stat.S_IMODE(temp_stat.st_mode) != 0o600 or temp_stat.st_nlink != 1:
            raise CycleError("E_ORPHAN_CONFLICT", "projection temp conflicts", exit_code=5)
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.link(temporary, final, follow_symlinks=False)
    _fsync_directory(root)
    temporary.unlink()
    _fsync_directory(root)


def _complete_brief(
    command: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
    projection_root: Path,
    root_binding: dict[str, int],
) -> dict[str, Any]:
    if previous["next_step"].get("card_id") != "wp.profiles.brief" or previous["route_context"] is None:
        raise CycleError("E_RECEIPT_INVALID", "brief completion does not match the active card", exit_code=3)
    _enforce_brief_budget(registry, command["fields"], command["outcome"])
    rendered = render_brief(command["fields"]).encode("utf-8")
    family = registry["families"][registry["artifacts"]["plan-brief"]]
    if len(rendered) > family["payload_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "brief projection exceeds its payload budget", exit_code=4)

    payload_hash = _hash_json(command["fields"])
    content_hash = _hash_bytes(rendered)
    scope_payload = {
        "profile": "brief",
        "allowed_plan_outputs": ["plan-brief"],
        "delivery_root_binding_hash": _hash_json(root_binding),
        "source_identity": source_identity,
    }
    scope_binding = {key: value for key, value in scope_payload.items() if key != "source_identity"}
    scope_binding["binding_id"] = _hash_json(scope_payload)
    completion_payload = {
        "artifact_id": "plan-brief",
        "producer_card_id": previous["next_step"]["card_id"],
        "decision_id": previous["next_step"]["decision_id"],
        "payload_hash": payload_hash,
        "outcome": {"blocker": command["outcome"]["blocker"], "decision_request": None},
        "source_identity": source_identity,
        "scope_binding_id": scope_binding["binding_id"],
    }
    completion = {key: value for key, value in completion_payload.items() if key not in {"source_identity", "scope_binding_id"}}
    completion["completion_id"] = _hash_json(completion_payload)
    locator = {
        "schema_version": "content-locator/1",
        "content_kind": "projection",
        "artifact_id": "plan-brief",
        "content_hash": content_hash,
        "bytes": len(rendered),
    }
    filename = f"plan-brief--{content_hash.removeprefix('sha256:')}.md"
    _publish_immutable(projection_root, filename, rendered)

    receipt = _base_receipt(manifest, source_identity, {"kind": "terminal", "status": "brief_complete"})
    receipt.update({
        "receipt_kind": "completion",
        "completion": completion,
        "planning_scope_binding": scope_binding,
        "content_locator": locator,
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.input != "-":
        raise CycleError("E_COMMAND_SCHEMA", "--input must be stdin")
    schema, registry, manifest = _load_contracts()
    command = _read_command()
    _validate(schema, "command", command, "E_COMMAND_SCHEMA")
    is_route = command["contract_id"] == "wp.route.initial/1"
    if args.subcommand != ("route" if is_route else "complete"):
        raise CycleError("E_COMMAND_SCHEMA", "subcommand does not match contract")
    if args.work_root is not None or args.artifact_root is not None:
        raise CycleError("E_ROOT_ROLE", "command received an unsupported root")
    if is_route and args.projection_root is not None:
        raise CycleError("E_ROOT_ROLE", "route does not accept a projection root")
    if not is_route and args.projection_root is None:
        raise CycleError("E_ROOT_ROLE", "brief completion requires a projection root")

    projection: Path | None = None
    root_binding: dict[str, int] | None = None
    if args.projection_root is not None:
        projection, root_binding = _validate_delivery_root(Path(args.projection_root))
    source_root = Path(args.source_root)
    if projection is not None:
        source_resolved = source_root.resolve(strict=True)
        if projection == source_resolved or projection.is_relative_to(source_resolved):
            raise CycleError("E_UNSUPPORTED_VARIANT", "source-contained projection is not active in this slice", exit_code=4)
    source_identity = _capture_source(source_root)
    if is_route:
        receipt = _route_initial(command, manifest, source_identity)
    else:
        previous = _validate_previous(schema, command["previous_receipt"], source_identity)
        if previous["bundle_id"] != manifest["bundle_id"]:
            raise CycleError("E_RECEIPT_INVALID", "previous receipt bundle is stale", exit_code=3)
        if command["contract_id"] != "wp.complete.brief/1":
            raise CycleError("E_UNSUPPORTED_VARIANT", "command contract is not active", exit_code=4)
        assert projection is not None and root_binding is not None
        receipt = _complete_brief(command, manifest, registry, previous, source_identity, projection, root_binding)
    _validate(schema, "receipt", receipt, "E_CONTRACT_INVALID")
    if len(_canonical(receipt)) + 1 > RECEIPT_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "receipt exceeds the byte limit", exit_code=4)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    for name in ("route", "complete", "render"):
        command = subparsers.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--source-root", required=True)
        command.add_argument("--work-root")
        command.add_argument("--artifact-root")
        command.add_argument("--projection-root")
    return parser


def _emit_error(error: CycleError) -> int:
    payload = {
        "code": error.code,
        "message": " ".join(str(error).split())[:512] or "card cycle failed",
        "retryable": error.retryable,
    }
    encoded = _canonical(payload)
    if len(encoded) > 1_024:
        payload["message"] = "card cycle failed"
        encoded = _canonical(payload)
    sys.stderr.buffer.write(encoded + b"\n")
    return error.exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = _execute(args)
    except CycleError as exc:
        return _emit_error(exc)
    except (AssertionError, KeyError, OSError, TypeError, ValueError):
        return _emit_error(CycleError("E_CONTRACT_INVALID", "card cycle failed", exit_code=5))
    sys.stdout.buffer.write(_canonical(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
