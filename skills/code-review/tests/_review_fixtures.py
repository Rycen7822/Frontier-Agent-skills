"""Minimal fixtures: real Git repositories and hand-authored review packets.

Only test code lives here; the shipped modules are imported from the sibling
``scripts`` directory so the tests exercise the shipped files.
"""

from __future__ import annotations

import contextlib
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _review_record as review_record  # noqa: E402
import review_support  # noqa: E402

# A pinned identity and no user configuration, so captured OIDs are reproducible.
GIT_ENV = {"GIT_AUTHOR_NAME": "FAS Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "FAS Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run one Git command with a pinned identity and no user configuration."""
    command = ["git", "-C", str(repo), *args]
    return subprocess.run(command, env={**os.environ, **GIT_ENV}, capture_output=True, check=check)


def init_repo(root: Path, *, name: str = "repo") -> Path:
    repo = Path(root) / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "FAS Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    return repo


def write(repo: Path, relative: str, content: str | bytes) -> Path:
    path = Path(repo) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def commit(repo: Path, files: dict[str, str | bytes | None], message: str = "fixture") -> str:
    """Stage the given files (``None`` deletes one), commit them, and return the new OID."""
    for relative, content in files.items():
        if content is None:
            (Path(repo) / relative).unlink(missing_ok=True)
        else:
            write(repo, relative, content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return head(repo)


def head(repo: Path, revision: str = "HEAD") -> str:
    return git(repo, "rev-parse", revision).stdout.decode("ascii").strip()


def digest(raw: bytes) -> str:
    """The digest of real bytes, computed independently of the shipped code."""
    return "sha256:" + sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> Path:
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return Path(path)


def run_cli(argv: list[str]) -> tuple[int, dict[str, Any] | None]:
    """Call the shipped CLI in process and return its exit code and JSON summary."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = review_support.main(argv)
    text = buffer.getvalue().strip()
    return code, (json.loads(text) if text else None)


def scope_cli(repo: Path, output: Path, *arguments: str) -> tuple[int, dict | None, Path]:
    """Assemble one scope call; the caller owns the output path and assertions."""
    code, payload = run_cli(["scope", "--repo", str(repo), *arguments, "--output", str(output)])
    return code, payload, Path(output)


def check_cli(
    repo: Path, packet: Path, record: Path, output: Path
) -> tuple[int, dict | None, Path]:
    """Assemble one check call; the caller owns the output path and assertions."""
    arguments = ["check", "--repo", str(repo), "--packet", str(packet), "--output", str(output)]
    code, payload = run_cli([*arguments, "--record", str(record)])
    return code, payload, Path(output)


def scope_of(packet: Path) -> dict[str, Any]:
    return json.loads((Path(packet) / "scope.json").read_bytes())


def objects_of(packet: Path) -> dict[str, bytes]:
    """Captured blobs by file name, so a test can compare real bytes."""
    return {path.name: path.read_bytes() for path in (Path(packet) / "objects").iterdir()}


def payload_of(packet: Path, source: dict[str, Any]) -> bytes:
    """The captured bytes one source records, addressed by its own digest."""
    return objects_of(packet)[source["sha256"][7:] + ".blob"]


def items_of(scope: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Items keyed by layer and path, because one path can appear in two layers."""
    return {(entry["layer"], entry["path"]): entry for entry in scope["items"]}


def sources_of(scope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {source["id"]: source for source in scope["sources"]}


def source_id(view: dict[str, Any], path: str, origin: str = "worktree") -> str:
    """Select the one source id for a path and origin, keeping same-path layers apart."""
    found = [source["id"] for source in view["scope"]["sources"]
        if source["path"] == path and source["origin"] == origin
    ]
    if len(found) != 1:
        raise AssertionError(f"expected one {origin} source for {path}, found {found}")
    return found[0]


def packet_view(packet: Path) -> dict[str, Any]:
    """Read a captured packet into the shape ``hand_packet`` returns."""
    scope_bytes = (Path(packet) / "scope.json").read_bytes()
    return {"packet": Path(packet), "scope": json.loads(scope_bytes), "scope_bytes": scope_bytes,
        "scope_sha256": digest(scope_bytes)}


def text_source(name: str, path: str, payload: bytes, **extra: Any) -> dict[str, Any]:
    """A captured regular file whose bytes are text."""
    return {"origin": "worktree", "availability": "text", "git_mode": "100644",
            "name": name, "path": path, "payload": payload, **extra}


def symlink_source(name: str, path: str, payload: bytes, **extra: Any) -> dict[str, Any]:
    """A captured symlink whose recorded bytes are its target string."""
    return {"origin": "worktree", "availability": "symlink", "git_mode": "120000",
            "name": name, "path": path, "payload": payload, **extra}


def item(
    layer: str, status: str, path: str, *, before: str | None = None, after: str | None = None
) -> dict[str, Any]:
    return {"layer": layer, "status": status, "path": path, "before": before, "after": after}


def coverage_entry(item_id: str, status: str, reason: str | None = None) -> dict[str, Any]:
    return {"item_id": item_id, "status": status, "reason": reason}


def hand_packet(
    root: Path, sources: list[dict[str, Any]], items: list[dict[str, Any]], *, name: str = "packet",
    mode: str = "workspace", request: dict[str, Any] | None = None,
    resolved: dict[str, Any] | None = None, observation: str | None = None,
    limitations: list[str] | None = None) -> dict[str, Any]:
    """Write a packet holding exactly the given bytes, in the order given.

    A captured source needs ``payload`` bytes; an item names its ``before`` and
    ``after`` sources by ``name``. Nothing is reordered here, so a test that
    depends on the recorded order states it explicitly.
    """
    packet = Path(root) / name
    (packet / "objects").mkdir(parents=True, mode=0o700)
    by_name: dict[str, str] = {}
    scope_sources: list[dict[str, Any]] = []
    written: set[str] = set()
    for index, source in enumerate(sources, start=1):
        by_name[source["name"]] = f"S-{index:06d}"
        availability, payload = source["availability"], source.get("payload")
        captured = availability in review_record.CAPTURED_AVAILABILITY
        assert not captured or payload is not None, f"{source['name']} needs payload bytes"
        raw_digest = digest(payload) if captured else None
        line_count = source.get("line_count")
        if line_count is None and availability == review_record.TEXT_AVAILABILITY:
            breaks = payload.count(b"\n")
            line_count = 0 if not payload else breaks + (0 if payload.endswith(b"\n") else 1)
        if captured and raw_digest not in written:
            (packet / "objects" / f"{raw_digest[7:]}.blob").write_bytes(payload)
            written.add(raw_digest)
        scope_sources.append({"id": by_name[source["name"]],
            "path": source["path"], "origin": source["origin"],
            "revision": source.get("revision"), "git_oid": source.get("git_oid"),
            "git_mode": source.get("git_mode"), "availability": availability,
            "sha256": raw_digest, "line_count": line_count,
            "size_bytes": len(payload) if captured else source.get("size_bytes")})
    scope_items = [{"id": f"I-{index:06d}", "layer": entry["layer"], "status": entry["status"],
         "path": entry["path"],
         "before": None if entry.get("before") is None else by_name[entry["before"]],
         "after": None if entry.get("after") is None else by_name[entry["after"]]}
        for index, entry in enumerate(items, start=1)
    ]
    request = request or {"paths": ["."], "context_paths": [], "base": None, "head": None,
                          "commit": None, "revision": None}
    resolved = resolved or {"object_format": "sha1", "base_oid": None, "head_oid": None,
                            "comparison_base_oid": None}
    if observation is None:
        frozen = mode in ("commit", "range") or request["revision"] not in (None, "WORKTREE")
        observation = "immutable_commits" if frozen else "bounded_double_observation"
    scope = {"schema_version": "fas-review-scope/1", "mode": mode, "request": request,
             "resolved": resolved, "observation": observation, "items": scope_items,
             "sources": scope_sources, "limitations": list(limitations or [])}
    scope_bytes = (json.dumps(scope, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (packet / "scope.json").write_bytes(scope_bytes)
    return {"packet": packet, "scope": scope, "scope_bytes": scope_bytes,
            "scope_sha256": digest(scope_bytes)}


def coverage(view: dict[str, Any], *statuses: str) -> list[dict[str, Any]]:
    """Cover the scope items in order; one status per item, ``reviewed`` by default."""
    reasons = {"reviewed": None, "partial": "only the changed lines were reviewed",
               "not_reviewed": "the source needs a manual pass"}
    chosen = list(statuses) or ["reviewed"] * len(view["scope"]["items"])
    return [coverage_entry(entry["id"], status, reasons[status])
            for entry, status in zip(view["scope"]["items"], chosen)]


def evidence(
    view: dict[str, Any], *, path: str, snippet: str | None = None, start_line: int | None = None,
    end_line: int | None = None, origin: str = "worktree") -> dict[str, Any]:
    return {"source_id": source_id(view, path, origin), "start_line": start_line,
            "end_line": end_line, "snippet": snippet}


def finding(
    view: dict[str, Any], evidence_entries: list[dict[str, Any]], *, finding_id: str = "F-1",
    severity: str = "high", item_ids: list[str] | None = None) -> dict[str, Any]:
    return {"id": finding_id, "severity": severity, "relation": "introduced",
        "summary": "The change drops an ownership check.",
        "trigger": "A caller asks for an object owned by another account.",
        "impact": "The request returns another account's payload.",
        "item_ids": item_ids or [entry["id"] for entry in view["scope"]["items"]],
        "evidence": evidence_entries, "fix": "Restore the ownership check."}


def concern(view: dict[str, Any], concern_id: str = "C-1") -> dict[str, Any]:
    return {"id": concern_id, "summary": "The retry path may still lose a write.",
            "item_ids": [entry["id"] for entry in view["scope"]["items"]],
            "missing_evidence": "No failure-injection run exists yet.",
            "impact_if_true": "A write can be lost without an error."}


def verification(verification_id: str = "V-1", status: str = "passed") -> dict[str, Any]:
    return {"id": verification_id, "label": "the fixture suite", "status": status,
            "observation": "The suite finished."}


def hand_record(
    view: dict[str, Any], *, coverage_entries: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None, concerns: list[dict[str, Any]] | None = None,
    verification_entries: list[dict[str, Any]] | None = None, limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {"schema_version": "fas-review-record/1", "scope_ref": "scope.json",
        "scope_sha256": view["scope_sha256"],
        "coverage": coverage(view) if coverage_entries is None else coverage_entries,
        "findings": list(findings or []), "concerns": list(concerns or []),
        "verification": list(verification_entries or []), "limitations": list(limitations or [])}


def validate(view: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Run the shipped validator over a hand-authored packet."""
    return review_record.validate_record(
        view["packet"], view["scope"], record, scope_bytes=view["scope_bytes"])


def report_for(
    view: dict[str, Any], record: dict[str, Any], freshness: str = "captured_inputs_match"
) -> dict[str, Any]:
    """Validate one record and merge it with the stated freshness."""
    freshness_detail = {"status": freshness, "changed_paths": []}
    return review_record.finish_report(validate(view, record), freshness_detail)
