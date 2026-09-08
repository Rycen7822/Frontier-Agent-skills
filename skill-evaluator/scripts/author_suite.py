"""Validate a compact suite and form Host requests without a compiled plan."""

from __future__ import annotations

import ast
import copy
from hashlib import sha256
import json
from pathlib import Path
import re

from evidence_io import file_sha256 as file_digest, resolve_contained_path

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PROFILES = {
    "baseline/skill_disabled",
    "candidate/force_loaded",
    "candidate/natural_routing",
}


def identifier(value, label):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def positive(value, label, *, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def local_file(root, name):
    return resolve_contained_path(root, name, "suite input", kind="file")[1]


def _unique(items, field, label):
    if not isinstance(items, list) or not items:
        raise ValueError(f"{label} must be a nonempty list")
    ids = [
        identifier(item.get(field), label) for item in items if isinstance(item, dict)
    ]
    if len(ids) != len(items) or len(ids) != len(set(ids)):
        raise ValueError(f"duplicate or malformed {label}")
    return set(ids)


def _binding(root, value):
    item = {"path": value} if isinstance(value, str) else copy.deepcopy(value)
    path = local_file(root, item["path"])
    observed = file_digest(path)
    if item.get("sha256", observed) != observed:
        raise ValueError(f"input digest mismatch: {item['path']}")
    return {"path": item["path"], "sha256": observed}


def _fixture(root, value):
    if isinstance(value, str):
        value = {"manifest": value}
    if not isinstance(value, dict):
        raise ValueError("fixture must be an object or a manifest path")
    result = {"initial_files": [], "initial_state": [], "fake_services": []}
    if value.get("manifest"):
        binding = _binding(
            root,
            {
                "path": value["manifest"],
                **({"sha256": value["sha256"]} if "sha256" in value else {}),
            },
        )
        result.update(manifest=binding["path"], sha256=binding["sha256"])
    seen = set()
    for kind in ("initial_files", "initial_state"):
        for item in value.get(kind, []):
            binding = _binding(root, item)
            if binding["path"] in seen:
                raise ValueError("duplicate fixture destination")
            seen.add(binding["path"])
            result[kind].append(binding)
    if value.get("fake_services"):
        raise ValueError(
            "configure fixture services in the Host; evaluator no longer orchestrates them"
        )
    return result


def _graders(items, root):
    _unique(items, "grader_id", "grader")
    result = copy.deepcopy(items)
    for grader in result:
        _unique(grader.get("checks"), "check_id", "grader check")
        for check in grader["checks"]:
            if (
                check.get("dimension")
                not in {"outcome", "safety", "process", "quality"}
                or type(check.get("required")) is not bool
            ):
                raise ValueError("checks require a dimension and boolean required flag")
            if (
                not isinstance(check.get("pass_condition"), str)
                or not check["pass_condition"].strip()
            ):
                raise ValueError("checks require a concrete pass_condition")
        if grader.get("type") == "deterministic":
            verifier = grader["verifier"]
            local_file(root, verifier["path"])
            if (
                not isinstance(verifier.get("argv"), list)
                or not verifier["argv"]
                or not all(isinstance(a, str) and a for a in verifier["argv"])
            ):
                raise ValueError("verifier argv must be nonempty strings")
            verifier.setdefault("cwd", ".")
            verifier.setdefault("env_allowlist", [])
            verifier.setdefault("input_allowlist", ["result.json"])
            verifier.setdefault("pass_exit_codes", [0])
            positive(verifier.setdefault("timeout_seconds", 30), "verifier timeout")
            if not verifier["input_allowlist"]:
                raise ValueError("verifier must consume declared task evidence")
        elif grader.get("type") == "model":
            if "prompt" in grader:
                if (
                    not isinstance(grader["prompt"], str)
                    or not grader["prompt"].strip()
                ):
                    raise ValueError("model grader prompt must be nonempty")
            elif "path" in grader.get("prompt_template", {}):
                local_file(root, grader["prompt_template"]["path"])
            else:
                raise ValueError("model grader needs a prompt or prompt_template path")
        else:
            raise ValueError("grader type must be deterministic or model")
    return result


def normalize(author, host, root, *, case_ids=None):
    """One input contract, also used for dependency selection and execution."""
    if not isinstance(author, dict) or author.get("schema_version") != 1:
        raise ValueError("expected compact suite schema_version 1")
    if "contract" in author:
        raise ValueError(
            "unsupported contract field; declare cases, graders and treatments directly in the suite"
        )
    skill_id = identifier(author.get("skill_id"), "skill_id")
    catalog = host.get("catalog", {}).get("entries", [])
    if sum(item.get("id") == skill_id for item in catalog) != 1:
        raise ValueError("skill must occur exactly once in the Host catalog")
    known = _unique(author.get("cases"), "case_id", "case")
    if case_ids and not set(case_ids) <= known:
        raise ValueError("selected case is absent from the suite")
    graders = _graders(author.get("graders"), root)
    declarations = {g["grader_id"]: g for g in graders}
    constraints = copy.deepcopy(author.get("constraints", {}))
    for name in ("task_attempt_budget", "judge_invocation_budget"):
        positive(constraints.setdefault(name, 0), name, minimum=0)
    timeout = positive(
        constraints.setdefault("timeout_seconds", 300), "timeout_seconds"
    )
    repeats = positive(author.get("repeats", 1), "repeats")
    cases = []
    for original in author["cases"]:
        if case_ids and original["case_id"] not in case_ids:
            continue
        case = copy.deepcopy(original)
        case["timeout_seconds"] = min(
            positive(case.get("timeout_seconds", timeout), "case timeout"), timeout
        )
        case["fixture"] = _fixture(root, case.get("fixture", {}))
        case.setdefault("tags", [])
        case.setdefault("shared_resources", [])
        if not all(
            isinstance(v, str) and v for v in case["tags"] + case["shared_resources"]
        ):
            raise ValueError("tags and shared_resources must contain nonempty strings")
        context = case.setdefault("execution_context", {})
        context.setdefault("task", case.get("prompt", ""))
        context.setdefault("expected_principal_slots", ["main"])
        context.setdefault("expected_tools", [])
        context.setdefault("expected_policy_surfaces", [])
        if "turns" not in case:
            case["turns"] = [
                {
                    "turn_id": "turn-1",
                    "input": {
                        "kind": "user_message",
                        "content": case.get("prompt", context["task"]),
                    },
                }
            ]
        _unique(case["turns"], "turn_id", "turn")
        for turn in case["turns"]:
            content = turn.get("input", {}).get("content")
            if (
                turn.get("input", {}).get("kind") != "user_message"
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError("turns require nonempty user_message input")
            turn.setdefault("open_obligations", [])
            turn.setdefault("due_obligations", [])
        requirements = case.get("requirements")
        _unique(requirements, "check_id", "case check")
        for requirement in requirements:
            grader = declarations.get(requirement.get("grader_id"))
            check = (
                next(
                    (
                        c
                        for c in grader["checks"]
                        if c["check_id"] == requirement["check_id"]
                    ),
                    None,
                )
                if grader
                else None
            )
            if check is None:
                raise ValueError("requirement has no declared grader check")
            for field in ("dimension", "required"):
                if field in requirement and requirement[field] != check[field]:
                    raise ValueError("requirement differs from grader check")
                requirement[field] = check[field]
            if requirement.get("owner", grader["type"]) != grader["type"]:
                raise ValueError("requirement owner differs from grader")
            requirement["owner"] = grader["type"]
        if not any(r["required"] and r["dimension"] == "outcome" for r in requirements):
            raise ValueError("case needs a required outcome oracle")
        # These empty wire fields serve the existing Host ABI, not evaluator semantics.
        if (
            case.get("coordination")
            or case.get("fault_script")
            or case.get("state_model", {}).get("scope", "none") != "none"
        ):
            raise ValueError(
                "domain coordination/state/fault checks now belong in the Host and verifier"
            )
        case.setdefault("state_model", {"scope": "none"})
        case.setdefault("fault_script", [])
        cases.append(case)
    treatments = copy.deepcopy(
        author.get(
            "treatments",
            [
                {"treatment_id": "baseline", "profile": "baseline/skill_disabled"},
                {"treatment_id": "candidate", "profile": "candidate/force_loaded"},
            ],
        )
    )
    _unique(treatments, "treatment_id", "treatment")
    for treatment in treatments:
        if treatment.get("profile") not in PROFILES:
            raise ValueError("unsupported treatment profile")
        selected = treatment.get("scenario_ids", sorted(known))
        exclusions = treatment.get("exclusions", [])
        if (
            not isinstance(selected, list)
            or not set(selected) <= known
            or not isinstance(exclusions, list)
            or not set(exclusions) <= known
        ):
            raise ValueError("treatment case selection is invalid")
        active = {case["case_id"] for case in cases}
        treatment["scenario_ids"] = [item for item in selected if item in active]
        treatment["exclusions"] = [item for item in exclusions if item in active]
    analysis = copy.deepcopy(author.get("analysis", {}))
    confidence = analysis.setdefault("confidence_level", 0.95)
    if type(confidence) not in (int, float) or not 0 < confidence < 1:
        raise ValueError("confidence_level must lie between zero and one")
    positive(analysis.setdefault("bootstrap_iterations", 2000), "bootstrap_iterations")
    positive(analysis.setdefault("random_seed", 0), "random_seed", minimum=0)
    return {
        "schema_version": 1,
        "skill_id": skill_id,
        "cases": cases,
        "graders": graders,
        "treatments": treatments,
        "repeats": repeats,
        "constraints": constraints,
        "analysis": analysis,
    }


def entries(suite, host):
    """Form transient execution items; no serialized spec or compiled plan."""
    execution = host["identity"]["execution"]
    result = []
    for case in suite["cases"]:
        for repeat in range(1, suite["repeats"] + 1):
            for treatment in suite["treatments"]:
                if (
                    case["case_id"] not in treatment["scenario_ids"]
                    or case["case_id"] in treatment["exclusions"]
                ):
                    continue
                position = [case["case_id"], treatment["treatment_id"], repeat]
                entry_id = "entry-" + digest(position)[7:31]
                variant = {
                    **treatment,
                    "base_catalog_id": host["catalog"]["catalog_id"],
                }
                result.append(
                    {
                        "entry_id": entry_id,
                        "entry_ordinal": len(result),
                        "case_id": position[0],
                        "treatment_id": position[1],
                        "repeat": repeat,
                        "shared_resources": case["shared_resources"],
                        "timeout_seconds": case["timeout_seconds"],
                        "execute_case_payload": {
                            "subject_skill_id": suite["skill_id"],
                            "case": copy.deepcopy(case),
                            "treatment": variant,
                            "repeat": repeat,
                            "workspace": f"workspaces/{entry_id}",
                            "fixture": case["fixture"],
                            "catalog": host["catalog"]["entries"],
                            "execution_context": case["execution_context"],
                            "coordination": None,
                            "turns": case["turns"],
                            "fault_script": [],
                            "model_policy": execution["model"],
                            "tool_policy": execution["tool_schema_id"],
                            "network_policy": execution["policy_id"],
                            "permission_policy": execution["policy_id"],
                            "context_policy": execution["policy_id"],
                            "observation_contracts": [],
                            "capture_contract": host.get("capture", {}),
                            "artifact_contract": {},
                        },
                    }
                )
    if not result:
        raise ValueError("selected treatments exclude every case")
    return result


def digest(value):
    return (
        "sha256:"
        + sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )


def local_python_dependencies(paths):
    """Include concrete sibling imports used by verifier/adapter scripts."""
    found = set()
    pending = list(paths)
    while pending:
        path = Path(pending.pop()).resolve()
        if path in found or not path.is_file():
            continue
        found.add(path)
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
        for name in names:
            candidate = path.parent / (name + ".py")
            if candidate.is_file() and candidate not in found:
                pending.append(candidate)
    return found
