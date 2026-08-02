"""Load comparison capsules and commit deterministic comparison artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from evidence_io import (
    atomic_write_directory,
    canonical_json_bytes,
    canonical_self_hash,
    file_sha256,
    load_json,
    normalize_relative_path,
    resolve_contained_path,
    verify_self_hash,
)
from validate_eval_suite import (
    load_v5_schema_registry,
    validate_v5_schema,
)


ROLE_ORDER = {
    "prior": 0,
    "candidate": 1,
    "A": 2,
    "B": 3,
    "C": 4,
}
ARTIFACT_CONTRACTS = {
    "spec": ("eval-spec-v5", "eval-spec-v5.schema.json", None),
    "execution_plan": (
        "execution-plan-v1",
        "execution-plan-v1.schema.json",
        "plan_hash",
    ),
    "host_manifest": (
        "host-manifest-v1",
        "host-manifest-v1.schema.json",
        "manifest_hash",
    ),
    "summary": (
        "analysis-summary-v4",
        "analysis-summary-v4.schema.json",
        "summary_hash",
    ),
    "failure_index": (
        "failure-index-v1",
        "failure-index-v1.schema.json",
        "failure_index_hash",
    ),
    "observations": (
        "comparison-observations-v1",
        "comparison-observations-v1.schema.json",
        "comparison_observations_hash",
    ),
}


class ContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CycleCapsule:
    role: str
    spec: dict[str, Any]
    execution_plan: dict[str, Any]
    host_manifest: dict[str, Any]
    summary: dict[str, Any]
    failure_index: dict[str, Any] | None
    observations: dict[str, Any] | None
    paths: dict[str, Path | None]
    file_hashes: dict[str, str | None]

    def report_record(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "evaluation_id": self.summary["evaluation_id"],
            "plan_id": self.execution_plan["plan_id"],
            "spec_hash": self.execution_plan["spec_hash"],
            "plan_hash": self.execution_plan["plan_hash"],
            "host_manifest_hash": self.host_manifest["manifest_hash"],
            "summary_hash": self.summary["summary_hash"],
            "failure_index_hash": (
                self.failure_index["failure_index_hash"]
                if self.failure_index is not None
                else None
            ),
            "observations_hash": (
                self.observations["comparison_observations_hash"]
                if self.observations is not None
                else None
            ),
            "execution_identity": self.execution_plan["execution_identity"],
            "file_hashes": self.file_hashes,
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
        registry = load_v5_schema_registry()
    except (OSError, ValueError, TypeError) as exc:
        _raise("plan.load", exc)
    diagnostics = validate_v5_schema(
        plan,
        "comparison-plan-v1.schema.json",
        registry,
    )
    if diagnostics:
        _schema_error("comparison plan", diagnostics)
    if not verify_self_hash(plan, "comparison_plan_hash"):
        _raise("plan.hash", "comparison plan self-hash is invalid")
    return resolved, plan, registry


def _load_artifact(
    root: Path,
    binding: dict[str, Any],
    artifact: str,
    role: str,
    registry: dict[str, dict[str, Any]],
) -> tuple[Path, dict[str, Any], str]:
    declared_schema, schema_name, self_hash_field = ARTIFACT_CONTRACTS[
        artifact
    ]
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
    diagnostics = validate_v5_schema(document, schema_name, registry)
    if diagnostics:
        _schema_error(label, diagnostics)
    if (
        self_hash_field is not None
        and not verify_self_hash(document, self_hash_field)
    ):
        _raise("input.self_hash", f"{label} self-hash is invalid")
    actual_file_hash = file_sha256(path)
    expected_file_hash = binding.get("file_sha256")
    if (
        expected_file_hash is not None
        and actual_file_hash != expected_file_hash
    ):
        _raise("input.file_hash", f"{label} file hash differs from its binding")
    return path, document, actual_file_hash


def _expect_equal(actual: Any, expected: Any, label: str) -> None:
    if canonical_json_bytes(actual) != canonical_json_bytes(expected):
        _raise("input.identity", f"{label} differs")


def _load_cycle(
    root: Path,
    role: str,
    binding: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> CycleCapsule:
    documents: dict[str, dict[str, Any] | None] = {}
    paths: dict[str, Path | None] = {}
    file_hashes: dict[str, str | None] = {}
    for artifact in ARTIFACT_CONTRACTS:
        artifact_binding = binding[artifact]
        if artifact_binding is None:
            documents[artifact] = None
            paths[artifact] = None
            file_hashes[artifact] = None
            continue
        path, document, actual_file_hash = _load_artifact(
            root,
            artifact_binding,
            artifact,
            role,
            registry,
        )
        documents[artifact] = document
        paths[artifact] = path
        file_hashes[artifact] = actual_file_hash

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
    expected = binding["expected_identity"]

    cross_references = {
        "evaluation_id": spec["evaluation_id"],
        "plan_id": plan["plan_id"],
        "spec_hash": plan["spec_hash"],
        "scenario_corpus_hash": plan["scenario_corpus_hash"],
        "host_manifest_hash": host["manifest_hash"],
        "execution_identity": plan["execution_identity"],
    }
    _expect_equal(cross_references, expected, f"{role}.expected_identity")
    _expect_equal(plan["evaluation_id"], spec["evaluation_id"], f"{role}.plan evaluation")
    _expect_equal(
        plan["host_manifest_hash"],
        host["manifest_hash"],
        f"{role}.plan host",
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
    _expect_equal(summary["plan_hash"], plan["plan_hash"], f"{role}.summary plan hash")
    _expect_equal(summary["spec_hash"], plan["spec_hash"], f"{role}.summary spec")
    _expect_equal(
        summary["scenario_corpus_hash"],
        plan["scenario_corpus_hash"],
        f"{role}.summary scenarios",
    )
    _expect_equal(
        summary["host_manifest_hash"],
        host["manifest_hash"],
        f"{role}.summary host",
    )
    expected_subject = {
        "skill_id": spec["subject"]["skill_id"],
        "version": spec["subject"]["version"],
        "shape": spec["subject"]["shape"],
        "package_hash": plan["package_hashes"][spec["subject"]["skill_id"]],
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
    if observations is not None:
        assert isinstance(observations, dict)
        for field, expected_value in (
            ("evaluation_id", spec["evaluation_id"]),
            ("plan_id", plan["plan_id"]),
            ("plan_hash", plan["plan_hash"]),
            ("spec_hash", plan["spec_hash"]),
            ("scenario_corpus_hash", plan["scenario_corpus_hash"]),
            ("host_manifest_hash", host["manifest_hash"]),
            ("subject", expected_subject),
        ):
            _expect_equal(
                observations[field],
                expected_value,
                f"{role}.observations {field}",
            )

    return CycleCapsule(
        role=role,
        spec=spec,
        execution_plan=plan,
        host_manifest=host,
        summary=summary,
        failure_index=failure_index,
        observations=observations,
        paths=paths,
        file_hashes=file_hashes,
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
    source_hash: str,
    case_ids: list[str] | None = None,
    requirement_ids: list[str] | None = None,
    metric_ids: list[str] | None = None,
) -> dict[str, Any]:
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
        "source_hash": source_hash,
    }
    digest = sha256(canonical_json_bytes(projection)).hexdigest()[:24]
    return {"diagnostic_id": f"cd-{digest}", **projection}


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
    for field in ("comparison_id", "comparison_plan_hash", "kind", "claim_scope"):
        _expect_equal(
            report[field],
            plan[field],
            f"report {field}",
        )
    ordered_diagnostics = sorted(
        diagnostics,
        key=lambda item: item["diagnostic_id"],
    )
    diagnostic_index = {
        "schema_version": 1,
        "comparison_diagnostic_index_hash": "sha256:" + "0" * 64,
        "comparison_id": plan["comparison_id"],
        "comparison_plan_hash": plan["comparison_plan_hash"],
        "item_count": len(ordered_diagnostics),
        "diagnostics": ordered_diagnostics,
    }
    diagnostic_index["comparison_diagnostic_index_hash"] = canonical_self_hash(
        diagnostic_index,
        "comparison_diagnostic_index_hash",
    )
    report["diagnostic_index_hash"] = diagnostic_index[
        "comparison_diagnostic_index_hash"
    ]
    report["comparison_report_hash"] = canonical_self_hash(
        report,
        "comparison_report_hash",
    )
    for value, schema_name, label in (
        (
            diagnostic_index,
            "comparison-diagnostic-index-v1.schema.json",
            "comparison diagnostic index",
        ),
        (report, "comparison-report-v1.schema.json", "comparison report"),
    ):
        schema_diagnostics = validate_v5_schema(
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
