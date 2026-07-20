#!/usr/bin/env python3
"""Conservative, stdlib-only static triage for an Agent Skill package.

This script inventories the whole package, validates basic SKILL.md structure and
local Markdown links, and surfaces text patterns that require human review. It
is not a security certificate and intentionally avoids executing package code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".jsx", ".sh", ".bash", ".zsh", ".ps1", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css", ".sql",
    ".rb", ".go", ".rs", ".java", ".kt", ".swift", ".r", ".lua", ".pl",
}

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
MAX_COMPACT_ITEMS = 10
MAX_COMPACT_BYTES = 4096
ALLOWED_LINK_SCHEMES = {"http", "https", "mailto"}
WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul", "clock$",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

PATTERNS = [
    (
        "remote-bootstrap-pipeline",
        "critical",
        re.compile(r"\b(?:curl|wget)\b[^\n|]{0,240}\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b", re.I),
        "Downloader output appears to be piped directly to a shell.",
    ),
    (
        "destructive-root-delete",
        "critical",
        re.compile(r"\brm\s+(?:-[A-Za-z]*r[A-Za-z]*f[A-Za-z]*|-[A-Za-z]*f[A-Za-z]*r[A-Za-z]*)\s+/(?:\s|$)", re.I),
        "Command may recursively delete from the filesystem root.",
    ),
    (
        "policy-override-language",
        "high",
        re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|system|developer|user)\s+(?:instructions?|messages?|rules?)\b", re.I),
        "Instruction may attempt to override higher-authority guidance.",
    ),
    (
        "privilege-escalation",
        "high",
        re.compile(r"\b(?:sudo|doas)\b|\bchmod\s+(?:-R\s+)?777\b", re.I),
        "Package requests privilege escalation or broad permissions.",
    ),
    (
        "dynamic-code-execution",
        "medium",
        re.compile(r"\b(?:eval|exec)\s*\(|\bos\.system\s*\(|\bshell\s*=\s*True\b|\bsubprocess\.[A-Za-z_]+\([^\n]*shell\s*=\s*True", re.I),
        "Dynamic or shell-mediated execution needs injection and scope review.",
    ),
    (
        "sensitive-path-or-secret",
        "medium",
        re.compile(r"(?:~?/)?\.(?:ssh|aws|gnupg)(?:/|\\)|\b(?:AWS_SECRET_ACCESS_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN|PRIVATE_KEY)\b", re.I),
        "Text references a sensitive path or secret name; verify necessity and handling.",
    ),
    (
        "persistence-surface",
        "medium",
        re.compile(r"\b(?:crontab|systemctl\s+enable|launchctl|schtasks|startup|autorun)\b|(?:^|[\\/])\.config[\\/](?:autostart|systemd)", re.I),
        "Package may create persistent or scheduled behavior.",
    ),
    (
        "network-upload",
        "medium",
        re.compile(r"\b(?:curl|wget)\b[^\n]{0,180}(?:--upload-file|-T\s|--data-binary|--form|-F\s)|\brequests\.(?:post|put|patch)\s*\(", re.I),
        "Code or instructions may upload data or perform a remote write.",
    ),
    (
        "recursive-delete",
        "medium",
        re.compile(r"\brm\s+(?:-[A-Za-z]*r[A-Za-z]*f[A-Za-z]*|-[A-Za-z]*f[A-Za-z]*r[A-Za-z]*)\b|\bshutil\.rmtree\s*\(", re.I),
        "Recursive deletion requires path ownership and safety review.",
    ),
]

MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
SIMPLE_YAML_FIELD_RE = re.compile(r"^(name|description|version|author|license):\s*(.*?)\s*$", re.M)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"SKILL.md", "Dockerfile", "Makefile"}:
        return True
    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
        if b"\0" in sample:
            return False
        sample.decode("utf-8")
        return True
    except (OSError, UnicodeDecodeError):
        return False


def iter_paths(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()
        current_path = Path(current)
        for name in list(dirs):
            candidate = current_path / name
            if candidate.is_symlink():
                yield candidate
                dirs.remove(name)
        for name in files:
            yield current_path / name


def parse_frontmatter(skill_text: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    match = FRONTMATTER_RE.search(skill_text)
    if not match:
        return {}, ["SKILL.md must begin with YAML frontmatter delimited by --- lines"]
    fields = {key: value.strip().strip('"\'') for key, value in SIMPLE_YAML_FIELD_RE.findall(match.group(1))}
    for required in ("name", "description"):
        if not fields.get(required):
            errors.append(f"SKILL.md frontmatter is missing non-empty {required}")
    return fields, errors


def parse_link_target(raw: str) -> str | None:
    value = raw.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    if " " in value and not value.startswith(("http://", "https://")):
        value = value.split()[0]
    value = unquote(value)
    parsed = urlsplit(value)
    if parsed.scheme or value.startswith(("#", "mailto:", "data:", "{{")):
        return None
    return parsed.path


def audit(root: Path, max_text_bytes: int, max_pattern_hits: int) -> dict[str, Any]:
    root = root.resolve()
    structural_errors: list[str] = []
    findings: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    pattern_counts: Counter[str] = Counter()
    omitted_pattern_hits: Counter[str] = Counter()
    link_graph: dict[str, set[str]] = {}
    text_scan_complete = True
    incomplete_text_files: list[str] = []

    if not root.exists() or not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    skill_path = root / "SKILL.md"
    frontmatter: dict[str, str] = {}
    if not skill_path.is_file():
        structural_errors.append("SKILL.md is missing at package root")
    else:
        try:
            frontmatter, fm_errors = parse_frontmatter(skill_path.read_text(encoding="utf-8"))
            structural_errors.extend(fm_errors)
            declared_name = frontmatter.get("name")
            if declared_name and declared_name != root.name:
                structural_errors.append(
                    f"SKILL.md name {declared_name!r} does not match package directory {root.name!r}"
                )
        except UnicodeDecodeError:
            structural_errors.append("SKILL.md is not valid UTF-8 text")

    for path in iter_paths(root):
        rel = path.relative_to(root).as_posix()
        for component in Path(rel).parts:
            base = component.rstrip(" .").split(".", 1)[0].lower()
            if base in WINDOWS_RESERVED_NAMES:
                structural_errors.append(f"reserved cross-platform path component: {rel}")
            if component != component.strip() or component.endswith(".") or any(ord(char) < 32 for char in component):
                structural_errors.append(f"unsafe or non-portable path component: {rel}")
        try:
            lst = path.lstat()
        except OSError as exc:
            structural_errors.append(f"cannot stat {rel}: {exc}")
            continue

        if stat.S_ISLNK(lst.st_mode):
            raw_target = os.readlink(path)
            resolved_target = (path.parent / raw_target).resolve()
            escapes = not is_within(resolved_target, root)
            broken = not resolved_target.exists()
            inventory.append({
                "path": rel,
                "type": "symlink",
                "target": raw_target,
                "resolved_target": str(resolved_target),
                "escapes_package": escapes,
                "broken": broken,
            })
            if escapes:
                structural_errors.append(f"symlink escapes package: {rel} -> {raw_target}")
                findings.append({
                    "id": f"F-{len(findings)+1:04d}",
                    "severity": "high",
                    "rule": "escaping-symlink",
                    "path": rel,
                    "line": None,
                    "excerpt": raw_target,
                    "message": "Symlink resolves outside the skill package.",
                })
            elif broken:
                structural_errors.append(f"broken symlink: {rel} -> {raw_target}")
                findings.append({
                    "id": f"F-{len(findings)+1:04d}",
                    "severity": "high",
                    "rule": "broken-symlink",
                    "path": rel,
                    "line": None,
                    "excerpt": raw_target,
                    "message": "Symlink target does not exist.",
                })
            continue

        if not stat.S_ISREG(lst.st_mode):
            inventory.append({"path": rel, "type": "other", "mode": oct(lst.st_mode)})
            continue

        text = is_probably_text(path)
        entry: dict[str, Any] = {
            "path": rel,
            "type": "text" if text else "binary",
            "size": lst.st_size,
            "sha256": sha256_file(path),
            "executable": bool(lst.st_mode & 0o111),
        }
        inventory.append(entry)

        if not text:
            severity = "medium" if entry["executable"] else "low"
            findings.append({
                "id": f"F-{len(findings)+1:04d}",
                "severity": severity,
                "rule": "binary-or-opaque-file",
                "path": rel,
                "line": None,
                "excerpt": None,
                "message": "Opaque/binary package content requires format-appropriate review.",
            })
            continue

        if lst.st_size > max_text_bytes:
            text_scan_complete = False
            incomplete_text_files.append(rel)
            structural_errors.append(
                f"text security scan incomplete because file exceeds {max_text_bytes} bytes: {rel}"
            )
            findings.append({
                "id": f"F-{len(findings)+1:04d}",
                "severity": "high",
                "rule": "text-scan-incomplete",
                "path": rel,
                "line": None,
                "excerpt": None,
                "message": f"Text file exceeds scan limit of {max_text_bytes} bytes; audit fails closed.",
            })
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text_scan_complete = False
            incomplete_text_files.append(rel)
            structural_errors.append(f"declared/probable text is not valid UTF-8 and was not scanned: {rel}")
            findings.append({
                "id": f"F-{len(findings)+1:04d}",
                "severity": "high",
                "rule": "non-utf8-text",
                "path": rel,
                "line": None,
                "excerpt": None,
                "message": "File looked textual but is not valid UTF-8; manual review required.",
            })
            continue

        lines = content.splitlines()
        for line_no, line in enumerate(lines, 1):
            for rule, severity, regex, message in PATTERNS:
                if regex.search(line):
                    pattern_counts[rule] += 1
                    if pattern_counts[rule] > max_pattern_hits:
                        omitted_pattern_hits[rule] += 1
                        continue
                    findings.append({
                        "id": f"F-{len(findings)+1:04d}",
                        "severity": severity,
                        "rule": rule,
                        "path": rel,
                        "line": line_no,
                        "excerpt": line.strip()[:300],
                        "message": message,
                    })

        if path.suffix.lower() in {".md", ".markdown"}:
            for match in MD_LINK_RE.finditer(content):
                raw_target = unquote(match.group(1).strip())
                normalized = raw_target[1:-1].strip() if raw_target.startswith("<") and raw_target.endswith(">") else raw_target
                parsed = urlsplit(normalized)
                if parsed.scheme:
                    if parsed.scheme.lower() not in ALLOWED_LINK_SCHEMES:
                        structural_errors.append(
                            f"unsafe Markdown link scheme in {rel}: {parsed.scheme} -> {normalized}"
                        )
                    continue
                target = parse_link_target(match.group(1))
                if target is None or target == "":
                    continue
                link_path = (path.parent / target).resolve()
                if not is_within(link_path, root):
                    structural_errors.append(f"local Markdown link escapes package: {rel} -> {target}")
                elif not link_path.exists():
                    structural_errors.append(f"broken local Markdown link: {rel} -> {target}")
                else:
                    target_rel = link_path.relative_to(root).as_posix()
                    link_graph.setdefault(rel, set()).add(target_rel)

    reachable = {"SKILL.md"}
    pending = ["SKILL.md"]
    while pending:
        source = pending.pop()
        for target in sorted(link_graph.get(source, set())):
            if target not in reachable:
                reachable.add(target)
                if Path(target).suffix.lower() in {".md", ".markdown"}:
                    pending.append(target)
    formal_support = {
        item["path"] for item in inventory
        if item.get("type") in {"text", "binary"}
        and item["path"].split("/", 1)[0] in {"references", "templates", "scripts"}
        and not item["path"].endswith((".pyc", ".pyo"))
    }
    for orphan in sorted(formal_support - reachable):
        structural_errors.append(f"formal support file is unreachable from SKILL.md: {orphan}")

    for rule, omitted in sorted(omitted_pattern_hits.items()):
        if omitted:
            findings.append({
                "id": f"F-{len(findings)+1:04d}",
                "severity": "info",
                "rule": "finding-details-truncated",
                "path": None,
                "line": None,
                "excerpt": rule,
                "message": f"{omitted} additional {rule} matches were counted but not expanded.",
            })

    for finding in findings:
        finding.setdefault("evidence_status", "provisional")
        finding.setdefault("confidence", "medium")
        finding.setdefault("detection_source", "static-heuristic")

    inventory_hash = hashlib.sha256(
        "\n".join(
            f"{item.get('path')}\t{item.get('type')}\t{item.get('sha256','')}\t{item.get('target','')}"
            for item in inventory
        ).encode("utf-8")
    ).hexdigest()
    severity_counts = Counter(item["severity"] for item in findings)

    return {
        "schema_version": 1,
        "package_root": str(root),
        "frontmatter": frontmatter,
        "inventory_hash": inventory_hash,
        "file_count": len(inventory),
        "inventory": inventory,
        "scan": {
            "text_scan_complete": text_scan_complete,
            "incomplete_text_files": sorted(set(incomplete_text_files)),
            "pattern_match_counts": dict(sorted(pattern_counts.items())),
            "omitted_pattern_hit_details": dict(sorted(omitted_pattern_hits.items())),
        },
        "structural_errors": sorted(set(structural_errors)),
        "findings": findings,
        "summary": {
            "structural_error_count": len(set(structural_errors)),
            "text_scan_complete": text_scan_complete,
            "finding_count": len(findings),
            "findings_by_severity": {level: severity_counts.get(level, 0) for level in SEVERITY_RANK},
            "manual_review_required": bool(findings),
            "security_certificate": False,
        },
    }


def write_json(path: str, report: dict[str, Any]) -> None:
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if path == "-":
        sys.stdout.write(payload)
    else:
        Path(path).write_text(payload, encoding="utf-8")


def safe_display(value: object) -> str:
    return "".join(char if ord(char) >= 32 and ord(char) != 127 else "?" for char in str(value))


def finding_sort_key(finding: dict[str, Any]) -> tuple[Any, ...]:
    line = finding.get("line")
    return (
        -SEVERITY_RANK[finding["severity"]],
        str(finding.get("path") or ""),
        line if isinstance(line, int) else -1,
        str(finding.get("rule") or ""),
        str(finding.get("id") or ""),
    )


def compact_status(report: dict[str, Any]) -> str:
    summary = report["summary"]
    errors = sorted(set(report["structural_errors"]))
    findings = sorted(report["findings"], key=finding_sort_key)
    triage = "structural_invalid" if errors else "review_required" if findings else "clean"

    def render(error_limit: int, finding_limit: int) -> str:
        lines = [
            f"Package: {safe_display(Path(report['package_root']).name)}",
            f"Triage status: {triage}",
            f"Files: {report['file_count']} | Inventory SHA-256: {report['inventory_hash']}",
            f"Structural errors: {summary['structural_error_count']}",
            f"Text scan complete: {'yes' if summary['text_scan_complete'] else 'no'}",
            "Findings: " + ", ".join(
                f"{key}={value}" for key, value in summary["findings_by_severity"].items()
            ),
            "Manual review required: " + ("yes" if summary["manual_review_required"] else "no"),
            "This output is triage, not a security certificate.",
        ]
        lines.extend(f"ERROR {safe_display(error)}" for error in errors[:error_limit])
        lines.append(f"ERRORS shown={min(error_limit, len(errors))} omitted={max(0, len(errors) - error_limit)}")
        for finding in findings[:finding_limit]:
            path = safe_display(finding.get("path") or "<package>")
            line = finding.get("line")
            locator = f"{path}:{line}" if isinstance(line, int) else path
            lines.append(
                "FINDING "
                f"{safe_display(finding['severity'])} {safe_display(finding['id'])} "
                f"{safe_display(finding['rule'])} {locator}"
            )
        lines.append(
            f"FINDINGS shown={min(finding_limit, len(findings))} "
            f"omitted={max(0, len(findings) - finding_limit)}"
        )
        return "\n".join(lines) + "\n"

    error_limit = min(MAX_COMPACT_ITEMS, len(errors))
    finding_limit = min(MAX_COMPACT_ITEMS, len(findings))
    payload = render(error_limit, finding_limit)
    while len(payload.encode("utf-8")) > MAX_COMPACT_BYTES and (error_limit or finding_limit):
        if finding_limit:
            finding_limit -= 1
        else:
            error_limit -= 1
        payload = render(error_limit, finding_limit)
    if len(payload.encode("utf-8")) > MAX_COMPACT_BYTES:
        raise ValueError("compact audit summary exceeds output bound")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir", help="Path to the skill package root")
    parser.add_argument("--json", metavar="PATH", help="Write the full JSON report; use - for stdout")
    parser.add_argument("--max-text-bytes", type=int, default=2_000_000, help="Maximum bytes scanned per text file")
    parser.add_argument("--max-pattern-hits", type=int, default=20, help="Maximum findings retained per text pattern")
    parser.add_argument(
        "--fail-on",
        choices=["none", "critical", "high", "medium", "low", "info"],
        default="none",
        help="Return exit 1 when a finding at or above this severity exists; structural errors always fail",
    )
    args = parser.parse_args()

    if args.max_text_bytes <= 0 or args.max_pattern_hits <= 0:
        parser.error("scan limits must be positive")

    try:
        report = audit(Path(args.skill_dir), args.max_text_bytes, args.max_pattern_hits)
    except (OSError, ValueError) as exc:
        print(f"audit error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        try:
            write_json(args.json, report)
        except OSError as exc:
            print(f"audit output error: {exc}", file=sys.stderr)
            return 2

    try:
        status = compact_status(report)
    except ValueError as exc:
        print(f"audit output error: {exc}", file=sys.stderr)
        return 2
    status_stream = sys.stderr if args.json == "-" or report["structural_errors"] else sys.stdout
    status_stream.write(status)

    if report["structural_errors"]:
        return 1

    if args.fail_on != "none":
        threshold = SEVERITY_RANK[args.fail_on]
        if any(SEVERITY_RANK[item["severity"]] >= threshold for item in report["findings"]):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
