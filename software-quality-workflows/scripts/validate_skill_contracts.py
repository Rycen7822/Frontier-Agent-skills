#!/usr/bin/env python3
"""Validate the SQW 9.0 static package and local review evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

import yaml


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
REPO_SCRIPTS = REPO_ROOT / "scripts"
if str(REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(REPO_SCRIPTS))

from evaluate_static_contracts import collect_legacy_contract, markdown_link_errors  # noqa: E402


SKILL_NAME = "software-quality-workflows"
SKILL_VERSION = "9.0.0"
ENTRY_MAX_BYTES = 4096
REQUIRED_HEADINGS = (
    "# Software Quality Workflows",
    "## Scope",
    "## Default execution",
    "## Ask only for material blockers",
    "## Evidence and test retention",
    "## Durable escalation",
    "## Optional specialist references",
    "## Completion truth",
)
EXPECTED_AGENT_METADATA = {
    "interface": {
        "display_name": "Software Quality Workflows",
        "short_description": "Execute and verify software changes with minimal process overhead",
        "default_prompt": "Use $software-quality-workflows to inspect, implement, and verify this software task directly unless a concrete risk requires durable coordination.",
    },
    "policy": {"allow_implicit_invocation": True},
}
VISUAL_OWNER = Path("operator/design-discovery")
VISUAL_RUNTIME_MARKERS = ("frame-template.html", "helper.js", "server.cjs", "start-server.sh", "stop-server.sh")
INDEPENDENT_REVIEWER = Path("templates/requesting-code-review/independent-reviewer-prompt.md")


@dataclass(frozen=True, order=True)
class Violation:
    code: str
    path: str
    line: int
    message: str


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        raise ValueError("missing opening YAML frontmatter delimiter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("missing closing YAML frontmatter delimiter")
    value = yaml.safe_load(text[4:end])
    if not isinstance(value, dict):
        raise ValueError("frontmatter must be a mapping")
    return value


def _check_skill_entry(root: Path, violations: list[Violation]) -> None:
    path = root / "SKILL.md"
    if path.is_symlink() or not path.is_file():
        violations.append(Violation("entry.missing", "SKILL.md", 0, "required regular entrypoint is missing"))
        return
    payload = path.read_bytes()
    if len(payload) > ENTRY_MAX_BYTES:
        violations.append(Violation("entry.size", "SKILL.md", 1, f"entry exceeds {ENTRY_MAX_BYTES} UTF-8 bytes"))
    try:
        text = payload.decode("utf-8")
        metadata = _frontmatter(text)
    except (UnicodeError, ValueError, yaml.YAMLError) as exc:
        violations.append(Violation("entry.frontmatter", "SKILL.md", 1, str(exc)))
        return
    if metadata.get("name") != SKILL_NAME:
        violations.append(Violation("entry.name", "SKILL.md", 1, f"name must be {SKILL_NAME}"))
    nested = metadata.get("metadata")
    version = nested.get("version") if isinstance(nested, dict) else None
    if version != SKILL_VERSION:
        violations.append(Violation("entry.version", "SKILL.md", 1, f"version must be {SKILL_VERSION}"))
    observed = tuple(line for line in text.splitlines() if line.startswith("#"))
    if observed != REQUIRED_HEADINGS:
        violations.append(Violation("entry.headings", "SKILL.md", 1, "entry headings differ from the fixed SQW 9.0 surface"))


def _check_agent_metadata(root: Path, violations: list[Violation]) -> None:
    agents = root / "agents"
    if agents.is_symlink() or not agents.is_dir():
        violations.append(Violation("agent-metadata.missing", "agents", 0, "agents directory is missing or symlinked"))
        return
    entries = sorted(path.name for path in agents.iterdir())
    if entries != ["openai.yaml"]:
        violations.append(Violation("agent-metadata.inventory", "agents", 0, "agents must contain only openai.yaml"))
        return
    path = agents / "openai.yaml"
    if path.is_symlink() or not path.is_file():
        violations.append(Violation("agent-metadata.type", "agents/openai.yaml", 0, "metadata must be a regular file"))
        return
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        violations.append(Violation("agent-metadata.yaml", "agents/openai.yaml", 1, str(exc)))
        return
    if value != EXPECTED_AGENT_METADATA:
        violations.append(Violation("agent-metadata.contract", "agents/openai.yaml", 1, "metadata differs from the fixed implicit SQW profile"))


def _check_markdown(root: Path, violations: list[Violation]) -> None:
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file():
            violations.append(Violation("markdown.type", relative, 0, "Markdown input must be a regular non-symlink file"))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            violations.append(Violation("markdown.read", relative, 0, str(exc)))
            continue
        if relative != "SKILL.md" and text.startswith("---\n"):
            violations.append(Violation("markdown.legacy-frontmatter", relative, 1, "retained references must be normal Markdown, not card JSON frontmatter"))
        if text.count("```") % 2:
            violations.append(Violation("markdown.fence", relative, 1, "unbalanced fenced code block"))

    for error in markdown_link_errors(REPO_ROOT):
        violations.append(Violation("link.invalid", error["path"], error["line"], f"local link is missing, symlinked, or outside the repository: {error['target']}"))


def _check_shared_legacy_contract(violations: list[Violation]) -> None:
    facts = collect_legacy_contract(REPO_ROOT)
    for path in facts["legacy_runtime_paths_present"]:
        violations.append(Violation("legacy.path", path, 0, "legacy runtime path must be absent"))
    for field in ("legacy_protocol_matches", "brainstorming_runtime_copies"):
        for match in facts[field]:
            violations.append(Violation(f"legacy.{field}", match["path"], match["line"], f"forbidden model-facing token: {match['pattern']}"))


def _check_single_owners(root: Path, violations: list[Violation]) -> None:
    provenance = root / VISUAL_OWNER / "SOURCE.md"
    if provenance.is_symlink() or not provenance.is_file():
        violations.append(Violation("owner.visual-provenance", provenance.relative_to(root).as_posix(), 0, "visual runtime provenance is missing or symlinked"))
    for name in VISUAL_RUNTIME_MARKERS:
        expected = root / VISUAL_OWNER / name
        copies = sorted(path for path in root.rglob(name) if path.is_file() or path.is_symlink())
        if copies != [expected] or expected.is_symlink():
            violations.append(Violation("owner.visual-runtime", name, 0, f"expected one runtime owner at {(VISUAL_OWNER / name).as_posix()}"))
    reviewer = root / INDEPENDENT_REVIEWER
    copies = sorted(path for path in root.rglob(INDEPENDENT_REVIEWER.name) if path.is_file() or path.is_symlink())
    if copies != [reviewer] or reviewer.is_symlink():
        violations.append(Violation("owner.independent-reviewer", INDEPENDENT_REVIEWER.as_posix(), 0, "expected exactly one independent reviewer owner"))


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_scope_manifest(data: Any) -> tuple[list[str], dict[str, Any] | None]:
    """Validate and normalize the frozen manifest used to address review inputs."""

    errors: list[str] = []
    if not isinstance(data, dict):
        return ["scope_manifest must be an object"], None
    required = {"base_revision", "head_revision", "scope_hash", "paths"}
    missing = required - data.keys()
    if missing:
        return [f"scope_manifest missing fields: {sorted(missing)}"], None

    for field in ("base_revision", "head_revision", "scope_hash"):
        if not _is_nonempty_string(data[field]):
            errors.append(f"scope_manifest.{field} must be a non-empty string")

    snapshots: dict[str, str] = {}
    if not isinstance(data["paths"], list):
        errors.append("scope_manifest.paths must be a list")
    else:
        statuses = {"added", "modified", "deleted", "renamed", "untracked", "unchanged"}
        seen_paths: list[str] = []
        for index, item in enumerate(data["paths"]):
            prefix = f"scope_manifest.paths[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            item_missing = {"path", "status", "snapshot_id"} - item.keys()
            if item_missing:
                errors.append(f"{prefix} missing {sorted(item_missing)}")
                continue
            path_value = item["path"]
            snapshot_value = item["snapshot_id"]
            if not _is_nonempty_string(path_value):
                errors.append(f"{prefix}.path must be a non-empty string")
            else:
                seen_paths.append(path_value)
            if not isinstance(item["status"], str) or item["status"] not in statuses:
                errors.append(f"{prefix}.status must be one of {sorted(statuses)}")
            if not _is_nonempty_string(snapshot_value):
                errors.append(f"{prefix}.snapshot_id must be a non-empty string")
            if _is_nonempty_string(path_value) and _is_nonempty_string(snapshot_value):
                snapshots.setdefault(path_value, snapshot_value)
        duplicates = sorted(item for item, count in Counter(seen_paths).items() if count > 1)
        if duplicates:
            errors.append(f"duplicate scope_manifest paths: {duplicates}")

    context = {
        "base_revision": data["base_revision"],
        "head_revision": data["head_revision"],
        "scope_hash": data["scope_hash"],
        "snapshots": snapshots,
    }
    return errors, context


def validate_review_result(
    data: Any,
    *,
    scope_manifest: Any = None,
    current_head: str | None = None,
    current_scope_hash: str | None = None,
) -> list[str]:
    """Validate a review envelope and the manifest/revision context needed to trust it."""

    errors: list[str] = []
    if not isinstance(data, dict):
        return ["result must be an object"]

    def validate_enum(field: str, allowed: set[str]) -> None:
        value = data[field]
        if not isinstance(value, str) or value not in allowed:
            errors.append(f"{field} must be one of {sorted(allowed)}")

    required = {
        "schema_version",
        "code_review_verdict",
        "verification_status",
        "spec_traceability",
        "coverage",
        "blocking_reasons",
        "reviewed_base_sha",
        "reviewed_head_sha",
        "reviewed_scope_hash",
        "findings",
    }
    missing = required - data.keys()
    if missing:
        errors.append(f"missing result fields: {sorted(missing)}")
        if data.get("schema_version") in {"1.0", "2.0"}:
            errors.append("pre-3.0 results require re-review against a frozen manifest")
        return errors

    manifest_context: dict[str, Any] | None = None
    if scope_manifest is None:
        errors.append("scope_manifest context is required")
    else:
        manifest_errors, manifest_context = validate_scope_manifest(scope_manifest)
        errors.extend(manifest_errors)

    if current_head is None:
        errors.append("current_head context is required")
    elif not _is_nonempty_string(current_head):
        errors.append("current_head context must be a non-empty string")
    if current_scope_hash is None:
        errors.append("current_scope_hash context is required")
    elif not _is_nonempty_string(current_scope_hash):
        errors.append("current_scope_hash context must be a non-empty string")

    allowed_scope = set(manifest_context["snapshots"]) if manifest_context is not None else None
    unexpected = sorted(data.keys() - (required | {"summary", "positive_notes"}))
    if unexpected:
        errors.append(f"unexpected result fields: {unexpected}")
    if data["schema_version"] != "3.0":
        errors.append("schema_version must be '3.0'; earlier results require re-review")
    validate_enum("code_review_verdict", {"pass", "changes_requested", "inconclusive"})
    validate_enum("verification_status", {"passed", "failed", "partial", "not_run"})

    traceability = data["spec_traceability"]
    if not isinstance(traceability, dict):
        errors.append("spec_traceability must be an object")
    else:
        unexpected_traceability = sorted(traceability.keys() - {"status", "evidence_refs"})
        if unexpected_traceability:
            errors.append(f"unexpected spec_traceability fields: {unexpected_traceability}")
        status = traceability.get("status")
        allowed_traceability = {"complete", "partial", "not_assessed", "not_applicable"}
        if not isinstance(status, str) or status not in allowed_traceability:
            errors.append(f"spec_traceability.status must be one of {sorted(allowed_traceability)}")
        evidence_refs = traceability.get("evidence_refs")
        if not isinstance(evidence_refs, list):
            errors.append("spec_traceability.evidence_refs must be a list")
        else:
            for index, ref in enumerate(evidence_refs):
                if not _is_nonempty_string(ref):
                    errors.append(f"spec_traceability.evidence_refs[{index}] must be a non-empty string")
            if status in {"complete", "partial"} and not evidence_refs:
                errors.append(f"spec_traceability.status={status} requires evidence_refs")

    for field in ("reviewed_base_sha", "reviewed_head_sha", "reviewed_scope_hash"):
        if not _is_nonempty_string(data[field]):
            errors.append(f"{field} must be a non-empty string")
    if data["reviewed_head_sha"] == "not_applicable":
        errors.append("reviewed_head_sha must identify the reviewed snapshot")

    if manifest_context is not None:
        if data["reviewed_base_sha"] != manifest_context["base_revision"]:
            errors.append("reviewed_base_sha does not match the frozen scope manifest")
        if data["reviewed_head_sha"] != manifest_context["head_revision"]:
            errors.append("reviewed_head_sha does not match the frozen scope manifest")
        if data["reviewed_scope_hash"] != manifest_context["scope_hash"]:
            errors.append("reviewed_scope_hash does not match the frozen scope manifest")
        if _is_nonempty_string(current_head) and current_head != manifest_context["head_revision"]:
            errors.append("current head differs from the frozen scope manifest")
        if _is_nonempty_string(current_scope_hash) and current_scope_hash != manifest_context["scope_hash"]:
            errors.append("current scope hash differs from the frozen scope manifest")

    coverage = data["coverage"] if isinstance(data["coverage"], list) else []
    if not isinstance(data["coverage"], list):
        errors.append("coverage must be a list")
    coverage_statuses: list[str] = []
    coverage_paths: list[str] = []
    for index, item in enumerate(coverage):
        if not isinstance(item, dict):
            errors.append(f"coverage[{index}] must be an object")
            continue
        if not {"path", "status", "snapshot_id"} <= item.keys():
            errors.append(f"coverage[{index}] requires path, status, and snapshot_id")
            continue
        unexpected_coverage = sorted(item.keys() - {"path", "status", "snapshot_id", "sampling_note"})
        if unexpected_coverage:
            errors.append(f"coverage[{index}] has unexpected fields: {unexpected_coverage}")
        path_value = item["path"]
        if not _is_nonempty_string(path_value):
            errors.append(f"coverage[{index}].path must be a non-empty string")
        else:
            coverage_paths.append(path_value)
            if allowed_scope is not None and path_value not in allowed_scope:
                errors.append(f"coverage[{index}].path is outside the scope allowlist")
        snapshot_value = item["snapshot_id"]
        if not _is_nonempty_string(snapshot_value):
            errors.append(f"coverage[{index}].snapshot_id must be a non-empty string")
        elif manifest_context is not None and _is_nonempty_string(path_value):
            expected_snapshot = manifest_context["snapshots"].get(path_value)
            if expected_snapshot is not None and snapshot_value != expected_snapshot:
                errors.append(f"coverage[{index}].snapshot_id does not match the frozen scope manifest")
        status_value = item["status"]
        allowed_coverage = {"full", "sampled", "not_reviewed"}
        if not isinstance(status_value, str) or status_value not in allowed_coverage:
            errors.append(f"coverage[{index}].status must be one of {sorted(allowed_coverage)}")
        else:
            coverage_statuses.append(status_value)
            if status_value == "sampled" and not _is_nonempty_string(item.get("sampling_note")):
                errors.append(f"coverage[{index}].sampling_note is required for sampled coverage")

    duplicate_coverage = sorted(item for item, count in Counter(coverage_paths).items() if count > 1)
    if duplicate_coverage:
        errors.append(f"duplicate coverage paths: {duplicate_coverage}")
    if allowed_scope is not None:
        missing_coverage = sorted(allowed_scope - set(coverage_paths))
        if missing_coverage:
            errors.append(f"coverage is missing allowlisted paths: {missing_coverage}")

    blocking_reasons: list[str] = []
    if not isinstance(data["blocking_reasons"], list):
        errors.append("blocking_reasons must be a list")
    else:
        for index, reason in enumerate(data["blocking_reasons"]):
            if not _is_nonempty_string(reason):
                errors.append(f"blocking_reasons[{index}] must be a non-empty string")
            else:
                blocking_reasons.append(reason)
        duplicates = sorted(item for item, count in Counter(blocking_reasons).items() if count > 1)
        if duplicates:
            errors.append(f"duplicate blocking_reasons: {duplicates}")

    findings = data["findings"] if isinstance(data["findings"], list) else []
    if not isinstance(data["findings"], list):
        errors.append("findings must be a list")
    finding_required = {
        "id", "severity", "blocking", "category", "path", "line", "evidence", "impact",
        "recommended_fix", "confidence", "verification", "code_fixable", "source_revision",
    }
    ids: list[str] = []
    blocking_ids: list[str] = []
    for index, finding in enumerate(findings):
        prefix = f"findings[{index}]"
        if not isinstance(finding, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing_finding = finding_required - finding.keys()
        if missing_finding:
            errors.append(f"{prefix} missing {sorted(missing_finding)}")
            continue
        for field in ("id", "category", "path", "evidence", "impact", "recommended_fix", "verification", "source_revision"):
            if not _is_nonempty_string(finding[field]):
                errors.append(f"{prefix}.{field} must be a non-empty string")
        if _is_nonempty_string(finding["id"]):
            ids.append(finding["id"])
        if _is_nonempty_string(finding["category"]) and not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", finding["category"]):
            errors.append(f"{prefix}.category must be lower_snake_case")
        allowed_severity = {"critical", "high", "medium", "low", "info"}
        if not isinstance(finding["severity"], str) or finding["severity"] not in allowed_severity:
            errors.append(f"{prefix}.severity must be one of {sorted(allowed_severity)}")
        if not isinstance(finding["blocking"], bool):
            errors.append(f"{prefix}.blocking must be boolean")
        elif finding["blocking"] and _is_nonempty_string(finding["id"]):
            blocking_ids.append(finding["id"])
        if not isinstance(finding["code_fixable"], bool):
            errors.append(f"{prefix}.code_fixable must be boolean")
        allowed_confidence = {"high", "medium", "low"}
        if not isinstance(finding["confidence"], str) or finding["confidence"] not in allowed_confidence:
            errors.append(f"{prefix}.confidence must be one of {sorted(allowed_confidence)}")
        line_value = finding["line"]
        if line_value is not None and (type(line_value) is not int or line_value < 1):
            errors.append(f"{prefix}.line must be null or a positive integer")
        if _is_nonempty_string(finding["source_revision"]) and finding["source_revision"] != data["reviewed_head_sha"]:
            errors.append(f"{prefix}.source_revision does not match reviewed_head_sha")
        if allowed_scope is not None and _is_nonempty_string(finding["path"]) and finding["path"] not in allowed_scope:
            errors.append(f"{prefix}.path is outside the scope allowlist")

    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate finding ids: {duplicates}")
    for finding_id in blocking_ids:
        if finding_id not in blocking_reasons:
            errors.append(f"blocking finding {finding_id!r} is missing from blocking_reasons")
    if blocking_ids and data["code_review_verdict"] == "pass":
        errors.append("blocking finding conflicts with code_review_verdict=pass")
    if blocking_reasons and data["code_review_verdict"] == "pass":
        errors.append("blocking_reasons conflict with code_review_verdict=pass")
    if "not_reviewed" in coverage_statuses and data["code_review_verdict"] == "pass":
        errors.append("not_reviewed coverage conflicts with code_review_verdict=pass")
    if manifest_context is not None and _is_nonempty_string(current_head) and current_head != manifest_context["head_revision"]:
        errors.append("review result is stale for the current head revision")
    return errors


def validate_skill(root: Path) -> list[Violation]:
    root = root.resolve(strict=True)
    violations: list[Violation] = []
    _check_skill_entry(root, violations)
    _check_agent_metadata(root, violations)
    _check_markdown(root, violations)
    _check_shared_legacy_contract(violations)
    _check_single_owners(root, violations)
    return sorted(set(violations))


def compact_violations(violations: Sequence[Violation], *, per_code: int = 4) -> str:
    grouped: dict[str, list[Violation]] = defaultdict(list)
    for violation in violations:
        grouped[violation.code].append(violation)
    lines = [f"FAIL: {len(violations)} contract violation(s) across {len(grouped)} check(s)"]
    for code in sorted(grouped):
        items = grouped[code]
        lines.append(f"[{code}] {len(items)}")
        for item in items[:per_code]:
            location = f"{item.path}:{item.line}" if item.line else item.path
            lines.append(f"  {location} - {item.message}")
        if len(items) > per_code:
            lines.append(f"  ... {len(items) - per_code} more")
    return "\n".join(lines)


def _load_json(path: Path) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    if path.is_symlink() or not path.is_file():
        raise ValueError("input must be a regular non-symlink file")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates, parse_constant=reject_constant)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=ROOT)
    parser.add_argument("--review-result", type=Path)
    parser.add_argument("--scope-manifest", type=Path)
    parser.add_argument("--current-head")
    parser.add_argument("--current-scope-hash")
    args = parser.parse_args(argv)
    if args.review_result:
        try:
            data = _load_json(args.review_result)
            scope_manifest = _load_json(args.scope_manifest) if args.scope_manifest is not None else None
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            print(f"FAIL: unable to read review evidence: {exc}")
            return 1
        errors = validate_review_result(
            data,
            scope_manifest=scope_manifest,
            current_head=args.current_head,
            current_scope_hash=args.current_scope_hash,
        )
        if errors:
            print(f"FAIL: {len(errors)} review-result contract violation(s)")
            for error in errors[:12]:
                print(f"  {error}")
            if len(errors) > 12:
                print(f"  ... {len(errors) - 12} more")
            return 1
        print("OK: local review result satisfies schema 3.0")
        return 0
    try:
        violations = validate_skill(args.root)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"FAIL: unable to inspect skill contracts: {exc}")
        return 1
    if violations:
        print(compact_violations(violations))
        return 1
    print("OK: software-quality-workflows contracts satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
