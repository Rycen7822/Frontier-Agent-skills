"""One grading path for fresh tasks, rubric changes and interrupted grading."""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import shutil

from author_suite import digest, local_file, local_python_dependencies
from evidence_io import (
    artifact_record,
    atomic_write_bytes,
    normalize_relative_path,
    validate_locator,
)
from execution import invoke, request, run_process
import model_grade_transport as transport
from task_results import checks as task_checks, position, write_grade
from usage_costs import captured_usage


def batches(entries, needed, declarations, keys):
    groups = defaultdict(list)
    for entry in entries:
        pos = position(entry)
        for grader_id in sorted(needed.get(pos, [])):
            if declarations[grader_id]["type"] == "model":
                groups[
                    (entry["case_id"], grader_id, keys[pos]["graders"][grader_id])
                ].append(entry)
    return [
        (grader_id, key, group[start : start + 6])
        for (_, grader_id, key), group in sorted(groups.items())
        for start in range(0, len(group), 6)
    ]


def _checks(output, expected, inputs):
    if (
        not isinstance(output, dict)
        or output.get("grader_failure") is not False
        or output.get("missing_evidence") != []
    ):
        raise ValueError("grader failed or required evidence is missing")
    rows = output.get("checks")
    if (
        not isinstance(rows, list)
        or len(rows) != len(expected)
        or {r.get("check_id") for r in rows} != set(expected)
    ):
        raise ValueError("grader checks differ from selected requirements")
    result = {}
    for row in rows:
        if (
            type(row.get("pass")) is not bool
            or not isinstance(row.get("evidence"), list)
            or not row["evidence"]
        ):
            raise ValueError(
                "deterministic checks require boolean outcomes and evidence"
            )
        for evidence in row["evidence"]:
            name = evidence.get("artifact")
            if name not in inputs:
                raise ValueError("grader evidence is outside declared inputs")
            locator = evidence["locator"]
            if "kind" not in locator:
                kind = (
                    "text_lines"
                    if "start_line" in locator
                    else "json_pointer"
                    if "json_pointer" in locator
                    else "byte_range"
                )
                locator = {"kind": kind, "artifact": name, **locator}
            raw = inputs[name].read_bytes()
            text = raw.decode("utf-8")
            validate_locator(
                locator,
                {
                    name: {
                        "resolved": inputs[name],
                        "encoding": "utf-8",
                        "lines": text.splitlines(),
                        "bytes": len(raw),
                        "text": text,
                    }
                },
            )
        result[row["check_id"]] = row["pass"]
    return result


def deterministic(record, entry, grader, key, *, source_root, output, custody_fd):
    grader_id = grader["grader_id"]
    identity = "grade-" + digest([record["source"], grader_id, key])[7:31]
    directory = output / "grades" / identity
    directory.mkdir(parents=True)
    verifier = grader["verifier"]
    cwd = directory / "workspace"
    if verifier["cwd"] != ".":
        cwd /= normalize_relative_path(verifier["cwd"], "verifier cwd")
    cwd.mkdir(parents=True)
    inputs = {}
    for name in verifier["input_allowlist"]:
        normalized = normalize_relative_path(name, "verifier input")
        source = record["paths"].get(normalized)
        if source is None:
            raise ValueError(f"required verifier input unavailable: {normalized}")
        target = cwd / normalized
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, source.read_bytes())
        inputs[normalized] = target
    script = local_file(source_root, verifier["path"])
    dependencies = local_python_dependencies([script])
    copied = {}
    for dependency in dependencies:
        if not dependency.is_relative_to(source_root):
            raise ValueError("verifier dependency escapes its suite")
        target = directory / "verifier" / dependency.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, dependency.read_bytes())
        target.chmod(dependency.stat().st_mode & 0o777)
        copied[dependency.resolve()] = target.resolve()
    argv = []
    for index, arg in enumerate(verifier["argv"]):
        path = (source_root / arg).resolve()
        if path in copied:
            argv.append(str(copied[path]))
        elif index == 0:
            executable = shutil.which(arg)
            if not executable:
                raise ValueError("verifier executable is unavailable")
            argv.append(str(Path(executable).resolve()))
        elif path.is_file():
            # Explicit local helper/config arguments also become captured inputs.
            relative = path.relative_to(source_root)
            target = directory / "verifier" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                atomic_write_bytes(target, path.read_bytes())
            copied[path] = target.resolve()
            argv.append(str(target.resolve()))
        else:
            argv.append(arg)
    if str(copied[script.resolve()]) not in argv:
        raise ValueError("verifier argv does not invoke its bound source")
    environment = {
        name: os.environ[name]
        for name in verifier["env_allowlist"]
        if name in os.environ
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    code, stdout, stderr, timeout = run_process(
        argv,
        cwd=cwd,
        environment=environment,
        input_bytes=b"",
        timeout_seconds=verifier["timeout_seconds"],
        custody_fd=custody_fd,
    )
    atomic_write_bytes(directory / "stdout.json", stdout)
    atomic_write_bytes(directory / "stderr.txt", stderr)
    if timeout or code not in verifier["pass_exit_codes"]:
        raise RuntimeError(f"verifier {grader_id} failed; see {directory}")
    expected = [
        r["check_id"]
        for r in entry["execute_case_payload"]["case"]["requirements"]
        if r["grader_id"] == grader_id
    ]
    observed = _checks(json.loads(stdout), expected, inputs)
    binding_paths = [
        *inputs.values(),
        *copied.values(),
        directory / "stdout.json",
        directory / "stderr.txt",
    ]
    bindings = [
        artifact_record(path, directory, encoding="utf-8")
        for path in dict.fromkeys(binding_paths)
    ]
    ref = write_grade(
        directory / "grade.json",
        grader_id=grader_id,
        key=key,
        outputs={record["source"]["digest"]: observed},
        task_refs=[record["source"]],
        bindings=bindings,
        usage=None,
    )
    return {"source": ref, "key": key}


def model(
    records,
    entries,
    grader,
    key,
    *,
    host,
    source_root,
    output,
    run_id,
    budget,
    custody_fd,
):
    grader_id = grader["grader_id"]
    task_refs = [records[position(entry)]["source"] for entry in entries]
    identity = "grade-" + digest([task_refs, grader_id, key])[7:31]
    directory = output / "grades" / identity
    items = []
    anonymous = {}
    for entry in entries:
        record = records[position(entry)]
        item_id = "item-" + record["source"]["digest"][7:31]
        anonymous[item_id] = (record, entry)
        observed = task_checks(
            record, entry["execute_case_payload"]["case"]["requirements"]
        )
        findings = [
            {
                "check_id": name,
                "pass": passed,
                "observations": ["Verified by the deterministic oracle."],
            }
            for name, passed in observed.items()
            if any(
                r["check_id"] == name and r["owner"] == "deterministic"
                for r in entry["execute_case_payload"]["case"]["requirements"]
            )
        ]
        items.append(
            transport.execution_item(
                entry,
                record["result"],
                grader=grader,
                findings=findings,
                item_id=item_id,
                paths=record["paths"],
            )
        )
    batch = {
        "batch_id": identity,
        "items": sorted(items, key=lambda item: item["item_id"]),
    }
    prompt = grader.get("prompt")
    if prompt is None:
        prompt = local_file(source_root, grader["prompt_template"]["path"]).read_text()
    payload = {
        "grader_id": grader_id,
        "blinded_input": batch,
        "schedule_id": identity,
        "grader_prompt": prompt,
        "grader_prompt_id": "rubric-" + digest(prompt)[7:31],
        "grader_schema_id": "judgment-v1",
    }
    budget.reserve("judge", identity)
    sent = request(run_id, entries[0], "model_grade", payload)
    result, _, paths = invoke(
        host,
        source_root,
        sent,
        directory,
        max(e["timeout_seconds"] for e in entries),
        custody_fd,
    )
    if result["terminal_status"] != "completed" or len(result["artifacts"]) != 1:
        raise ValueError("model grader did not produce one completed judgment")
    judgment = json.loads(paths[result["artifacts"][0]["path"]].read_text())
    checks = transport.judgment_checks(judgment, batch)
    outputs = {
        record["source"]["digest"]: checks[item_id]
        for item_id, (record, _) in anonymous.items()
    }
    usage = captured_usage(result, entries[0], host, role="judge", grader_id=grader_id)
    bindings = [
        artifact_record(path, directory, encoding="utf-8") for path in paths.values()
    ]
    ref = write_grade(
        directory / "grade.json",
        grader_id=grader_id,
        key=key,
        outputs=outputs,
        task_refs=task_refs,
        bindings=bindings,
        usage=usage,
    )
    return {"source": ref, "key": key}, {"digest": ref["digest"], "usage": usage}


def grade_tasks(
    records,
    entries,
    needed,
    keys,
    *,
    suite,
    host,
    source_root,
    output,
    run_id,
    budget,
    custody_fd,
    on_progress,
):
    declarations = {g["grader_id"]: g for g in suite["graders"]}
    for entry in entries:
        pos = position(entry)
        for grader_id in sorted(needed.get(pos, [])):
            grader = declarations[grader_id]
            if grader["type"] != "deterministic":
                continue
            value = deterministic(
                records[pos],
                entry,
                grader,
                keys[pos]["graders"][grader_id],
                source_root=source_root,
                output=output,
                custody_fd=custody_fd,
            )
            records[pos]["grades"][grader_id] = value
            on_progress(None)
    for grader_id, key, group in batches(entries, needed, declarations, keys):
        value, usage = model(
            records,
            group,
            declarations[grader_id],
            key,
            host=host,
            source_root=source_root,
            output=output,
            run_id=run_id,
            budget=budget,
            custody_fd=custody_fd,
        )
        for entry in group:
            records[position(entry)]["grades"][grader_id] = value
        on_progress(usage)
