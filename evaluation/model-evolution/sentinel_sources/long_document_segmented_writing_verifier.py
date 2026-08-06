#!/usr/bin/env python3
"""Deterministic envelope owner for Long Document Segmented Writing."""

import sys

sys.dont_write_bytecode = True

from verify_common import run  # noqa: E402


raise SystemExit(run("long-document-segmented-writing"))
