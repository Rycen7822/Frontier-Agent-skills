"""Dependency selection without a compiler or historical contract loader."""

from __future__ import annotations

import json
from pathlib import Path

from author_suite import digest, file_digest, local_file, local_python_dependencies

EXECUTION_DEPENDENCIES = (
    "task",
    "fixture",
    "skill",
    "shared_inputs",
    "runtime",
    "model",
    "effort",
    "catalog",
)


def historical_summary(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("historical report must be an object")
    return {
        "path": str(path.resolve()),
        "historical_claim": value.get("usefulness_status", "not_evaluable"),
        "new_behavior_evidence": False,
    }


def select_evidence_action(previous, current, *, impact="auto", raw_complete=True):
    if impact == "editorial":
        return {
            "action": "carry_forward" if previous else "skip",
            "reason": "maintainer_declared_semantics_unchanged",
        }
    if previous is None:
        return {"action": "rerun_affected", "reason": "no_source_evidence"}
    for field in EXECUTION_DEPENDENCIES:
        if (
            field not in previous
            or field not in current
            or previous[field] != current[field]
        ):
            return {"action": "rerun_affected", "reason": f"{field}_changed"}
    if previous.get("graders") != current.get("graders"):
        return {
            "action": "regrade" if raw_complete else "rerun_affected",
            "reason": "grading_changed",
        }
    return {"action": "reuse_exact", "reason": "dependencies_unchanged"}


def input_content(root, value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"source_revision", "created", "expires"}:
                continue
            if key in {"path", "manifest"} and isinstance(item, str):
                path = local_file(root, item)
                result[key] = {
                    "content": file_digest(path),
                    "imports": {
                        str(dep.relative_to(root)): file_digest(dep)
                        for dep in local_python_dependencies([path])
                        if dep.is_relative_to(root)
                    },
                }
            else:
                result[key] = input_content(root, item)
        return result
    if isinstance(value, list):
        return [input_content(root, item) for item in value]
    return value


def dependency_key(suite, entry, host, root):
    payload = entry["execute_case_payload"]
    case, treatment = payload["case"], payload["treatment"]
    execution = host["identity"]["execution"]
    target = next(
        item for item in host["catalog"]["entries"] if item["id"] == suite["skill_id"]
    )
    disabled = treatment["profile"] == "baseline/skill_disabled"
    routing = treatment["profile"] == "candidate/natural_routing"
    argv = host["command"]["argv"]
    task_argv = []
    index = 0
    while index < len(argv):
        if argv[index] in {
            "--judge-model",
            "--judge-effort",
            "--host-manifest",
            "--model-catalog-snapshot",
            "--model-catalog-relative-path",
            "--model-catalog-sha256",
            "--model-catalog-client-version",
        }:
            index += 2
        else:
            task_argv.append(argv[index])
            index += 1
    paths = [
        root / arg
        for arg in task_argv[1:]
        if Path(arg).suffix == ".py" and (root / arg).is_file()
    ]
    files = {str(path): file_digest(path) for path in local_python_dependencies(paths)}
    catalog_model = None
    if "--model-catalog-snapshot" in argv:
        catalog = json.loads(
            (root / argv[argv.index("--model-catalog-snapshot") + 1]).read_text()
        )
        selected = [
            item
            for item in catalog.get("models", [])
            if item.get("slug") == execution["model"]
        ]
        if len(selected) != 1:
            raise ValueError("task model is absent or ambiguous in bound catalog")
        catalog_model = {
            "client_version": catalog.get("client_version"),
            "model": selected[0],
        }
    effort = execution.get("effort")
    if effort is None and "--effort" in argv:
        effort = argv[argv.index("--effort") + 1]
    if effort is None and execution.get("provider") == "fixture-provider":
        effort = "not_applicable"
    if effort is None or not execution.get("model"):
        raise ValueError("task model and effort must be bound")
    judge = host["identity"].get("grading", execution)
    judge = {
        k: v
        for k, v in judge.items()
        if k not in {"pricing_id", "skill_id", "catalog_id"}
    }
    graders = {}
    for grader in suite["graders"]:
        requirements = [
            r for r in case["requirements"] if r["grader_id"] == grader["grader_id"]
        ]
        if requirements:
            graders[grader["grader_id"]] = digest(
                {
                    "grader": input_content(root, grader),
                    "requirements": requirements,
                    "judge": judge if grader["type"] == "model" else None,
                }
            )
    catalog_entries = (
        host["catalog"]["entries"]
        if routing
        else [
            item
            for item in host["catalog"]["entries"]
            if item["id"] != suite["skill_id"]
        ]
    )
    return {
        "task": digest(
            {k: case.get(k) for k in ("turns", "execution_context", "timeout_seconds")}
        ),
        "fixture": digest(input_content(root, case["fixture"])),
        "skill": "disabled" if disabled else target["root_digest"],
        "shared_inputs": digest(
            {"profile": treatment["profile"], "policy": execution["policy_id"]}
        ),
        "runtime": digest(
            {
                "execution": {
                    k: execution.get(k)
                    for k in (
                        "harness",
                        "harness_version",
                        "tool_schema_id",
                        "policy_id",
                    )
                },
                "command": {**host["command"], "argv": task_argv},
                "files": files,
                "model_catalog": catalog_model,
            }
        ),
        "model": digest(
            {k: execution.get(k) for k in ("provider", "model", "model_revision")}
        ),
        "effort": effort,
        "catalog": digest(catalog_entries),
        "graders": graders,
    }
