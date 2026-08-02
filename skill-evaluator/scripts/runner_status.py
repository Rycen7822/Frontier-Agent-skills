"""Pure bounded status projection for the Skill Evaluator runner."""

from __future__ import annotations

from typing import Any


def project_runner_status(
    *,
    plan: dict[str, Any],
    selected: list[dict[str, Any]],
    execute_entries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    entry_states: dict[str, dict[str, Any]],
    active_attempts: list[dict[str, Any]],
    recoverable_attempts: list[dict[str, Any]],
    invalid_attempts: int,
) -> dict[str, Any]:
    """Project verified runner facts without reading or writing state."""
    selected_ids = {entry["entry_id"] for entry in execute_entries}
    remaining = [
        entry for entry in execute_entries
        if not entry_states[entry["entry_id"]]["complete"]
    ]
    next_entry = remaining[0] if remaining else None
    next_pass_attempts = 0
    for entry in execute_entries:
        state = entry_states[entry["entry_id"]]
        if state["complete"]:
            continue
        next_pass_attempts += state["next_pass_new_attempts"]
        if state["next_pass_new_attempts"] == 0:
            break
    return {
        "schema_version": "runner-status/1",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "selected_entries": len(selected),
        "execute_entries": len(execute_entries),
        "indexed_attempts": sum(
            row["entry_id"] in selected_ids for row in rows
        ),
        "completed_entries": sum(
            state["complete"] for state in entry_states.values()
        ),
        "invalid_attempts": invalid_attempts,
        "remaining_entries": len(remaining),
        "active_attempts": active_attempts,
        "recoverable_attempts": recoverable_attempts,
        "next_entry_id": next_entry["entry_id"] if next_entry else None,
        "next_attempt": (
            entry_states[next_entry["entry_id"]]["next_attempt"]
            if next_entry else None
        ),
        "next_pass_new_attempts": next_pass_attempts,
        "worst_case_remaining_attempts": sum(
            state["worst_case_remaining_attempts"]
            for state in entry_states.values()
        ),
        "execute_case_request_ceiling": sum(
            state["worst_case_remaining_attempts"]
            for state in entry_states.values()
        ),
        "model_grade_request_ceiling": sum(
            state["worst_case_remaining_attempts"]
            * state["model_grade_requests_per_attempt"]
            for state in entry_states.values()
        ),
    }
