#!/usr/bin/env python3
"""Change-scoped maintenance and evaluation; check never invokes a model."""

from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def run_suite(args):
    import threading
    import time
    import author_suite
    import evidence_reuse
    import execution
    import grading
    import analyze_runs
    import task_results
    from evidence_io import atomic_write_json
    from usage_costs import aggregate_captured

    started = time.monotonic()
    if args.impact == "editorial":
        result = classify_change([str(args.suite)], "editorial")
        if args.previous_report and args.previous_report.is_file():
            result["previous_report"] = evidence_reuse.historical_summary(
                args.previous_report
            )
        return result
    author_suite.positive(args.max_parallel, "max_parallel")
    source = args.suite.resolve(strict=True).parent
    host_path = args.host.resolve(strict=True)
    host = json.loads(host_path.read_text())
    author = json.loads(args.suite.read_text())
    suite = author_suite.normalize(author, host, source, case_ids=args.case)
    entries = author_suite.entries(suite, host)
    by_position = {task_results.position(e): e for e in entries}
    keys = {
        p: evidence_reuse.dependency_key(suite, e, host, source)
        for p, e in by_position.items()
    }
    previous = task_results.load_previous(args.previous_report, set(by_position))
    declarations = {g["grader_id"]: g for g in suite["graders"]}
    records, needs_run, needed, decisions = {}, set(), {}, []
    for pos, entry in by_position.items():
        key, record = keys[pos], previous.get(pos)
        decision = evidence_reuse.select_evidence_action(
            record["task"]["key"] if record else None, key
        )
        changed = set(key["graders"])
        if record and decision["action"] != "rerun_affected":
            changed = {
                gid
                for gid, expected in key["graders"].items()
                if record["grades"].get(gid, {}).get("key") != expected
            }
            for gid in changed:
                grader = declarations[gid]
                required_inputs = (
                    grader["verifier"]["input_allowlist"]
                    if grader["type"] == "deterministic"
                    else grading.transport.EVIDENCE_PATHS.values()
                )
                if not set(required_inputs) <= record["paths"].keys():
                    decision = {
                        "action": "rerun_affected",
                        "reason": "required_observation_missing",
                    }
                    break
        if decision["action"] == "rerun_affected":
            needs_run.add(pos)
            needed[pos] = set(key["graders"])
        else:
            record["grades"] = {
                gid: value
                for gid, value in record["grades"].items()
                if gid in key["graders"] and gid not in changed
            }
            # Selected reused grades are checked before any execution is prepared.
            task_results.checks(
                record, entry["execute_case_payload"]["case"]["requirements"]
            )
            records[pos] = record
            if changed:
                needed[pos] = changed
            decision = {
                "action": "regrade" if changed else "reuse_exact",
                "reason": "grading_changed" if changed else "dependencies_unchanged",
            }
        decisions.append({"position": list(pos), **decision})
    task_limit = (
        args.task_attempt_budget
        if args.task_attempt_budget is not None
        else suite["constraints"]["task_attempt_budget"]
    )
    judge_limit = (
        args.judge_invocation_budget
        if args.judge_invocation_budget is not None
        else suite["constraints"]["judge_invocation_budget"]
    )
    author_suite.positive(task_limit, "task budget", minimum=0)
    author_suite.positive(judge_limit, "judge budget", minimum=0)
    judge_count = len(grading.batches(entries, needed, declarations, keys))
    if task_limit < len(needs_run) or judge_limit < judge_count:
        return {
            "action": "budget_incomplete",
            "reason": "budget below selected task attempts or judge invocations",
            "required_task_attempts": len(needs_run),
            "required_judge_invocations": judge_count,
            "task_attempts": 0,
            "judge_invocations": 0,
            "decisions": decisions,
            "usefulness_status": "not_evaluable",
        }
    preflight = (
        _host_preflight(host_path, source)
        if needs_run or judge_count
        else {"status": "not_needed", "provider_requests": 0}
    )
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(
            "output already exists; use a fresh directory and --previous-report"
        )
    output.mkdir(parents=True)
    action = "rerun_affected" if needs_run else "regrade" if needed else "reuse_exact"
    budget = execution.Budget(task_limit, judge_limit, output)
    run_id = "run-" + author_suite.digest(str(output))[7:31]
    costs = []
    mutex = threading.RLock()
    previous_rows = []
    for pos, old in previous.items():
        if pos[1] != "candidate" or pos not in by_position:
            continue
        same_execution = all(
            old["task"]["key"].get(field) == keys[pos][field]
            for field in evidence_reuse.EXECUTION_DEPENDENCIES
            if field != "skill"
        )
        same_grading = all(
            old["grades"].get(gid, {}).get("key") == key
            for gid, key in keys[pos]["graders"].items()
        )
        if same_execution and same_grading:
            previous_rows.append(
                analyze_runs.record_summary(old, by_position[pos], variant="previous")
            )

    def publish(usage=None, *, error=None):
        with mutex:
            if usage:
                costs.append(usage)
            known_tasks = sum(item["usage"]["role"] == "task" for item in costs)
            known_judges = sum(item["usage"]["role"] == "judge" for item in costs)
            unknown_roles = {
                role
                for role, known in (("task", known_tasks), ("judge", known_judges))
                if budget.used[role] > known
            }
            summary = {
                "schema_version": task_results.REPORT_VERSION,
                "action": "not_executable" if error else action,
                "task_attempts": budget.used["task"],
                "judge_invocations": budget.used["judge"],
                "calibration_invocations": 0,
                "decisions": decisions,
                "selected_cases": sorted({e["case_id"] for e in entries}),
                "preflight": preflight,
                "costs": aggregate_captured(costs, unknown_roles=unknown_roles),
                "wall_clock_ms": (time.monotonic() - started) * 1000,
                "records": [
                    task_results.record_view(records[p]) for p in sorted(records)
                ],
                **analyze_runs.summarize(
                    records, entries, suite["analysis"], previous_rows=previous_rows
                ),
            }
            if error:
                summary.update(
                    reason=str(error),
                    automatic_retry=False,
                    evidence_status="incomplete",
                    usefulness_status="not_evaluable",
                )
            path = output / "summary.json"
            atomic_write_json(path, summary, replace=path.exists())
            return summary

    def completed(record):
        with mutex:
            records[tuple(record["task"]["position"])] = record
            publish(
                {"digest": record["source"]["digest"], "usage": record["task"]["usage"]}
            )

    with execution.RunLock(output) as custody:
        if needs_run or needed:
            atomic_write_json(
                output / "run.json",
                {
                    "schema_version": "skill-evaluator-run/1",
                    "run_id": run_id,
                    "suite": suite,
                    "entries": entries,
                    "host": host,
                    "keys": {e["entry_id"]: keys[p] for p, e in by_position.items()},
                },
            )
        publish()
        try:

            def worker(entry):
                pos = task_results.position(entry)
                if (
                    evidence_reuse.dependency_key(suite, entry, host, source)
                    != keys[pos]
                ):
                    raise ValueError("execution inputs changed after selection")
                return execution.execute_task(
                    entry,
                    keys[pos],
                    host=host,
                    source_root=source,
                    output=output,
                    run_id=run_id,
                    budget=budget,
                    custody_fd=custody.fd,
                )

            execution.run_tasks(
                [e for e in entries if task_results.position(e) in needs_run],
                max_parallel=args.max_parallel,
                worker=worker,
                on_complete=completed,
            )
            for pos in needed:
                if (
                    evidence_reuse.dependency_key(suite, by_position[pos], host, source)
                    != keys[pos]
                ):
                    raise ValueError("grading inputs changed after selection")
            grading.grade_tasks(
                records,
                entries,
                needed,
                keys,
                suite=suite,
                host=host,
                source_root=source,
                output=output,
                run_id=run_id,
                budget=budget,
                custody_fd=custody.fd,
                on_progress=publish,
            )
        except BaseException as exc:
            publish(error=exc)
            raise
        result = publish()
    return {k: v for k, v in result.items() if k not in {"records", "cases"}} | {
        "report": str(output / "summary.json")
    }


sys.dont_write_bytecode = True


NON_MODEL_FILES = {
    "README.md",
    "RELEASE_NOTES.md",
}
GENERATED_IDENTITY = "frontier-engineering.bundle.json"
IMPACTS = ("auto", "editorial", "behavior", "runtime", "grading")
_PREFLIGHT_CACHE: dict[str, dict[str, Any]] = {}


def preflight_runtime(args: argparse.Namespace, workspace: Path) -> dict[str, Any]:
    """Check the real fresh/resume parsers without supplying a task prompt.

    Help parsing is not authentication, tool execution or model qualification.
    Actual config/stream validation remains with the Host and bounded smoke.
    """
    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import codex_eval_host as host

    last_message = workspace / "preflight-last-message"
    commands = {
        "fresh": host._fresh_argv(args, workspace, last_message, ephemeral=True),
        "resume": host._resume_argv(args, "preflight-session", last_message),
    }
    if getattr(args, "judge_model", None) or getattr(args, "judge_effort", None):
        commands["judge"] = host._fresh_argv(
            args, workspace, last_message, ephemeral=True, role="judge"
        )
    executable = Path(args.codex).resolve(strict=True)
    version = subprocess.run(
        [str(executable), "--version"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if version.returncode:
        raise ValueError(
            "runtime version check failed: " + version.stderr.strip()[:1000]
        )
    fingerprint = sha256(
        executable.read_bytes()
        + json.dumps(commands, sort_keys=True).encode()
        + version.stdout.encode()
    ).hexdigest()
    if fingerprint in _PREFLIGHT_CACHE:
        return {**_PREFLIGHT_CACHE[fingerprint], "reused": True}
    checks = []
    for name, argv in commands.items():
        if argv[-1] != "-":
            raise ValueError(
                f"{name} argv does not end in the expected stdin prompt marker"
            )
        result = subprocess.run(
            [*argv[:-1], "--help"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode:
            raise ValueError(
                f"{name} CLI arguments rejected: {result.stderr.strip()[:2000]}"
            )
        checks.append(name)
    result = {
        "status": "argv_compatible",
        "fingerprint": fingerprint,
        "checks": checks,
        "reused": False,
        "provider_requests": 0,
        "runtime_validation": "pending_execution",
    }
    _PREFLIGHT_CACHE[fingerprint] = result
    return dict(result)


def classify_change(paths: list[str], impact: str = "auto") -> dict[str, Any]:
    """An editorial declaration is a maintenance judgment, not new model proof."""
    if impact not in IMPACTS:
        raise ValueError(f"unsupported impact: {impact}")
    paths = sorted(set(paths))
    relevant = [
        p for p in paths if p not in NON_MODEL_FILES and p != GENERATED_IDENTITY
    ]
    if not paths:
        action, reason = "skip", "no_change"
    elif impact == "editorial":
        action, reason = "carry_forward", "maintainer_declared_semantics_unchanged"
    elif not relevant:
        action, reason = "skip", "non_model_or_generated_identity_only"
    else:
        action = "needs_scoped_evidence"
        reason = "impact_requires_judgment" if impact == "auto" else f"{impact}_changed"
    return {
        "action": action,
        "reason": reason,
        "impact": impact,
        "affected_paths": paths,
        "affected_cases": [],
        "checks": [],
        "model_calls": 0,
        "new_behavior_evidence": False,
    }


def _git(root: Path, *args: str) -> bytes:
    # Raw output is parsed; no shell interpolation or RTK presentation transforms.
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def _version_only(root: Path, base: str) -> bool:
    def without_versions(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: without_versions(v)
                for k, v in value.items()
                if k not in {"version", "bundle_version"}
            }
        if isinstance(value, list):
            return [without_versions(v) for v in value]
        return value

    try:
        old = json.loads(_git(root, "show", f"{base}:bundle-manifest.json"))
        new = json.loads((root / "bundle-manifest.json").read_text())
    except (ValueError, OSError):
        return False
    return without_versions(old) == without_versions(new)


def check_change(root: Path, base: str, impact: str = "auto") -> dict[str, Any]:
    root = root.resolve()
    try:
        # Resolve a revision first so user input cannot become a Git option.
        revision = (
            _git(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}")
            .decode()
            .strip()
        )
        changed = _git(
            root, "diff", "--name-only", "-z", "--no-renames", revision, "--"
        )
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
        paths = sorted(set(p for p in (changed + untracked).decode().split("\0") if p))
    except ValueError as exc:
        result = classify_change([], impact)
        result.update(
            action="needs_scoped_evidence",
            reason="baseline_unavailable",
            detail=str(exc),
        )
        return result
    version_only = "bundle-manifest.json" in paths and _version_only(root, revision)
    relevant = [p for p in paths if not (p == "bundle-manifest.json" and version_only)]
    result = classify_change(relevant, impact)
    result["affected_paths"] = paths
    if version_only and not relevant:
        result["reason"] = "version_only"
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        check = None
        try:
            if path.suffix == ".py":
                check = "python_syntax"
                ast.parse(path.read_text(), filename=relative)
            elif path.suffix == ".json":
                check = "json_syntax"
                json.loads(path.read_text())
        except (ValueError, SyntaxError, OSError) as exc:
            result["checks"].append(
                {"path": relative, "check": check, "passed": False, "error": str(exc)}
            )
            result["action"] = "local_check_failed"
        else:
            if check:
                result["checks"].append(
                    {"path": relative, "check": check, "passed": True}
                )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check", help="classify a change and run local syntax checks; zero model calls"
    )
    check.add_argument("--base", required=True)
    check.add_argument("--impact", choices=IMPACTS, default="auto")
    check.add_argument("--root", type=Path, default=Path.cwd())
    check.add_argument("--previous-report", type=Path)
    run = commands.add_parser(
        "run", help="run or reuse only selected maintenance cases"
    )
    run.add_argument("--suite", type=Path, required=True)
    run.add_argument("--host", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--previous-report", type=Path)
    run.add_argument("--case", action="append")
    run.add_argument("--impact", choices=IMPACTS, default="auto")
    run.add_argument("--max-parallel", type=int, default=1)
    run.add_argument("--task-attempt-budget", type=int)
    run.add_argument("--judge-invocation-budget", type=int)
    args = parser.parse_args(argv)
    if args.command == "run":
        try:
            if args.max_parallel < 1 or any(
                v is not None and v < 0
                for v in (args.task_attempt_budget, args.judge_invocation_budget)
            ):
                raise ValueError("parallelism must be positive and budgets nonnegative")
            result = run_suite(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return (
                3
                if result.get("action") == "budget_incomplete"
                or result.get("evidence_status") == "incomplete"
                else 0
            )
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(
                json.dumps(
                    {
                        "action": "not_executable",
                        "reason": str(exc),
                        "automatic_retry": False,
                    },
                    ensure_ascii=False,
                )
            )
            return 2
    result = check_change(args.root, args.base, args.impact)
    if args.previous_report is not None:
        from evidence_reuse import historical_summary

        try:
            result["previous_report"] = historical_summary(args.previous_report)
        except (OSError, ValueError) as exc:
            result["previous_report"] = {
                "path": str(args.previous_report),
                "available": False,
                "reason": str(exc),
            }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["action"] == "local_check_failed":
        return 1
    return 2 if result["action"] == "needs_scoped_evidence" else 0


def _host_preflight(host_path: Path, source_root: Path) -> dict[str, Any]:
    value = json.loads(host_path.read_text())
    command = value["command"]["argv"]
    if value["identity"]["adapter"]["id"] != "codex-eval-host":
        from evidence_io import resolve_host_command

        resolve_host_command(value, source_root)
        return {"status": "host_command_validated", "provider_requests": 0}
    start = next(
        (
            i + 1
            for i, arg in enumerate(command)
            if Path(arg).name == "codex_eval_host.py"
        ),
        None,
    )
    if start is None:
        raise ValueError("Codex Host command does not bind codex_eval_host.py")
    adapter = (source_root / command[start - 1]).resolve(strict=True)
    scripts = str(adapter.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import codex_eval_host as host

    try:
        args = host._parser().parse_args(command[start:])
    except SystemExit as exc:
        raise ValueError("Host command arguments do not match its adapter") from exc
    manifest = host._validate_manifest(host_path, args)
    if args.isolation_tool is not None:
        from _codex_eval_isolation import isolated_child_argv, request_codex_home

        with request_codex_home(args.isolation_tool) as codex_home:
            isolated_child_argv(
                isolation_tool=args.isolation_tool,
                sandbox=args.sandbox,
                source_root=host._manifest_source_root(manifest),
                codex=args.codex,
                code_mode_host=args.code_mode_host,
                argv=host._fresh_argv(
                    args,
                    source_root,
                    source_root / "preflight-last-message",
                    ephemeral=True,
                ),
                workspace=source_root,
                codex_home=codex_home,
                model_catalog_snapshot=args.model_catalog_snapshot,
                model_catalog_sha256=args.model_catalog_sha256,
            )
    return preflight_runtime(args, source_root)


if __name__ == "__main__":
    raise SystemExit(main())
