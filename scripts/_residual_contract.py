#!/usr/bin/env python3
"""Structural contract for bounded Software Quality Workflows evolution."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import yaml

from _evaluation_documents import ContractError, validate_document


MAP_PATH = Path(
    "evaluation/model-evolution/residual-clauses/software-quality-workflows.json"
)
SOURCE_PATH = Path("software-quality-workflows/SKILL.md")
SCENARIOS_PATH = Path(
    "evaluation/model-evolution/sentinels/software-quality-workflows/"
    "scenarios.public.jsonl"
)
CLAUSES = {
    "native-default": (
        "Native default",
        {"software-quality-workflows-routine-local-edit"},
    ),
    "observable-contract": (
        "Observable contract",
        {"software-quality-workflows-cross-cutting-contract"},
    ),
    "evidence-selection": (
        "Evidence selection",
        {
            "software-quality-workflows-routine-local-edit",
            "software-quality-workflows-harness-setup-failure",
            "software-quality-workflows-material-risk-escalation",
        },
    ),
    "failure-ownership": (
        "Failure ownership",
        {
            "software-quality-workflows-preexisting-unrelated-red",
            "software-quality-workflows-invalid-oracle",
            "software-quality-workflows-harness-setup-failure",
        },
    ),
    "progress-stop": (
        "Progress stop",
        {
            "software-quality-workflows-repeated-identical-failure",
            "software-quality-workflows-stochastic-failure",
        },
    ),
    "test-retention": (
        "Test retention",
        {
            "software-quality-workflows-test-retention-boundary",
            "software-quality-workflows-invalid-oracle",
        },
    ),
    "completion-truth": (
        "Completion truth",
        {
            "software-quality-workflows-preexisting-unrelated-red",
            "software-quality-workflows-repeated-identical-failure",
        },
    ),
}


class ResidualError(ValueError):
    """A residual map or single-clause candidate is invalid."""


def _text(raw: bytes, *, label: str) -> str:
    try:
        return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise ResidualError(f"{label} is not UTF-8") from exc


def _document(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ResidualError("SQW source lacks YAML frontmatter")
    frontmatter_text, body = text[4:].split("\n---\n", 1)
    value = yaml.safe_load(frontmatter_text)
    if not isinstance(value, dict):
        raise ResidualError("SQW frontmatter is not an object")
    return value, body


def _sections(body: str) -> tuple[str, list[str], dict[str, str]]:
    matches = list(re.finditer(r"(?m)^## ([^\n]+)\n", body))
    headings = [match.group(1) for match in matches]
    if len(headings) != len(set(headings)):
        raise ResidualError("SQW H2 headings must be unique")
    sections = {
        heading: body[match.start() : matches[index + 1].start()]
        if index + 1 < len(matches)
        else body[match.start() :]
        for index, (heading, match) in enumerate(zip(headings, matches, strict=True))
    }
    prelude = body[: matches[0].start()] if matches else body
    return prelude, headings, sections


def _public_cases(raw: bytes) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(
        _text(raw, label="SQW scenarios").splitlines(), 1
    ):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ResidualError(f"SQW scenario line {line_number} is not JSON") from exc
        case_id = value.get("case_id") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or not isinstance(case_id, str)
            or case_id in result
            or value.get("split") not in {"dev", "regression"}
        ):
            raise ResidualError("SQW public case identity or split is invalid")
        result[case_id] = value
    if not result:
        raise ResidualError("SQW public scenario set is empty")
    return result


def load_clause_map(
    map_raw: bytes,
    source_raw: bytes,
    scenarios_raw: bytes,
) -> tuple[dict[str, Any], dict[str, str], set[str]]:
    try:
        value = json.loads(_text(map_raw, label="residual clause map"))
        clause_map = validate_document(value, "residual_clause_map")
    except (json.JSONDecodeError, ContractError) as exc:
        raise ResidualError(str(exc)) from exc
    rows = clause_map["clauses"]
    by_id = {row["clause_id"]: row for row in rows}
    if len(by_id) != len(rows) or not by_id or not set(by_id) <= set(CLAUSES):
        raise ResidualError("residual clause IDs must be a unique canonical subset")
    cases = set(_public_cases(scenarios_raw))
    headings: set[str] = set()
    for clause_id, row in by_id.items():
        expected_heading, required_cases = CLAUSES[clause_id]
        if (
            row["source_path"] != SOURCE_PATH.as_posix()
            or row["section_heading"] != expected_heading
            or not required_cases <= set(row["case_ids"])
            or not set(row["case_ids"]) <= cases
            or row["section_heading"] in headings
        ):
            raise ResidualError(f"residual clause binding is invalid: {clause_id}")
        headings.add(row["section_heading"])
    _, source_body = _document(_text(source_raw, label="SQW source"))
    _, source_headings, sections = _sections(source_body)
    if source_headings != [row["section_heading"] for row in rows]:
        raise ResidualError("residual clauses must match SQW H2 order exactly")
    return clause_map, sections, cases


def validate_repository_contract(root: Path) -> dict[str, Any]:
    clause_map, _, _ = load_clause_map(
        (root / MAP_PATH).read_bytes(),
        (root / SOURCE_PATH).read_bytes(),
        (root / SCENARIOS_PATH).read_bytes(),
    )
    return clause_map
