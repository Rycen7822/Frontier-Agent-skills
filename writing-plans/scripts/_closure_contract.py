#!/usr/bin/env python3
"""Strict Closure Contract loading, canonical hashing, and ID/ref helpers."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from _plan_state import PlanInputError, load_json


class ContractInputError(ValueError):
    """A bounded Closure Contract input could not be read safely."""


def load_contract(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if source.is_symlink():
        raise ContractInputError(f"refusing symlinked Closure Contract input: {source}")
    try:
        value = load_json(source)
    except PlanInputError as exc:
        raise ContractInputError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ContractInputError("Closure Contract must be a JSON object")
    return value


def canonical_contract_payload(contract: dict[str, Any]) -> bytes:
    clean = deepcopy(contract)
    clean.pop("content_hash", None)
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_contract_hash(contract: dict[str, Any]) -> str:
    return "sha256:" + sha256(canonical_contract_payload(contract)).hexdigest()


def canonical_object_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def iter_id_objects(contract: dict[str, Any]) -> Iterable[tuple[str, int, dict[str, Any]]]:
    for collection in ("assumptions", "hard_constraints", "soft_objectives", "corners", "protected_surfaces", "verifier_requirements", "ambiguities"):
        values = contract.get(collection, [])
        if isinstance(values, list):
            for index, value in enumerate(values):
                if isinstance(value, dict) and isinstance(value.get("id"), str):
                    yield collection, index, value


def id_index(contract: dict[str, Any]) -> tuple[dict[str, tuple[str, int]], set[str]]:
    index: dict[str, tuple[str, int]] = {}
    duplicates: set[str] = set()
    for collection, position, value in iter_id_objects(contract):
        identifier = value["id"]
        if identifier in index:
            duplicates.add(identifier)
        else:
            index[identifier] = (collection, position)
    return index, duplicates


def iter_strings(value: Any, path: tuple[str | int, ...] = ()) -> Iterable[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, path + (index,))
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from iter_strings(child, path + (key,))
