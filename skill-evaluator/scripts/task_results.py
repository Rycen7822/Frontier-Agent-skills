"""Immutable task/grade files and small, source-checked maintenance views."""

from __future__ import annotations

import copy
from pathlib import Path

from evidence_io import (
    atomic_write_json,
    file_sha256,
    load_json,
    resolve_contained_path,
)

TASK_VERSION = "skill-evaluator-task/1"
GRADE_VERSION = "skill-evaluator-grade/1"
REPORT_VERSION = "maintenance-report/2"


def reference(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"source must be a regular file: {path}")
    return {"path": str(path.resolve()), "digest": file_sha256(path)}


def read_reference(ref):
    if not isinstance(ref, dict) or set(ref) != {"path", "digest"}:
        raise ValueError("invalid source reference")
    path = Path(ref["path"])
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or file_sha256(path) != ref["digest"]
    ):
        raise ValueError(f"source digest mismatch or unavailable: {path}")
    return load_json(path), path.parent


def artifacts(root, bindings):
    result = {}
    if not isinstance(bindings, list):
        raise ValueError("artifact list is missing")
    for item in bindings:
        name, path = resolve_contained_path(
            root, item["path"], "task artifact", kind="file"
        )
        if name in result or file_sha256(path) != item["digest"]:
            raise ValueError(f"duplicate or damaged artifact: {name}")
        result[name] = path
    return result


def position(entry):
    return (entry["case_id"], entry["treatment_id"], entry["repeat"])


def write_task(path, *, entry, key, result, bindings, usage):
    value = {
        "schema_version": TASK_VERSION,
        "position": list(position(entry)),
        "entry": entry,
        "key": key,
        "result": result,
        "artifacts": bindings,
        "usage": usage,
    }
    atomic_write_json(path, value)
    return read_task(reference(path))


def read_task(ref):
    task, root = read_reference(ref)
    if task.get("schema_version") != TASK_VERSION or tuple(
        task.get("position", [])
    ) != position(task["entry"]):
        raise ValueError("task position or format is invalid")
    paths = artifacts(root, task["artifacts"])
    result_ref = task["result"]
    if (
        result_ref["path"] not in paths
        or file_sha256(paths[result_ref["path"]]) != result_ref["digest"]
    ):
        raise ValueError("task result is not bound by its artifacts")
    result = load_json(paths[result_ref["path"]])
    if result.get("envelope", {}).get("entry_id") != task["entry"]["entry_id"]:
        raise ValueError("task result entry differs from its source")
    for binding in result.get("artifacts", []):
        if (
            binding["path"] not in paths
            or file_sha256(paths[binding["path"]]) != binding["digest"]
        ):
            raise ValueError("Host observation is missing or damaged")
    return {"task": task, "source": ref, "result": result, "paths": paths, "grades": {}}


def write_grade(path, *, grader_id, key, outputs, task_refs, bindings, usage):
    value = {
        "schema_version": GRADE_VERSION,
        "grader_id": grader_id,
        "key": key,
        "outputs": outputs,
        "tasks": task_refs,
        "artifacts": bindings,
        "usage": usage,
    }
    atomic_write_json(path, value)
    return reference(path)


def read_grade(ref, task_ref, *, grader_id, key, expected_checks):
    grade, root = read_reference(ref)
    if (
        grade.get("schema_version") != GRADE_VERSION
        or grade.get("grader_id") != grader_id
        or grade.get("key") != key
    ):
        raise ValueError("grade identity differs from its source")
    if task_ref not in grade.get("tasks", []):
        raise ValueError("grade does not bind this task")
    artifacts(root, grade["artifacts"])
    checks = grade.get("outputs", {}).get(task_ref["digest"])
    if (
        not isinstance(checks, dict)
        or set(checks) != set(expected_checks)
        or any(type(v) is not bool for v in checks.values())
    ):
        raise ValueError("grade checks are missing or invalid")
    return checks


def record_view(record):
    return {
        "position": record["task"]["position"],
        "source": record["source"],
        "grades": record["grades"],
    }


def load_previous(path, selected_positions):
    """Read selected sources only; recover completed files after a missed report write."""
    if path is None:
        return {}
    from execution import RunLock

    root = path.parent.resolve(strict=True)
    with RunLock(root):
        report = (
            load_json(path)
            if path.is_file()
            else {"schema_version": REPORT_VERSION, "records": []}
        )
        if report.get("schema_version") != REPORT_VERSION:
            raise ValueError(
                f"unsupported report format; expected {REPORT_VERSION}"
            )
        records = {}
        cache = {}
        for view in report.get("records", []):
            pos = tuple(view.get("position", []))
            if pos not in selected_positions:
                continue
            if pos in records:
                raise ValueError("duplicate previous task position")
            ref = view["source"]
            cache_id = (ref["path"], ref["digest"])
            if cache_id not in cache:
                cache[cache_id] = read_task(ref)
            record = copy.deepcopy(cache[cache_id])
            if tuple(record["task"]["position"]) != pos:
                raise ValueError("report and task positions differ")
            record["grades"] = copy.deepcopy(view.get("grades", {}))
            records[pos] = record
        manifest_path = root / "run.json"
        if manifest_path.is_file():
            manifest = load_json(manifest_path)
            if manifest.get("schema_version") != "skill-evaluator-run/1":
                raise ValueError("unknown run manifest")
            for entry in manifest["entries"]:
                pos = position(entry)
                if pos not in selected_positions:
                    continue
                task_path = root / "tasks" / entry["entry_id"] / "task.json"
                if not task_path.exists():
                    continue
                recovered = read_task(reference(task_path))
                if position(recovered["task"]["entry"]) != pos:
                    raise ValueError("recovered task differs from run manifest")
                if pos in records and records[pos]["source"] != recovered["source"]:
                    raise ValueError("conflicting completed task sources")
                records.setdefault(pos, recovered)
            incomplete = [
                record
                for record in records.values()
                if not set(record["task"]["key"]["graders"]) <= record["grades"].keys()
            ]
            for grade_path in (
                (root / "grades").glob("*/grade.json") if incomplete else ()
            ):
                ref = reference(grade_path)
                grade, _ = read_reference(ref)
                if grade.get("schema_version") != GRADE_VERSION:
                    raise ValueError("unknown grade result")
                for record in incomplete:
                    if record["source"] in grade["tasks"]:
                        record["grades"].setdefault(
                            grade["grader_id"], {"source": ref, "key": grade["key"]}
                        )
        return records


def checks(record, requirements):
    observed = {}
    for grader_id in {r["grader_id"] for r in requirements}:
        if grader_id not in record["grades"]:
            continue
        selected = [r["check_id"] for r in requirements if r["grader_id"] == grader_id]
        grade = record["grades"][grader_id]
        observed.update(
            read_grade(
                grade["source"],
                record["source"],
                grader_id=grader_id,
                key=grade["key"],
                expected_checks=selected,
            )
        )
    return observed
