#!/usr/bin/env python3
"""Deterministic envelope owner for Skill Evaluator."""

import sys

sys.dont_write_bytecode = True

from verify_common import run  # noqa: E402


raise SystemExit(run("skill-evaluator"))
