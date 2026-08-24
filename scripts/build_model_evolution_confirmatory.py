#!/usr/bin/env python3
"""Public entry point for the versioned confirmatory corpus builder."""

from _model_evolution_confirmatory_builder import main
import sys


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
