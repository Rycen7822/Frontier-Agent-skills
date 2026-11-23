"""Protect user-only Hermes commands without requiring a live agent."""

import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
USER_COMMANDS = ("clean-code-comments", "codebase-improve", "improve-docs")


class UserCommandAPI:
    """Only user commands and message injection exist on this test surface."""

    def __init__(self, accepted=True):
        self.commands = {}
        self.messages = []
        self.accepted = accepted

    def register_command(self, name, handler, **metadata):
        self.commands[name] = handler

    def inject_message(self, content, role):
        self.messages.append((content, role))
        return self.accepted


def load_adapter(root):
    spec = importlib.util.spec_from_file_location("fas_user_command", root / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExplicitSkillCommands(unittest.TestCase):
    def test_registration_neither_reads_instructions_nor_injects_context(self):
        for name in USER_COMMANDS:
            with self.subTest(command=name):
                api = UserCommandAPI()
                with patch.object(Path, "read_text", side_effect=AssertionError("Premature skill read")):
                    load_adapter(ROOT / name).register(api)
                self.assertEqual({name}, set(api.commands))
                self.assertEqual([], api.messages)

    def test_explicit_command_uses_installed_bytes_and_reference_root(self):
        for name in USER_COMMANDS:
            with self.subTest(command=name), tempfile.TemporaryDirectory() as directory:
                installed = Path(directory) / "plugin"
                shutil.copytree(ROOT / name, installed)
                instructions = (installed / "SKILL.md").read_text()
                request = "Audit src/tasks only; do not edit product code."
                api = UserCommandAPI()
                load_adapter(installed).register(api)
                self.assertEqual([], api.messages)
                api.commands[name](request)
                self.assertEqual(1, len(api.messages))
                message, role = api.messages[0]
                self.assertEqual("user", role)
                self.assertIn(instructions, message)
                self.assertIn(str(installed.resolve()), message)
                self.assertTrue(message.endswith(request))
                (installed / "SKILL.md").unlink()
                with self.assertRaises(FileNotFoundError):
                    api.commands[name](request)
                self.assertEqual(1, len(api.messages), "Missing instructions must not queue a stale turn")


if __name__ == "__main__":
    unittest.main()
