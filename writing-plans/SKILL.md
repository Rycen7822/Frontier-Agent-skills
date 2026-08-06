---
name: writing-plans
description: "Write source-bound software implementation Handoffs and multi-session Programs from settled decisions; not diagnosis or execution."
metadata:
  version: 8.2.1
---

Handoff crosses contexts; Program tracks a changing frontier; otherwise stay native. Skill-source changes use skill authoring. Do not decide, diagnose, execute, verify or claim.

A bounded single-session plan with named files and checks stays native: inspect each available bound file once, then write a concise ordered plan with observed symbols and behavior, exact edits, checks, expected results, and failure exits. Do not substitute placeholders such as "existing conventions" for available source facts. Do not add the four-row contract, host attestation, combined-proof-only rule, or an unrequested owner handoff. Prompt-bound files, commits, completed state, checks, and commands remain resolved inputs when an isolated planning workspace does not contain them; do not replace the requested plan with a missing-file diagnosis.

## Bind

Use invocation-bound source; do not reread it. Treat named plan/owner/test/symbol paths as resolved. Do not inventory, seek alternate owners, or check existence unless the binding fails or contradicts the prompt.

Bind portable identity: revision or explicit non-Git identity, with repo-relative dirty/protected and first-slice paths/symbols. Resolve root once; never bind temporary/home paths or future `pwd` equality.

Facts/authority/evidence are fixed. Unknowns block later slices only; missing intent/write/irreversible approval blocks that slice.

## Contract

Minimal sufficient form: omit generic/empty prose; do not expand one sentence into its own heading. No word/byte reduction target: retain needed facts. Keep each prose paragraph on one physical line; insert line breaks only at Markdown structural boundaries, never inside a sentence or merely to fit a column.

For a Handoff or Program, write a title and either one contract table or a three- or four-row bullet contract:

- State — Bound source identity; Protected work and allowed effects; Settled decisions; Exact first-slice inputs, outputs, values, invariants; observed protected-test I/O and values, once; Later blockers and dependencies.
- Resume — For a later source-changing slice that crosses contexts, consume a matching freshness-bound host attestation when resolved root, bound source identity, freshness, and dirty scope match; transfer it unchanged and do not rerun it; if missing or mismatched, run one combined preflight. Omit this row for an immutable artifact handoff whose next action is verification only.
- Slice — Goal / non-goals; First source-changing slice and files/symbols; Exact next source-changing action.
- Proof — Acceptance and verification: the one combined final proof command is the only post-edit command and covers behavior, diff scope, protected boundary, residue, and whitespace; Rollback/cleanup when material.

Fill rows directly from settled facts, assigning each fact to one row. State behavior, not just a symbol/test. Later Slice and Proof rows reference State instead of repeating protected behavior. No format comparison or planning rationale.

Program uses those rows: State contains Current frontier and later blockers; Slice contains named Milestones in dependency order, each with acceptance; dependencies cite milestone names, never ordinals. Include Migration/deprecation owner and removal condition when applicable. Update-in-place rule: only a later planning invocation updates the Program; an executor treats it as protected immutable input.

The Resume row resolves root anew; exclude the named plan deliverable itself (including untracked `PLAN.md`) from dirty scope; reject other dirt. Never compare against the original absolute root or require globally clean status.

Next action: first edit/result/check; inspect only if blocked. Use the prompt-bound verification command. When the prompt binds exact files and required checks but omits a repository-wide runner, state the narrow checks implied by those bindings and leave only the broader runner as a later blocker; do not block the plan or invent a full-suite command. The repository's test owner supplies any broader Proof. Python unittest: `PYTHONDONTWRITEBYTECODE=1 python -m unittest <repo-test>`; never use bare `pytest`; leaves no cache/state artifact. Other owners disable residue in-command or include exact cleanup. Split Proof only on failure or an independent long check.

Before return, reject a required Resume that lacks attestation acceptance or one-preflight fallback, and reject ordinal dependency references. After writing, allow at most one combined planner-only non-content confirmation (status/hash/`git diff --check`); never put it in the executor plan. Do not reopen, print or diff contents. After Proof, run no status, diff, test, or confirmation.

Reply only with plan/named Markdown; do not instruct execution to modify the plan. No sidecar/state/copy, source edits or completion claims.
