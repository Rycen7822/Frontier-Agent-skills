"""Hermes user command; the skill is never registered in the model catalog."""

from pathlib import Path


def register(api):
    def invoke(arguments: str):
        root = Path(__file__).resolve().parent
        instructions = (root / "SKILL.md").read_text(encoding="utf-8")
        message = (
            "[The user explicitly invoked improve-docs.]\n"
            f"Skill directory: {root}\n"
            "Resolve the skill's files relative to that directory.\n"
            f"{instructions}\n\nUser request:\n{arguments.strip()}"
        )
        if not api.inject_message(message, role="user"):
            return "Improve Docs could not load into an attached Hermes CLI session."
        return "Improve Docs queued for this session."

    api.register_command(
        "improve-docs",
        invoke,
        description="Write and improve technical documentation",
        args_hint="<request>",
    )
