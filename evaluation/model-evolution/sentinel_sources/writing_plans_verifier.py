#!/usr/bin/env python3
"""Deterministic envelope owner for Writing Plans."""

import sys

sys.dont_write_bytecode = True

from verify_common import run  # noqa: E402


raise SystemExit(run("writing-plans"))
