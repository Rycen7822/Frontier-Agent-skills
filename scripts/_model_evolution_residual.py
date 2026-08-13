#!/usr/bin/env python3
"""Structural contract for bounded Software Quality Workflows evolution."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from typing import Any

import yaml

from _model_evolution_contract import ContractError, validate_document


MAP_PATH = Path(
    "evaluation/model-evolution/residual-clauses/software-quality-workflows.json"
)
SOURCE_PATH = Path("software-quality-workflows/SKILL.md")
AGENTS_PATH = Path("software-quality-workflows/agents/openai.yaml")
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
NATIVE_CLASSIFICATIONS = {
    "native_capability_absorption_candidate",
    "stable_no_incremental_value",
}
ROUTING_CLASSIFICATIONS = {"routing_loss", "loading_loss", "application_loss"}


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


def model_visible_bytes(sections: dict[str, str], heading: str) -> int:
    """Compute the LF-normalized section size without persisting another identity."""
    return len(sections[heading].encode("utf-8"))


def resolve_clause(
    clause_map: dict[str, Any], root_cause_ids: list[str], public_cases: set[str]
) -> str:
    rows = {row["clause_id"]: row for row in clause_map["clauses"]}
    clauses = set(root_cause_ids) & set(rows)
    cases = set(root_cause_ids) - set(rows)
    if not root_cause_ids or not cases <= public_cases or len(clauses) > 1:
        raise ResidualError("root causes must identify one residual clause group")
    if clauses:
        selected = next(iter(clauses))
        if not cases <= set(rows[selected]["case_ids"]):
            raise ResidualError("root cause cases do not belong to the selected clause")
        return selected
    matches = [
        clause_id for clause_id, row in rows.items() if cases <= set(row["case_ids"])
    ]
    if len(matches) != 1:
        raise ResidualError(
            "case-only root causes must resolve to exactly one residual clause"
        )
    return matches[0]


def eligible_native_clause(
    clause_map: dict[str, Any],
    sections: dict[str, str],
    current_summary: dict[str, Any],
) -> str | None:
    metric = current_summary.get("paired_metrics", {}).get("task-benefit", {})
    differences = metric.get("case_differences", {})
    if current_summary.get("baseline_ceiling") is not True or not isinstance(
        differences, dict
    ):
        return None
    eligible = [
        row
        for row in clause_map["clauses"]
        if all(
            case_id in differences
            and isinstance(differences[case_id], (int, float))
            and not isinstance(differences[case_id], bool)
            and differences[case_id] == 0
            for case_id in row["case_ids"]
        )
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda row: (
            -model_visible_bytes(sections, row["section_heading"]),
            row["clause_id"],
        )
    )
    return eligible[0]["clause_id"]


def _normalized_frontmatter(value: dict[str, Any], *, routing: bool) -> dict[str, Any]:
    normalized = copy.deepcopy(value)
    metadata = normalized.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("version", None)
    if routing:
        normalized.pop("description", None)
    return normalized


def _normalized_agents(raw: bytes, *, routing: bool) -> dict[str, Any]:
    value = yaml.safe_load(_text(raw, label="SQW agent metadata"))
    if not isinstance(value, dict):
        raise ResidualError("SQW agent metadata is not an object")
    value = copy.deepcopy(value)
    if routing:
        policy = value.get("policy")
        if (
            not isinstance(policy, dict)
            or type(policy.get("allow_implicit_invocation")) is not bool
        ):
            raise ResidualError("SQW activation policy is invalid")
        policy.pop("allow_implicit_invocation")
    return value


def _activation(raw: bytes) -> bool:
    value = yaml.safe_load(_text(raw, label="SQW agent metadata"))
    try:
        activation = value["policy"]["allow_implicit_invocation"]
    except (KeyError, TypeError) as exc:
        raise ResidualError("SQW activation policy is invalid") from exc
    if type(activation) is not bool:
        raise ResidualError("SQW activation policy is invalid")
    return activation


def _validate_single_section_change(
    base_body: str,
    candidate_body: str,
    *,
    heading: str,
    allow_growth: bool,
) -> None:
    base_prelude, base_order, base_sections = _sections(base_body)
    candidate_prelude, candidate_order, candidate_sections = _sections(candidate_body)
    if base_prelude != candidate_prelude:
        raise ResidualError("candidate changes SQW content outside residual clauses")
    expected_order = list(base_order)
    if heading not in candidate_sections:
        expected_order.remove(heading)
    if candidate_order != expected_order:
        raise ResidualError("candidate changes more than one residual clause boundary")
    if any(
        candidate_sections[item] != base_sections[item]
        for item in candidate_order
        if item != heading
    ):
        raise ResidualError("candidate changes a non-selected residual clause")
    if heading not in candidate_sections:
        if allow_growth:
            raise ResidualError("new guidance cannot delete its selected clause")
        return
    before = base_sections[heading]
    after = candidate_sections[heading]
    if allow_growth:
        iterator = iter(after.splitlines(keepends=True))
        if len(after.encode("utf-8")) <= len(before.encode("utf-8")) or not all(
            any(line == candidate_line for candidate_line in iterator)
            for line in before.splitlines(keepends=True)
        ):
            raise ResidualError("new guidance must only add within its selected clause")
        return
    iterator = iter(before.splitlines(keepends=True))
    if len(after.encode("utf-8")) >= len(before.encode("utf-8")) or not all(
        any(line == prior for prior in iterator)
        for line in after.splitlines(keepends=True)
    ):
        raise ResidualError("candidate must only delete content from one clause")


def validate_candidate_change(
    *,
    base_map_raw: bytes,
    candidate_map_raw: bytes,
    base_source_raw: bytes,
    candidate_source_raw: bytes,
    base_agents_raw: bytes,
    candidate_agents_raw: bytes,
    base_scenarios_raw: bytes,
    candidate_scenarios_raw: bytes,
    classification: str,
    root_cause_ids: list[str],
    current_summary: dict[str, Any],
) -> str:
    base_map, base_sections, base_cases = load_clause_map(
        base_map_raw, base_source_raw, base_scenarios_raw
    )
    candidate_map, _, candidate_cases = load_clause_map(
        candidate_map_raw, candidate_source_raw, candidate_scenarios_raw
    )
    selected = resolve_clause(
        candidate_map if classification == "insufficient_specialization" else base_map,
        root_cause_ids,
        candidate_cases | base_cases,
    )
    base_frontmatter, base_body = _document(_text(base_source_raw, label="base SQW"))
    candidate_frontmatter, candidate_body = _document(
        _text(candidate_source_raw, label="candidate SQW")
    )
    routing = classification in ROUTING_CLASSIFICATIONS
    if _normalized_frontmatter(
        base_frontmatter, routing=routing
    ) != _normalized_frontmatter(candidate_frontmatter, routing=routing):
        raise ResidualError("candidate changes unowned SQW frontmatter")
    if _normalized_agents(base_agents_raw, routing=routing) != _normalized_agents(
        candidate_agents_raw, routing=routing
    ):
        raise ResidualError("candidate changes unowned SQW agent metadata")

    if routing:
        if base_body != candidate_body or base_map != candidate_map:
            raise ResidualError(
                "routing repair cannot add or change SQW runtime clauses"
            )
        if base_frontmatter.get("description") == candidate_frontmatter.get(
            "description"
        ) and _activation(base_agents_raw) == _activation(candidate_agents_raw):
            raise ResidualError("routing repair must change description or activation")
        return selected
    if classification in NATIVE_CLASSIFICATIONS:
        eligible = eligible_native_clause(base_map, base_sections, current_summary)
        if eligible is None:
            raise ResidualError(
                "no residual clause is eligible; retain specialized value"
            )
        candidate_rows = {row["clause_id"]: row for row in candidate_map["clauses"]}
        expected_rows = {
            row["clause_id"]: row
            for row in base_map["clauses"]
            if row["clause_id"] != selected
        }
        if selected != eligible or candidate_rows not in (
            {row["clause_id"]: row for row in base_map["clauses"]},
            expected_rows,
        ):
            raise ResidualError(
                "native absorption must select the canonical eligible clause"
            )
        heading = CLAUSES[selected][0]
        _validate_single_section_change(
            base_body, candidate_body, heading=heading, allow_growth=False
        )
        return selected
    if classification == "skill_interference":
        candidate_rows = {row["clause_id"]: row for row in candidate_map["clauses"]}
        base_rows = {row["clause_id"]: row for row in base_map["clauses"]}
        if candidate_rows not in (
            base_rows,
            {key: value for key, value in base_rows.items() if key != selected},
        ):
            raise ResidualError("interference repair changes an unselected map entry")
        heading = CLAUSES[selected][0]
        _validate_single_section_change(
            base_body, candidate_body, heading=heading, allow_growth=False
        )
        return selected
    if classification == "insufficient_specialization":
        case_roots = set(root_cause_ids) & candidate_cases
        if len(case_roots) != 1:
            raise ResidualError(
                "new guidance requires exactly one named public or regression case"
            )
        base_records = _public_cases(base_scenarios_raw)
        candidate_records = _public_cases(candidate_scenarios_raw)
        if any(
            candidate_records[case_id] != record
            for case_id, record in base_records.items()
        ) or set(candidate_records) - set(base_records) != case_roots - set(
            base_records
        ):
            raise ResidualError(
                "new guidance must preserve existing cases and add only its named case"
            )
        base_rows = {row["clause_id"]: row for row in base_map["clauses"]}
        candidate_rows = {row["clause_id"]: row for row in candidate_map["clauses"]}
        if set(candidate_rows) != set(base_rows):
            raise ResidualError("new guidance must stay within one existing clause")
        for clause_id in base_rows:
            before = base_rows[clause_id]
            after = candidate_rows[clause_id]
            if clause_id != selected and before != after:
                raise ResidualError("new guidance changes more than one clause mapping")
            if clause_id == selected:
                before_static = {
                    key: value for key, value in before.items() if key != "case_ids"
                }
                after_static = {
                    key: value for key, value in after.items() if key != "case_ids"
                }
                added_cases = set(after["case_ids"]) - set(before["case_ids"])
                if (
                    before_static != after_static
                    or not set(before["case_ids"]) <= set(after["case_ids"])
                    or added_cases != case_roots - set(before["case_ids"])
                ):
                    raise ResidualError("new guidance rewrites its clause identity")
        if not base_cases <= candidate_cases:
            raise ResidualError("new guidance removes a registered public case")
        heading = CLAUSES[selected][0]
        _validate_single_section_change(
            base_body, candidate_body, heading=heading, allow_growth=True
        )
        return selected
    raise ResidualError(
        f"transition classification does not authorize a candidate: {classification}"
    )
