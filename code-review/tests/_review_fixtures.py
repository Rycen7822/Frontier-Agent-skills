"""Fixture builders for the review helper tests: real Git repos and hand-authored packets.

Only test code lives here. Production modules are imported from the sibling
``scripts`` directory so the tests exercise the shipped files.
"""

from __future__ import annotations

import hashlib
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

FIXTURE_ENV = {
    "GIT_AUTHOR_NAME": "FAS Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "FAS Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(FIXTURE_ENV)
    return env


def git(
    repo: Path, *args: str, check: bool = True, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=git_env(),
        capture_output=True,
        check=check,
        input=input_bytes,
    )


def init_repo(root: Path) -> Path:
    repo = Path(root) / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "FAS Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "tag.gpgsign", "false")
    return repo


def write_file(repo: Path, relative: str, content: str | bytes) -> Path:
    path = Path(repo) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content
    path.write_bytes(data)
    return path


def commit_files(repo: Path, files: dict[str, str | bytes], message: str = "fixture") -> str:
    for relative, content in files.items():
        if content is None:
            path = Path(repo) / relative
            if path.exists():
                path.unlink()
            continue
        write_file(repo, relative, content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.decode("ascii").strip()


def head_oid(repo: Path, revision: str = "HEAD") -> str:
    return git(repo, "rev-parse", revision).stdout.decode("ascii").strip()


_ITEMS_ORDER = ("commit", "range", "index", "worktree", "untracked", "snapshot")


def _source_sort_key(source: dict[str, Any]) -> tuple[str, str, bytes, str]:
    return (
        source["origin"],
        source.get("revision") or "",
        source["path"].encode("utf-8"),
        source.get("git_oid") or "",
    )


def _item_sort_key(item: dict[str, Any]) -> tuple[int, bytes]:
    return (_ITEMS_ORDER.index(item["layer"]), item["path"].encode("utf-8"))


def hand_packet(
    root: Path,
    sources: list[dict[str, Any]],
    items: list[dict[str, Any]],
    *,
    packet_name: str = "packet",
    mode: str = "workspace",
    request: dict[str, Any] | None = None,
    resolved: dict[str, Any] | None = None,
    observation: str | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Write a packet from explicit source and item descriptions.

    Each source entry uses ``name`` for item references and optional
    ``payload`` bytes; ``line_count``/``size_bytes`` overrides exist so tests can
    build deliberately inconsistent metadata.
    """
    packet = Path(root) / packet_name
    packet.mkdir(mode=0o700)
    objects = packet / "objects"
    objects.mkdir(mode=0o700)

    ordered = sorted(sources, key=_source_sort_key)
    by_name: dict[str, str] = {}
    written: set[str] = set()
    scope_sources: list[dict[str, Any]] = []
    for index, source in enumerate(ordered, start=1):
        source_id = f"S-{index:06d}"
        by_name[source["name"]] = source_id
        availability = source["availability"]
        payload = source.get("payload")
        digest = None
        size = source.get("size_bytes")
        lines = None
        if availability in review_record.CAPTURED_AVAILABILITY:
            if payload is None:
                raise ValueError(f"source {source['name']} needs payload bytes")
            digest = review_record.sha256_digest(payload)
            size = len(payload) if size is None else size
            lines = (
                review_record.count_lines(payload)
                if availability == review_record.TEXT_AVAILABILITY
                else None
            )
            if source.get("line_count") is not None:
                lines = source["line_count"]
            blob = objects / f"{digest[7:]}.blob"
            if digest not in written:
                blob.write_bytes(payload)
                written.add(digest)
        elif size is None:
            size = 0
        scope_sources.append(
            {
                "id": source_id,
                "path": source["path"],
                "origin": source["origin"],
                "revision": source.get("revision"),
                "git_oid": source.get("git_oid"),
                "git_mode": source.get("git_mode"),
                "availability": availability,
                "sha256": digest,
                "size_bytes": size,
                "line_count": lines,
            }
        )

    ordered_items = sorted(items, key=_item_sort_key)
    scope_items: list[dict[str, Any]] = []
    for index, item in enumerate(ordered_items, start=1):
        before = item.get("before")
        after = item.get("after")
        scope_items.append(
            {
                "id": f"I-{index:06d}",
                "layer": item["layer"],
                "status": item["status"],
                "path": item["path"],
                "before": None if before is None else by_name[before],
                "after": None if after is None else by_name[after],
            }
        )

    if request is None:
        request = {
            "paths": ["."],
            "context_paths": [],
            "base": None,
            "head": None,
            "commit": None,
            "revision": None,
        }
    if resolved is None:
        resolved = {
            "object_format": "sha1",
            "base_oid": None,
            "head_oid": None,
            "comparison_base_oid": None,
        }
    if observation is None:
        observation = (
            "bounded_double_observation"
            if mode in ("workspace",) or request.get("revision") == "WORKTREE"
            else "immutable_commits"
        )
    scope = {
        "schema_version": review_record.SCOPE_SCHEMA_VERSION,
        "mode": mode,
        "request": request,
        "resolved": resolved,
        "observation": observation,
        "items": scope_items,
        "sources": scope_sources,
        "limitations": list(limitations or []),
    }
    scope_path = packet / "scope.json"
    scope_bytes = (json.dumps(scope, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    scope_path.write_bytes(scope_bytes)
    view = packet_view(packet)
    view["source_ids"] = by_name
    return view


def packet_view(packet: Path) -> dict[str, Any]:
    """Read a captured packet directory into the shape ``hand_packet`` returns.

    ``source_ids`` is keyed by source path, which stays unambiguous for the
    single-layer sources the CLI tests reference.
    """
    scope_bytes = (Path(packet) / review_record.SCOPE_FILE).read_bytes()
    scope = json.loads(scope_bytes)
    return {
        "packet": Path(packet),
        "scope": scope,
        "scope_bytes": scope_bytes,
        "scope_sha256": review_record.sha256_digest(scope_bytes),
        "source_ids": {source["path"]: source["id"] for source in scope["sources"]},
        "item_ids": {item["path"]: item["id"] for item in scope["items"]},
    }


def anchor_packet(
    root: Path,
    payload: bytes,
    *,
    path: str = "src/module.py",
    availability: str = "text",
    packet_name: str = "packet",
    layer: str = "worktree",
    status: str = "A",
) -> dict[str, Any]:
    """Packet with one source and one item, for location and evidence tests."""
    return hand_packet(
        root,
        sources=[
            {
                "name": "main",
                "path": path,
                "origin": "worktree",
                "availability": availability,
                "payload": payload,
            }
        ],
        items=[{"layer": layer, "status": status, "path": path, "after": "main"}],
        packet_name=packet_name,
    )


def evidence(
    packet: dict[str, Any],
    *,
    snippet: str | None,
    start_line: int | None = None,
    end_line: int | None = None,
    source_name: str = "main",
) -> dict[str, Any]:
    return {
        "source_id": packet["source_ids"][source_name],
        "start_line": start_line,
        "end_line": end_line,
        "snippet": snippet,
    }


def hand_record(
    packet: dict[str, Any],
    *,
    coverage: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    concerns: list[dict[str, Any]] | None = None,
    verification: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    if coverage is None:
        coverage = [
            {"item_id": item["id"], "status": "reviewed", "reason": None}
            for item in packet["scope"]["items"]
        ]
    return {
        "schema_version": review_record.RECORD_SCHEMA_VERSION,
        "scope_ref": "scope.json",
        "scope_sha256": packet["scope_sha256"],
        "coverage": coverage,
        "findings": list(findings or []),
        "concerns": list(concerns or []),
        "verification": list(verification or []),
        "limitations": list(limitations or []),
    }


def finding(
    packet: dict[str, Any],
    *,
    finding_id: str = "F-1",
    evidence_entries: list[dict[str, Any]],
    severity: str = "high",
    summary: str = "The change drops an ownership check.",
    relation: str = "introduced",
    fix: str | None = "Restore the ownership check.",
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "summary": summary,
        "relation": relation,
        "trigger": "A caller requests an object owned by another account.",
        "impact": "The request returns another account's payload.",
        "item_ids": [item["id"] for item in packet["scope"]["items"]],
        "evidence": evidence_entries,
        "fix": fix,
    }


def write_json(path: Path, value: Any) -> Path:
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return path


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def run_cli(argv: list[str]) -> tuple[int, dict[str, Any] | None]:
    """Call the review CLI in-process and return (exit code, parsed stdout JSON)."""
    import contextlib
    import io

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import review_support

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = review_support.main(argv)
    text = buffer.getvalue().strip()
    payload = json.loads(text) if text else None
    return code, payload
