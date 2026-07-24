---
name: writing-plans
description: "Write source-bound software implementation Handoffs and multi-session Programs from settled decisions; not diagnosis or execution."
metadata:
  version: 8.0.0
---

Handoff crosses contexts; Program tracks a changing frontier; otherwise stay native. Use a skill-authoring workflow only for skill-source changes. Do not decide, diagnose, execute, verify or claim.

## Bind

Exact source content already bound in the invocation: do not reread it. Treat prompt-named plan/owner/test/symbol paths as resolved. One combined prewrite inspection covers missing direct reads and cross-context root/HEAD/status. Do not inventory files, search alternate owners, or check existence separately unless it fails or contradicts the prompt.

Bind portable identity: Revision or explicit non-Git source identity; repo-relative paths for dirty/protected and first-slice owners/symbols. Resolve root once; never bind temporary/home paths or future `pwd` equality.

Facts/authority/evidence are fixed. Unknowns block later slices only; missing intent/write/irreversible approval blocks that slice.

## Contract

Minimal sufficient form: state each fact/decision/evidence once; omit generic/empty prose; do not expand one sentence into its own heading. No word/byte reduction target: retain needed facts.

Write a title and only one compact contract table or four-row bullets:

- State — Bound source identity; Protected work and allowed effects; Settled decisions; Exact first-slice inputs, outputs, values, invariants; Later blockers and dependencies.
- Resume — Resume preflight.
- Slice — Goal / non-goals; First source-changing slice and files/symbols; Exact next source-changing action.
- Proof — Acceptance and verification once as one combined command/evidence statement; Rollback/cleanup when material.

Fill rows directly from settled facts once; state behavior, not just a symbol/test. No format comparison or planning rationale.

Program uses those rows: State contains Current frontier and later blockers; Slice contains Milestones in dependency order, each with acceptance, plus Migration/deprecation owner and removal condition when applicable. Update-in-place rule: only a later planning invocation updates the Program; an executor treats it as protected immutable input.

Resume preflight resolves root anew; combine identity/freshness/dirty checks. Exclude the named plan deliverable itself (including untracked `PLAN.md`); reject other dirt. Never compare against the original absolute root or require globally clean status.

Next action: first edit/result/check; inspect only if blocked. Each slice: one combined final proof command—not an example or alternative—from the repository's test owner. Python unittest: `PYTHONDONTWRITEBYTECODE=1 python -m unittest <repo-test>`; never use bare `pytest`; leaves no cache/state artifact. Other owners disable residue in-command or include exact cleanup. Split on failure/independent long check; name each read/status/diff/acceptance once.

Review the whole plan before writing. After writing, allow at most one combined non-content confirmation (status/hash/`git diff --check`); do not reopen, print or diff contents.

Reply only with plan/named Markdown; do not instruct execution to modify the plan. No sidecar/state/copy, hard wraps, source edits or completion claims.
