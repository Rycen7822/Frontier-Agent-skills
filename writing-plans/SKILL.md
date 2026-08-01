---
name: writing-plans
description: "Write source-bound software implementation Handoffs and multi-session Programs from settled decisions; not diagnosis or execution."
metadata:
  version: 8.1.0
---

Handoff crosses contexts; Program tracks a changing frontier; otherwise stay native. Skill-source changes use skill authoring. Do not decide, diagnose, execute, verify or claim.

## Bind

Use invocation-bound source; do not reread it. Treat named plan/owner/test/symbol paths as resolved. Do not inventory, seek alternate owners, or check existence unless the binding fails or contradicts the prompt.

Bind portable identity: revision or explicit non-Git identity, with repo-relative dirty/protected and first-slice paths/symbols. Resolve root once; never bind temporary/home paths or future `pwd` equality.

Facts/authority/evidence are fixed. Unknowns block later slices only; missing intent/write/irreversible approval blocks that slice.

## Contract

Minimal sufficient form: state each fact/decision/evidence once; omit generic/empty prose; do not expand one sentence into its own heading. No word/byte reduction target: retain needed facts.

Write a title and only one compact contract table or four-row bullets:

- State — Bound source identity; Protected work and allowed effects; Settled decisions; Exact first-slice inputs, outputs, values, invariants; observed protected-test I/O and values, once; Later blockers and dependencies.
- Resume — Resume preflight (concrete): consume a matching freshness-bound host attestation when resolved root, bound source identity, freshness, and dirty scope match; transfer it unchanged and do not rerun it; if missing or mismatched, run one combined preflight.
- Slice — Goal / non-goals; First source-changing slice and files/symbols; Exact next source-changing action.
- Proof — Acceptance and verification: the one combined final proof command is the only post-edit command and covers behavior, diff scope, protected boundary, residue, and whitespace; Rollback/cleanup when material.

Fill rows directly from settled facts once; each fact has one row owner. State behavior, not just a symbol/test. Later Slice and Proof rows reference State instead of repeating its protected behavior. No format comparison or planning rationale.

Program uses those rows: State contains Current frontier and later blockers; Slice contains named Milestones in dependency order, each with acceptance; dependencies cite milestone names, never ordinals. Include Migration/deprecation owner and removal condition when applicable. Update-in-place rule: only a later planning invocation updates the Program; an executor treats it as protected immutable input.

The Resume row resolves root anew; exclude the named plan deliverable itself (including untracked `PLAN.md`) from dirty scope; reject other dirt. Never compare against the original absolute root or require globally clean status.

Next action: first edit/result/check; inspect only if blocked. Use the prompt-bound verification command; if absent, make one bounded authority inspection. Never infer the runner from language, filename, or convention. The repository's test owner supplies the Proof—not an example or alternative. Python unittest: `PYTHONDONTWRITEBYTECODE=1 python -m unittest <repo-test>`; never use bare `pytest`; leaves no cache/state artifact. Other owners disable residue in-command or include exact cleanup. Name each read/status/diff/acceptance once; split only on failure or an independent long check.

Before return, reject: Resume missing attestation acceptance or one-preflight fallback; ordinal dependency references; prose broken only to fit a column. After writing, allow at most one combined planner-only non-content confirmation (status/hash/`git diff --check`); never put it in the executor plan. Do not reopen, print or diff contents. After Proof, run no status, diff, test, or confirmation.

Reply only with plan/named Markdown; do not instruct execution to modify the plan. No sidecar/state/copy, source edits or completion claims.
