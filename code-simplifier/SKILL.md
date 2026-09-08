---
name: code-simplifier
description: "Simplify, clean up, or refactor selected code for clarity and maintainability while preserving intended behavior. Use the user-named scope, or the current diff by default; not for feature changes or performance redesigns."
license: Apache-2.0
metadata:
  version: 1.0.0
  hosts: [codex, hermes-agent]
---

# Code Simplifier

Simplify the user-selected component, files or change. When no wider scope is named, focus on recently modified code. Read the relevant implementation and consumers first, preserve user work, and follow the repository's actual conventions rather than imposing a language or framework style.

Preserve intended outputs, side effects, errors and compatibility. Explicitly requested removal or behavior change follows the user's goal; do not silently treat it as an equivalent refactor. Resolve a consequential uncertainty before deleting the affected behavior.

Reduce what a reader must trace and remember: unnecessary indirection, scattered invariants, redundant branches, duplicated transformations and hidden mutable state. Prefer direct names and control flow, cohesive ownership and fewer representations. Remove dead code only after checking relevant consumers, including dynamic or generated use when applicable.

Prefer deleting an unnecessary abstraction to adding another wrapper. Consolidate truly shared behavior without coupling unrelated cases. Clear code matters more than fewer lines: avoid nested ternaries, dense expressions and clever compression that hide intent. A useful module hides complexity behind a small interface; it need not be split into tiny forwarding functions.

Remove comments that merely restate code or preserve abandoned scaffolding. Keep explanations of non-obvious reasons, risks, public contracts and licensing; uncertainty about a comment is not proof that it is disposable.

Complete the coherent simplification, then use the smallest check that addresses actual behavioral uncertainty. Reuse existing valid checks; obvious non-semantic edits need no new test or model evaluation. Apply YAGNI to tests: retain unique behavioral protection, remove duplicates and retired expectations, and keep temporary probes out of the maintained suite.

Report the meaningful simplification and verification limits. Do not add a mandatory cleanup pass to every coding task, a dedicated subagent, or a line-count target. Stop once the requested scope is clearer and sufficiently checked.
