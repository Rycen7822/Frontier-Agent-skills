#!/usr/bin/env python3
"""Shared model-evolution schemas, hashing, and artifact bindings."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import jsonschema


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPOSITORY_ROOT / "evaluation/model-evolution/schemas"
SCHEMA_FILES = {
    "qualification": "qualification-v3.schema.json",
    "residual_clause_map": "residual-clause-map-v1.schema.json",
}


class ContractError(ValueError):
    """A deterministic contract or binding failure."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def strict_json_bytes(raw: bytes, *, label: str) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ContractError(f"{label} contains non-finite number {value}")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not strict UTF-8 JSON") from exc


def load_json(path: Path, *, label: str | None = None) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label or path.name} must be a regular non-symlink file")
    return strict_json_bytes(path.read_bytes(), label=label or path.name)


def _schema(name: str) -> dict[str, Any]:
    try:
        path = SCHEMA_ROOT / SCHEMA_FILES[name]
    except KeyError as exc:
        raise ContractError(f"unknown schema {name!r}") from exc
    value = load_json(path, label=f"{name} schema")
    if not isinstance(value, dict):
        raise ContractError(f"{name} schema is not an object")
    return value


def validate_schema(value: Any, name: str) -> None:
    try:
        jsonschema.Draft202012Validator(
            _schema(name), format_checker=jsonschema.FormatChecker()
        ).validate(value)
    except jsonschema.ValidationError as exc:
        location = "/" + "/".join(str(item) for item in exc.absolute_path)
        raise ContractError(
            f"{name} schema violation at {location}: {exc.message}"
        ) from exc


def validate_document(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} document must be an object")
    validate_schema(value, name)
    return value


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError("timestamp must be UTC and end in Z")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ContractError("timestamp is not ISO-8601 UTC") from exc
