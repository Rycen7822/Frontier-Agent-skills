#!/usr/bin/env python3
"""Public entry point for the source-distinct confirmatory-v3 corpus."""

from _model_evolution_confirmatory_v3_builder import main
import sys


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
