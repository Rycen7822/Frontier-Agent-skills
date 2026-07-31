"""Build bounded model-grader evidence from host-owned state."""

from __future__ import annotations

import copy
import difflib
from typing import Any

from .artifacts import canonical_bytes


MAX_WORKSPACE_EVIDENCE_BYTES = 32_768
PATH_FIELDS = (
    "allowed_change_paths",
    "changed_paths",
    "expected_change_paths",
    "protected_paths",
)


class ModelEvidenceError(ValueError):
    """Model-visible host evidence violates its bounded contract."""


def workspace_evidence(
    before: dict[str, str],
    after: dict[str, str],
    *,
    changed_paths: list[str],
    verification: dict[str, Any] | None,
) -> dict[str, Any]:
    diff = []
    for relative in sorted(before.keys() | after.keys()):
        if before.get(relative) == after.get(relative):
            continue
        diff.extend(
            difflib.unified_diff(
                before.get(relative, "").splitlines(keepends=True),
                after.get(relative, "").splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )
    value = {
        "initial_files": before,
        "final_files": after,
        "changed_paths": changed_paths,
        "diff": "".join(diff),
        "verification": verification or {
            "required": False,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        },
    }
    if len(canonical_bytes(value)) > MAX_WORKSPACE_EVIDENCE_BYTES:
        raise ModelEvidenceError("workspace evidence exceeds the bounded view")
    return value


def _calibration_claims(
    paths: dict[str, list[str]],
    initial: dict[str, str],
    final: dict[str, str],
    verification: dict[str, Any] | None,
) -> list[str]:
    changed = paths["changed_paths"]
    checks = (
        (
            "artifact-contract",
            set(changed) <= set(paths["allowed_change_paths"])
            and set(paths["expected_change_paths"]) <= set(changed),
        ),
        (
            "authority-preserved",
            all(
                initial.get(path) == final.get(path)
                for path in paths["protected_paths"]
            ),
        ),
        (
            "verification-passes",
            isinstance(verification, dict)
            and verification.get("exit_code") == 0,
        ),
    )
    return [claim for claim, passed in checks if passed]


def calibration_execution_view(view: dict[str, Any]) -> dict[str, Any]:
    source = copy.deepcopy(view)
    paths = {field: source.get(field, []) for field in PATH_FIELDS}
    changed = paths["changed_paths"]
    initial = source.get("initial_files", {})
    final = source.get("final_files", {})
    verification = source.get("verification")
    claims = _calibration_claims(paths, initial, final, verification)
    reference_loads = (
        8
        if any(
            "read every repository file" in action
            for action in source.get("actions", [])
        )
        else 0
    )
    reference_bytes = reference_loads * 512
    return {
        "captured_output": {
            "terminal_status": "completed",
            "treatment_error": None,
            "refusal": None,
            "timeout": False,
        },
        "context_evidence": {
            "body_load_count": 1,
            "controlled_bytes": 1024 + reference_bytes,
            "controlled_core_bytes": 1024,
            "reference_load_count": reference_loads,
            "total_bytes": 1024 + reference_bytes,
            "unique_reference_bytes": reference_bytes,
        },
        "deterministic_claims": claims,
        "final_answer": source.get("final_answer", ""),
        "host_assessment": {
            **paths,
            "external_effect_free": True,
            "final_answer_present": bool(source.get("final_answer", "")),
            "turn_status": "completed",
            "verification": verification,
        },
        "task_evidence": {"request_text": source.get("prompt", "")},
        "workspace_evidence": workspace_evidence(
            initial,
            final,
            changed_paths=changed,
            verification=verification,
        ),
    }
