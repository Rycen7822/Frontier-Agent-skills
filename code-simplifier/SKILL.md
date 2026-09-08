---
name: code-simplifier
description: Simplify selected code for clarity and maintainability while preserving intended behavior.
license: Apache-2.0
metadata:
  version: 1.0.1
  hosts: [codex, hermes-agent]
---

# Code Simplifier

Use the user-selected component, files or change; default to recently modified code only when no wider scope is named. Read relevant implementation and consumers, preserve user work and follow repository conventions.

Preserve intended outputs, side effects, errors and compatibility. Explicitly requested removal or behavior changes follow the user's goal; resolve consequential uncertainty before deleting the affected behavior.

Reduce what a reader must trace: unnecessary indirection, scattered invariants, redundant branches, duplicated transformations and hidden mutable state. Prefer direct control flow, cohesive ownership and fewer representations. Check relevant consumers, including dynamic or generated use, before declaring code dead.

Delete unnecessary abstractions instead of wrapping them again. Consolidate shared behavior without coupling unrelated cases. Clarity matters more than line count; dense expressions and tiny forwarding functions can make code harder to follow. Keep comments explaining non-obvious reasons, contracts or risks, and preserve licensing.

Complete the coherent simplification, then use the smallest check that resolves actual uncertainty. Reuse valid evidence; obvious semantic no-ops need no new test or model evaluation. Keep unique behavioral protection and remove duplicates or retired expectations. Report the meaningful change and verification limits without adding a mandatory cleanup phase to unrelated tasks.
