#!/usr/bin/env python3
"""Deterministic envelope owner for Software Quality Workflows."""

import sys

sys.dont_write_bytecode = True

from verify_common import run  # noqa: E402


raise SystemExit(run("software-quality-workflows"))
