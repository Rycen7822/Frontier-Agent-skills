"""Bounded Host execution. Task results are immutable and never contain grades."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import copy
import fcntl
import json
import os
import signal
import stat
import subprocess
import threading

from evidence_io import (
    artifact_record,
    atomic_write_bytes,
    atomic_write_json,
    file_sha256,
    resolve_contained_path,
    resolve_host_command,
)
from task_results import write_task
from usage_costs import captured_usage


class RunLock:
    """A live child inherits this lock; a killed parent cannot authorize reuse."""

    def __init__(self, root):
        self.path = root / ".run.lock"
        self.fd = None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(self.fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
            ):
                raise ValueError("invalid run lock")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def __exit__(self, *args):
        # close, rather than LOCK_UN: any surviving child still holds custody.
        os.close(self.fd)
        self.fd = None


class Budget:
    def __init__(self, task, judge, output):
        self.limits = {"task": task, "judge": judge}
        self.used = {"task": 0, "judge": 0}
        self.path = output / "attempts.json"
        self.lock = threading.RLock()
        self.attempts = []

    def reserve(self, role, identity):
        with self.lock:
            if self.used[role] >= self.limits[role]:
                raise ValueError(f"{role} budget exhausted")
            updated = {**self.used, role: self.used[role] + 1}
            attempts = self.attempts + [{"role": role, "id": identity}]
            # A crash after this commit spends an attempt, never creates a free retry.
            atomic_write_json(
                self.path,
                {"limits": self.limits, "used": updated, "attempts": attempts},
                replace=self.path.exists(),
            )
            self.used, self.attempts = updated, attempts


def request(run_id, entry, kind, payload=None):
    return {
        "record_type": "skill-evaluator-host-request/2",
        "envelope": {
            # Field names are the existing Host wire ABI; no compiled plan is created.
            "plan_id": run_id,
            "entry_ordinal": entry["entry_ordinal"],
            "entry_id": entry["entry_id"],
            "run_id": run_id + "." + entry["entry_id"],
            "attempt_id": "attempt.1",
            "attempt": 1,
            "request_id": f"request.{entry['entry_ordinal']}.{kind}",
            "request_kind": kind,
        },
        "payload": copy.deepcopy(
            entry["execute_case_payload"] if payload is None else payload
        ),
    }


def run_process(argv, *, cwd, environment, input_bytes, timeout_seconds, custody_fd):
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=True,
        pass_fds=(custody_fd,),
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(input_bytes, timeout=timeout_seconds)
    except BaseException as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        if not isinstance(exc, subprocess.TimeoutExpired):
            raise
        timed_out = True
    return process.returncode, stdout, stderr, timed_out


def parse_protocol(stdout, sent):
    try:
        records = [
            json.loads(line)
            for line in stdout.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Host output is not UTF-8 JSONL") from exc
    if not records or any(not isinstance(row, dict) for row in records):
        raise ValueError("Host output lacks a terminal result")
    events, result = records[:-1], records[-1]
    if (
        result.get("record_type") != "skill-evaluator-host-result/2"
        or result.get("terminal") is not True
        or result.get("envelope") != sent["envelope"]
    ):
        raise ValueError("Host terminal identity differs from its request")
    for sequence, event in enumerate(events):
        if (
            event.get("record_type") != "skill-evaluator-host-event/2"
            or event.get("seq") != sequence
        ):
            raise ValueError("Host events are not a contiguous prefix")
        parent = event.get("parent_seq")
        if parent is not None and (
            type(parent) is not int or not 0 <= parent < sequence
        ):
            raise ValueError("Host event parent is outside the prefix")
    if result.get("terminal_status") not in {
        "completed",
        "failed",
        "cancelled",
        "timeout",
        "protocol_error",
    }:
        raise ValueError("unknown Host terminal status")
    if (
        result.get("protocol_error") is not None
        or result["terminal_status"] == "protocol_error"
    ):
        raise ValueError(f"Host protocol error: {result.get('protocol_error')}")
    if (
        result.get("failure_class") is not None
        or result.get("provider_error_code") is not None
    ):
        raise RuntimeError(
            f"Host apparatus failure: {result.get('failure_class')} {result.get('provider_error_code')}"
        )
    for field in ("artifacts", "principals", "actions", "assertions"):
        if not isinstance(result.get(field), list):
            raise ValueError(f"Host result lacks {field}")
    if result.get("cleanup", {}).get("status") not in {"clean", "not_applicable"}:
        raise ValueError("Host cleanup is incomplete")
    return events, result


def invoke(host, source_root, sent, directory, timeout, custody_fd):
    directory.mkdir(parents=True, exist_ok=True)
    workspace = directory / "workspace"
    workspace.mkdir(exist_ok=True)
    argv, environment = resolve_host_command(host, source_root)
    atomic_write_json(directory / "request.json", sent)
    code, stdout, stderr, timeout_hit = run_process(
        argv,
        cwd=workspace,
        environment=environment,
        input_bytes=json.dumps(sent).encode(),
        timeout_seconds=timeout,
        custody_fd=custody_fd,
    )
    atomic_write_bytes(directory / "stdout.jsonl", stdout)
    atomic_write_bytes(directory / "stderr.txt", stderr)
    if timeout_hit or code != 0:
        raise RuntimeError(
            f"Host {'timed out' if timeout_hit else f'exited {code}'}; see {directory / 'stderr.txt'}"
        )
    events, result = parse_protocol(stdout, sent)
    paths = {}
    for binding in result["artifacts"]:
        name, path = resolve_contained_path(
            directory, binding["path"], "Host artifact", kind="file"
        )
        if (
            not name.startswith("workspace/")
            or name in paths
            or file_sha256(path) != binding["digest"]
        ):
            raise ValueError(
                "Host artifact is duplicated, outside workspace or damaged"
            )
        paths[name] = path
    result_path = directory / "result.json"
    atomic_write_json(result_path, result)
    paths.update(
        {
            name: directory / name
            for name in ("request.json", "stdout.jsonl", "stderr.txt", "result.json")
        }
    )
    return result, events, paths


def restore_fixture(entry, source_root, workspace):
    workspace.mkdir(parents=True)
    for kind in ("initial_files", "initial_state"):
        for binding in entry["execute_case_payload"]["fixture"][kind]:
            name, source = resolve_contained_path(
                source_root, binding["path"], "fixture", kind="file"
            )
            if file_sha256(source) != binding["sha256"]:
                raise ValueError("fixture changed after selection")
            destination = workspace / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(destination, source.read_bytes())


def execute_task(entry, key, *, host, source_root, output, run_id, budget, custody_fd):
    directory = output / "tasks" / entry["entry_id"]
    budget.reserve("task", entry["entry_id"])
    directory.mkdir(parents=True)
    probe, _, _ = invoke(
        host,
        source_root,
        request(
            run_id,
            entry,
            "probe_capability",
            {
                "capability": "state_snapshot_reset",
                "strategy": host["reset"]["strategy"],
                "scopes": host["reset"].get("scopes", []),
            },
        ),
        directory / "reset",
        entry["timeout_seconds"],
        custody_fd,
    )
    if probe["terminal_status"] != "completed":
        raise ValueError("Host reset probe did not complete")
    restore_fixture(entry, source_root, directory / "workspace")
    result, _, paths = invoke(
        host,
        source_root,
        request(run_id, entry, "execute_case"),
        directory,
        entry["timeout_seconds"],
        custody_fd,
    )
    # Host owns apparatus classification; a known infrastructure failure is not an outcome.
    failure = result.get("infrastructure_failure")
    if failure:
        raise RuntimeError(f"Host infrastructure failure: {failure}")
    usage = captured_usage(result, entry, host, role="task")
    bindings = [
        artifact_record(path, directory, encoding="utf-8") for path in paths.values()
    ]
    return write_task(
        directory / "task.json",
        entry=entry,
        key=key,
        result=artifact_record(directory / "result.json", directory, encoding="utf-8"),
        bindings=bindings,
        usage=usage,
    )


def run_tasks(entries, *, max_parallel, worker, on_complete):
    """Dispatch only ready case lanes; never occupy a worker waiting on resources."""
    groups = defaultdict(list)
    for entry in entries:
        groups[entry["case_id"]].append(entry)
    pending = list(groups.values())
    active = {}
    resources = set()
    failure = None
    stopped = threading.Event()

    def lane(group):
        try:
            for entry in group:
                if stopped.is_set():
                    return
                record = worker(entry)
                on_complete(record)
        except BaseException:
            stopped.set()
            raise

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        while pending or active:
            if failure is None:
                for group in list(pending):
                    required = set().union(*(set(e["shared_resources"]) for e in group))
                    if len(active) >= max_parallel:
                        break
                    if required & resources:
                        continue
                    pending.remove(group)
                    resources.update(required)
                    active[pool.submit(lane, group)] = required
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                resources.difference_update(active.pop(future))
                try:
                    future.result()
                except BaseException as exc:
                    failure = failure or exc
            if failure is not None:
                pending.clear()
    if failure is not None:
        raise failure
