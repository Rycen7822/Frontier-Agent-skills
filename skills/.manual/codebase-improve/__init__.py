"""Hermes user command; the skill is never registered in the model catalog."""

from pathlib import Path


def register(api):
    def invoke(arguments: str):
        root = Path(__file__).resolve().parent
        instructions = (root / "SKILL.md").read_text(encoding="utf-8")
        message = (
            "[The user explicitly invoked codebase-improve.]\n"
            f"Skill directory: {root}\n"
            "Resolve the skill's references relative to that directory.\n\n"
            f"{instructions}\n\nUser request:\n{arguments.strip()}"
        )
        if not api.inject_message(message, role="user"):
            return "Codebase Improve could not load into an attached Hermes CLI session."
        return "Codebase Improve queued for this session."

    api.register_command(
        "codebase-improve",
        invoke,
        description="Review and improve codebase architecture",
        args_hint="<request>",
    )
