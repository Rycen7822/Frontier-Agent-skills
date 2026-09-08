#!/usr/bin/env python3
"""Read a bounded, source-located excerpt from one selected Codex rollout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def message_text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


def project(record, view):
    kind, payload = record.get("type"), record.get("payload")
    if not isinstance(payload, dict):
        return None
    subtype = payload.get("type")
    if kind == "response_item" and subtype == "message":
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            return None
        if view == "index" and role != "user" and payload.get("phase") != "final":
            return None
        return {"kind": role, "text": message_text(payload.get("content"))}
    if kind == "event_msg" and subtype == "turn_aborted":
        return {"kind": subtype, "text": json.dumps(payload, ensure_ascii=False)}
    if view == "index":
        return None
    if kind == "turn_context":
        fields = {key: payload[key] for key in ("cwd", "model", "effort") if key in payload}
        return {"kind": kind, "text": json.dumps(fields, ensure_ascii=False)}
    if kind == "response_item" and subtype in {
        "function_call", "custom_tool_call", "local_shell_call",
        "function_call_output", "custom_tool_call_output",
    }:
        fields = {
            key: payload[key]
            for key in ("name", "call_id", "arguments", "input", "action", "output")
            if key in payload
        }
        return {"kind": subtype, "text": json.dumps(fields, ensure_ascii=False)}
    if kind == "event_msg" and subtype == "item_completed":
        item = payload.get("item")
        if isinstance(item, dict) and item.get("type") in {"CommandExecution", "FileChange"}:
            return {"kind": item["type"], "text": json.dumps(item, ensure_ascii=False)}
    return None


def inspect(path, *, view="index", start_line=1, end_line=None, match="", max_events=20,
            max_chars=12000, event_chars=1200):
    if view not in {"index", "events"} or min(start_line, max_events, max_chars, event_chars) < 1:
        raise ValueError("view must be index or events; limits and start_line must be positive")
    if end_line is not None and end_line < start_line:
        raise ValueError("end_line must not precede start_line")
    path = path.expanduser().resolve(strict=True)
    result = {"source": str(path), "view": view, "start_line": start_line, "end_line": end_line,
              "session": {}, "events": [], "next_line": None}
    remaining = max_chars
    with path.open(encoding="utf-8") as stream:
        for line, raw in enumerate(stream, 1):
            if end_line is not None and line > end_line:
                break
            if line != 1 and line < start_line:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"expected an object at {path}:{line}")
            if line == 1:
                meta = record.get("payload")
                if record.get("type") != "session_meta" or not isinstance(meta, dict):
                    raise ValueError("expected a Codex rollout beginning with session_meta")
                result["session"] = {key: meta.get(key) for key in ("id", "cwd", "timestamp")}
                continue
            event = project(record, view)
            if event is None or (match and match not in event["text"]):
                continue
            text = event["text"]
            limit = min(event_chars, remaining)
            offset = max(0, text.find(match) - min(120, limit // 4)) if match else 0
            excerpt = text[offset:offset + limit]
            result["events"].append({
                "line": line, "kind": event["kind"], "text": excerpt,
                "text_offset": offset, "omitted_chars": len(text) - len(excerpt),
            })
            remaining -= len(excerpt)
            if len(result["events"]) >= max_events or remaining == 0:
                result["next_line"] = line + 1 if end_line is None or line < end_line else None
                break
        else:
            if not result["session"]:
                raise ValueError("empty rollout")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", type=Path, help="one explicit Codex rollout JSONL path")
    parser.add_argument("--view", choices=("index", "events"), default="index")
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--end-line", type=int, help="last source line in the selected episode")
    parser.add_argument("--match", default="", help="case-sensitive text filter on projected events")
    parser.add_argument("--max-events", type=int, default=20)
    parser.add_argument("--max-chars", type=int, default=12000, help="total displayed event text budget")
    parser.add_argument("--event-chars", type=int, default=1200, help="displayed characters per event")
    args = parser.parse_args(argv)
    try:
        result = inspect(
            args.trajectory, view=args.view, start_line=args.start_line, end_line=args.end_line, match=args.match,
            max_events=args.max_events, max_chars=args.max_chars, event_chars=args.event_chars,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
