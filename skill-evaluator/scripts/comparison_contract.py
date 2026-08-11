"""Load comparison capsules and commit deterministic comparison artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any

from evidence_io import (
    atomic_write_directory,
    canonical_json_bytes,
    file_sha256,
    load_json,
    normalize_relative_path,
    resolve_contained_path,
)
from validate_eval_suite import (
    load_epoch6_schema_registry,
    validate_epoch6_schema,
)


ROLE_ORDER = {
    "prior": 0,
    "candidate": 1,
    "A": 2,
    "B": 3,
    "C": 4,
}
ARTIFACT_CONTRACTS = {
    "spec": ("eval-spec-v6", "eval-spec-v6.schema.json"),
    "execution_plan": ("execution-plan-v2", "execution-plan-v2.schema.json"),
    "host_manifest": ("host-manifest-v2", "host-manifest-v2.schema.json"),
    "summary": ("analysis-summary-v5", "analysis-summary-v5.schema.json"),
    "failure_index": ("failure-index-v2", "failure-index-v2.schema.json"),
    "observations": (
        "comparison-observations-v2", "comparison-observations-v2.schema.json",
    ),
}


class ContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CycleCapsule:
    role: str
    cycle_id: str
    capsule_digest: str
    spec: dict[str, Any]
    execution_plan: dict[str, Any]
    host_manifest: dict[str, Any]
    summary: dict[str, Any]
    failure_index: dict[str, Any] | None
    observations: dict[str, Any] | None
    paths: dict[str, Path | None]
    source_refs: dict[str, str | None]
    artifact_digests: dict[str, str | None]

    def report_record(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "cycle_id": self.cycle_id,
            "evaluation_id": self.summary["evaluation_id"],
            "plan_id": self.execution_plan["plan_id"],
            "capsule_digest": self.capsule_digest,
            "execution_profile": self.execution_plan["execution_profile"],
        }


def _bounded(value: Any, limit: int = 240) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _raise(code: str, message: str) -> None:
    raise ContractError(code, _bounded(message))


def _schema_error(
    label: str,
    diagnostics: list[dict[str, str]],
) -> None:
    first = diagnostics[0]
    _raise(
        "contract.schema",
        f"{label}: {first['code']} at {first['path'] or '/'}",
    )


def _reject_symlink_components(root: Path, relative: str, label: str) -> None:
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor /= part
        if cursor.is_symlink():
            _raise("contract.symlink", f"{label} uses a symlink component")


def load_comparison_plan(
    plan_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, dict[str, Any]]]:
    if plan_path.is_symlink() or not plan_path.is_file():
        _raise("plan.file", "comparison plan must be a regular non-symlink file")
    resolved = plan_path.resolve()
    try:
        plan = load_json(resolved)
        registry = load_epoch6_schema_registry()
    except (OSError, ValueError, TypeError) as exc:
        _raise("plan.load", exc)
    diagnostics = validate_epoch6_schema(
        plan,
        "comparison-plan-v2.schema.json",
        registry,
    )
    if diagnostics:
        _schema_error("comparison plan", diagnostics)
    return resolved, plan, registry


def _load_artifact(
    root: Path,
    binding: dict[str, Any],
    artifact: str,
    role: str,
    registry: dict[str, dict[str, Any]],
) -> tuple[Path, dict[str, Any], str]:
    declared_schema, schema_name = ARTIFACT_CONTRACTS[artifact]
    if binding["schema"] != declared_schema:
        _raise(
            "input.schema_binding",
            f"{role}.{artifact} declares the wrong schema",
        )
    label = f"{role}.{artifact}"
    try:
        relative = normalize_relative_path(binding["path"], label)
        _reject_symlink_components(root, relative, label)
        _, path = resolve_contained_path(
            root,
            relative,
            label,
            kind="file",
        )
        document = load_json(path)
    except ContractError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        _raise("input.path", f"{label}: {exc}")
    diagnostics = validate_epoch6_schema(document, schema_name, registry)
    if diagnostics:
        _schema_error(label, diagnostics)
    actual_digest = file_sha256(path)
    if actual_digest != binding["digest"]:
        _raise("input.digest", f"{label} digest differs from its binding")
    return path, document, actual_digest


def _expect_equal(actual: Any, expected: Any, label: str) -> None:
    if canonical_json_bytes(actual) != canonical_json_bytes(expected):
        _raise("input.identity", f"{label} differs")


def _load_cycle(
    root: Path,
    role: str,
    binding: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> CycleCapsule:
    capsule_binding = binding["capsule"]
    if capsule_binding["schema"] != "comparison-cycle-capsule/2":
        _raise("input.schema_binding", f"{role}.capsule schema is invalid")
    try:
        capsule_relative = normalize_relative_path(
            capsule_binding["path"], f"{role}.capsule",
        )
        _reject_symlink_components(root, capsule_relative, f"{role}.capsule")
        _, capsule_path = resolve_contained_path(
            root, capsule_relative, f"{role}.capsule", kind="file",
        )
        if file_sha256(capsule_path) != capsule_binding["digest"]:
            _raise("input.digest", f"{role}.capsule digest differs")
        capsule = load_json(capsule_path)
    except ContractError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        _raise("input.path", f"{role}.capsule: {exc}")
    diagnostics = validate_epoch6_schema(
        capsule, "comparison-cycle-capsule-v2.schema.json", registry,
    )
    if diagnostics:
        _schema_error(f"{role}.capsule", diagnostics)

    expected = binding["expected_identity"]
    _expect_equal(capsule["cycle_id"], binding["cycle_id"], f"{role}.cycle ID")
    _expect_equal(
        {
            "evaluation_id": capsule["evaluation_id"],
            "plan_id": capsule["plan_id"],
            "execution_profile": capsule["execution_profile"],
        },
        expected,
        f"{role}.expected identity",
    )

    documents: dict[str, dict[str, Any] | None] = {}
    paths: dict[str, Path | None] = {}
    source_refs: dict[str, str | None] = {}
    artifact_digests: dict[str, str | None] = {}
    for artifact in ARTIFACT_CONTRACTS:
        artifact_binding = capsule["artifacts"][artifact]
        if artifact_binding is None:
            documents[artifact] = None
            paths[artifact] = None
            source_refs[artifact] = None
            artifact_digests[artifact] = None
            continue
        path, document, actual_digest = _load_artifact(
            capsule_path.parent,
            artifact_binding,
            artifact,
            role,
            registry,
        )
        documents[artifact] = document
        paths[artifact] = path
        source_refs[artifact] = path.relative_to(root).as_posix()
        artifact_digests[artifact] = actual_digest

    spec = documents["spec"]
    plan = documents["execution_plan"]
    host = documents["host_manifest"]
    summary = documents["summary"]
    if not all(isinstance(item, dict) for item in (spec, plan, host, summary)):
        _raise("input.required", f"{role} lacks a required cycle artifact")
    assert isinstance(spec, dict)
    assert isinstance(plan, dict)
    assert isinstance(host, dict)
    assert isinstance(summary, dict)
    failure_index = documents["failure_index"]
    observations = documents["observations"]
    _expect_equal(
        plan["execution_profile"],
        capsule["execution_profile"],
        f"{role}.execution profile",
    )
    _expect_equal(plan["evaluation_id"], spec["evaluation_id"], f"{role}.plan evaluation")
    _expect_equal(plan["plan_id"], capsule["plan_id"], f"{role}.capsule plan")
    _expect_equal(
        plan["source_revision"],
        spec["subject"]["package"]["source_revision"],
        f"{role}.source revision",
    )
    _expect_equal(
        plan["subject_shape"],
        spec["subject"]["shape"],
        f"{role}.subject shape",
    )
    _expect_equal(
        summary["evaluation_id"],
        spec["evaluation_id"],
        f"{role}.summary evaluation",
    )
    _expect_equal(summary["plan_id"], plan["plan_id"], f"{role}.summary plan")
    expected_subject = {
        "skill_id": spec["subject"]["skill_id"],
        "version": spec["subject"]["version"],
        "shape": spec["subject"]["shape"],
        "source_revision": plan["source_revision"],
    }
    _expect_equal(summary["subject"], expected_subject, f"{role}.summary subject")

    if failure_index is not None:
        assert isinstance(failure_index, dict)
        _expect_equal(
            failure_index["evaluation_id"],
            spec["evaluation_id"],
            f"{role}.failure evaluation",
        )
        _expect_equal(
            failure_index["plan_id"],
            plan["plan_id"],
            f"{role}.failure plan",
        )
        if failure_index["view"] != "index":
            _raise("input.failure_view", f"{role}.failure_index must use index view")
        failure_view = summary["output_manifest"]["failure_index"]
        failure_path = paths["failure_index"]
        summary_path = paths["summary"]
        assert failure_path is not None and summary_path is not None
        expected_failure_view = {
            "path": failure_path.relative_to(summary_path.parent).as_posix(),
            "schema_or_view_version": "failure-index-v2/index",
            "item_count": failure_index["item_count"],
            "shown_count": failure_index["shown_count"],
            "omitted_count": failure_index["omitted_count"],
            "truncated": failure_index["truncated"],
            "family_counts": failure_index["family_counts"],
            "severity_counts": failure_index["severity_counts"],
        }
        _expect_equal(
            failure_view,
            expected_failure_view,
            f"{role}.summary failure index",
        )
    if observations is not None:
        assert isinstance(observations, dict)
        for field, expected_value in (
            ("cycle_id", capsule["cycle_id"]),
            ("evaluation_id", spec["evaluation_id"]),
            ("plan_id", plan["plan_id"]),
            ("subject", expected_subject),
        ):
            _expect_equal(
                observations[field],
                expected_value,
                f"{role}.observations {field}",
            )

    return CycleCapsule(
        role=role,
        cycle_id=capsule["cycle_id"],
        capsule_digest=capsule_binding["digest"],
        spec=spec,
        execution_plan=plan,
        host_manifest=host,
        summary=summary,
        failure_index=failure_index,
        observations=observations,
        paths=paths,
        source_refs=source_refs,
        artifact_digests=artifact_digests,
    )


def load_cycle_capsules(
    plan_path: Path,
    plan: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, CycleCapsule]:
    root = plan_path.parent
    bindings = plan["input_bindings"]
    roles = sorted(bindings, key=ROLE_ORDER.__getitem__)
    return {
        role: _load_cycle(root, role, bindings[role], registry)
        for role in roles
    }


def make_diagnostic(
    *,
    severity: str,
    fact_type: str,
    reason_key: str,
    roles: list[str],
    expected: Any,
    observed: Any,
    locator_artifact: str,
    json_pointer: str,
    source_ref: str,
    case_ids: list[str] | None = None,
    requirement_ids: list[str] | None = None,
    metric_ids: list[str] | None = None,
) -> dict[str, Any]:
    purpose = expected.get("purpose") if isinstance(expected, dict) else None
    projection = {
        "severity": severity,
        "fact_type": fact_type,
        "reason_key": reason_key,
        "roles": sorted(set(roles), key=ROLE_ORDER.__getitem__),
        "case_ids": sorted(set(case_ids or [])),
        "requirement_ids": sorted(set(requirement_ids or [])),
        "metric_ids": sorted(set(metric_ids or [])),
        "expected": _bounded(expected),
        "observed": _bounded(observed),
        "locator": {
            "kind": "json_pointer",
            "artifact": normalize_relative_path(
                locator_artifact,
                "diagnostic artifact",
            ),
            "json_pointer": json_pointer,
        },
        "source_ref": normalize_relative_path(source_ref, "diagnostic source"),
    }
    identity_parts = [reason_key, *projection["roles"]]
    if purpose:
        identity_parts.append(str(purpose))
    identity_parts.extend(projection["metric_ids"][:1])
    identity_parts.extend(projection["requirement_ids"][:1])
    identity_parts.extend([
        Path(locator_artifact).stem,
        json_pointer.strip("/").replace("/", ".") or "root",
    ])
    identity = ".".join(
        re.sub(r"[^A-Za-z0-9._-]+", "-", part).strip("-.") or "item"
        for part in identity_parts
    )
    return {"diagnostic_id": f"diagnostic.{identity}"[:128], **projection}


def _output_root(plan_path: Path, plan: dict[str, Any]) -> Path:
    root = plan_path.parent
    relative = normalize_relative_path(plan["output"]["root"], "output root")
    _reject_symlink_components(root, relative, "output root")
    _, output_root = resolve_contained_path(root, relative, "output root")
    if output_root.exists() or output_root.is_symlink():
        _raise("output.exists", "comparison output root already exists")
    if not output_root.parent.is_dir() or output_root.parent.is_symlink():
        _raise("output.parent", "comparison output parent is not a regular directory")
    return output_root


def commit_outputs(
    plan_path: Path,
    plan: dict[str, Any],
    report: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
) -> tuple[Path, Path]:
    for field in ("comparison_id", "kind", "claim_scope"):
        _expect_equal(
            report[field],
            plan[field],
            f"report {field}",
        )
    ordered_diagnostics = sorted(
        diagnostics,
        key=lambda item: item["diagnostic_id"],
    )
    diagnostic_ids = [item["diagnostic_id"] for item in ordered_diagnostics]
    if len(diagnostic_ids) != len(set(diagnostic_ids)):
        _raise("output.diagnostic_id", "comparison diagnostic IDs must be unique")
    diagnostic_index = {
        "schema_version": 2,
        "comparison_id": plan["comparison_id"],
        "item_count": len(ordered_diagnostics),
        "diagnostics": ordered_diagnostics,
    }
    report["diagnostic_index_path"] = plan["output"]["diagnostic_index"]
    for value, schema_name, label in (
        (
            diagnostic_index,
            "comparison-diagnostic-index-v2.schema.json",
            "comparison diagnostic index",
        ),
        (report, "comparison-report-v2.schema.json", "comparison report"),
    ):
        schema_diagnostics = validate_epoch6_schema(
            value,
            schema_name,
            registry,
        )
        if schema_diagnostics:
            _schema_error(label, schema_diagnostics)

    output_root = _output_root(plan_path, plan)
    report_name = plan["output"]["report"]
    index_name = plan["output"]["diagnostic_index"]
    atomic_write_directory(
        output_root,
        {
            report_name: canonical_json_bytes(report),
            index_name: canonical_json_bytes(diagnostic_index),
        },
    )
    return output_root / report_name, output_root / index_name
