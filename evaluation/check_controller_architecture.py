#!/usr/bin/env python3
"""Report and enforce the canonical evaluation-controller architecture."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Iterable


OWNER_BY_CLASS = {
    "AttemptStateTests": "campaign",
    "CampaignManifestTests": "campaign",
    "FrozenStudyDesignTests": "studies",
    "HostGraderTests": "host",
    "HostAdapterProtocolTests": "host",
    "ReviewerLifecycleTests": "host",
    "HostCapabilityProbeTests": "host",
    "NativeV5IntegrationTests": "reports",
    "StableProjectionControllerTests": "source_proof",
    "P4EvaluatorTests": "reports",
}
NEGATIVE_WORDS = {
    "cannot",
    "fail",
    "forbid",
    "invalid",
    "missing",
    "reject",
    "tamper",
}
OWNER_NAMES = {
    "canonical": {
        "canonical_bytes",
        "canonical_hash",
        "canonical_json_bytes",
        "canonical_sha256",
    },
    "nofollow": {
        "assert_nofollow",
        "contained_regular_file",
        "nofollow",
        "read_nofollow_regular",
    },
}
STATE_MACHINE_FUNCTIONS = {"initialize_attempt", "run_campaign"}
TEST_SUPPORT_FILES = {"controller_testkit.py"}


def python_files(root: Path) -> tuple[list[Path], list[Path]]:
    files = sorted(root.glob("*.py"))
    tests = [
        path
        for path in files
        if path.name.startswith("test_") or path.name in TEST_SUPPORT_FILES
    ]
    return (
        [path for path in files if path not in tests],
        tests,
    )


def parse_files(paths: Iterable[Path]) -> dict[Path, ast.Module]:
    return {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in paths
    }


def line_count(paths: Iterable[Path]) -> int:
    return sum(
        len(path.read_text(encoding="utf-8").splitlines())
        for path in paths
    )


def function_spans(trees: dict[Path, ast.Module]) -> list[dict[str, object]]:
    spans = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                spans.append({
                    "file": path.name,
                    "function": node.name,
                    "line": node.lineno,
                    "lines": (node.end_lineno or node.lineno) - node.lineno + 1,
                })
    return spans


def import_graph(trees: dict[Path, ast.Module]) -> dict[str, set[str]]:
    modules = {path.stem for path in trees}
    graph = {path.stem: set() for path in trees}
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            else:
                continue
            graph[path.stem].update(name for name in names if name in modules)
    return graph


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for child in graph[node]:
            if child not in indices:
                visit(child)
                low[node] = min(low[node], low[child])
            elif child in active:
                low[node] = min(low[node], indices[child])
        if low[node] == indices[node]:
            component = []
            while True:
                child = stack.pop()
                active.remove(child)
                component.append(child)
                if child == node:
                    break
            if len(component) > 1 or node in graph[node]:
                components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def owner_files(trees: dict[Path, ast.Module]) -> dict[str, list[str]]:
    result = {owner: set() for owner in OWNER_NAMES}
    cli = set()
    for path, tree in trees.items():
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for owner, owned_names in OWNER_NAMES.items():
            if names & owned_names:
                result[owner].add(path.name)
        if "parse_args" in names or any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "ArgumentParser"
            for node in ast.walk(tree)
        ):
            cli.add(path.name)
    return {
        **{key: sorted(value) for key, value in result.items()},
        "cli": sorted(cli),
    }


def behavior_rows(trees: dict[Path, ast.Module]) -> list[dict[str, object]]:
    rows = []
    for path, tree in trees.items():
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                negative = any(word in node.name for word in NEGATIVE_WORDS)
                rows.append({
                    "contract_id": f"{path.stem}.{node.name}",
                    "owner": path.stem.removeprefix("test_"),
                    "positive": not negative,
                    "negative": negative,
                    "new_test": f"{path.name}::{node.name}",
                })
        for owner_node in tree.body:
            if not isinstance(owner_node, ast.ClassDef):
                continue
            owner = OWNER_BY_CLASS.get(owner_node.name, "unmapped")
            target = (
                "test_campaign.py"
                if owner in {"campaign", "source_proof"}
                else "test_host.py"
                if owner == "host"
                else "test_reports.py"
            )
            for node in owner_node.body:
                if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                    continue
                negative = any(word in node.name for word in NEGATIVE_WORDS)
                rows.append({
                    "contract_id": f"{path.stem}.{owner_node.name}.{node.name}",
                    "owner": owner,
                    "positive": not negative,
                    "negative": negative,
                    "new_test": f"{target}::{node.name}",
                })
    return sorted(rows, key=lambda row: str(row["contract_id"]))


def write_matrix(path: Path, rows: list[dict[str, object]]) -> None:
    header = "contract_id\towner\tpositive\tnegative\tnew_test\n"
    body = "".join(
        "\t".join(
            str(row[key]).lower() if isinstance(row[key], bool) else str(row[key])
            for key in ("contract_id", "owner", "positive", "negative", "new_test")
        )
        + "\n"
        for row in rows
    )
    path.write_text(header + body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--matrix", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    production, tests = python_files(root)
    trees = parse_files([*production, *tests])
    production_trees = {path: trees[path] for path in production}
    spans = function_spans(trees)
    rows = behavior_rows({path: trees[path] for path in tests})
    if args.matrix:
        write_matrix(args.matrix, rows)
    graph = import_graph(production_trees)
    observed_cycles = cycles(graph)
    owners = owner_files(production_trees)
    normal_spans = [
        item
        for item in spans
        if item["function"] not in STATE_MACHINE_FUNCTIONS
    ]
    state_spans = [
        item
        for item in spans
        if item["function"] in STATE_MACHINE_FUNCTIONS
    ]
    summary = {
        "root": str(root),
        "production_files": len(production),
        "production_lines": line_count(production),
        "test_files": len(tests),
        "test_lines": line_count(tests),
        "test_contracts": len(rows),
        "max_file_lines": max(
            (len(path.read_text(encoding="utf-8").splitlines()) for path in [*production, *tests]),
            default=0,
        ),
        "max_function_lines": max((int(item["lines"]) for item in spans), default=0),
        "max_normal_function_lines": max(
            (int(item["lines"]) for item in normal_spans),
            default=0,
        ),
        "max_state_machine_lines": max(
            (int(item["lines"]) for item in state_spans),
            default=0,
        ),
        "cycles": observed_cycles,
        "owner_files": owners,
    }
    violations = []
    if summary["production_lines"] > 9_000:
        violations.append("production_lines")
    if summary["test_lines"] > 3_000:
        violations.append("test_lines")
    if summary["max_file_lines"] > 1_500:
        violations.append("max_file_lines")
    if summary["max_normal_function_lines"] > 120:
        violations.append("normal_function_lines")
    if summary["max_state_machine_lines"] > 160:
        violations.append("state_machine_lines")
    if observed_cycles:
        violations.append("import_cycles")
    for owner, files in owners.items():
        if len(files) != 1:
            violations.append(f"{owner}_owner_count")
    summary["violations"] = violations
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 1 if args.check and violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
