---
name: writing-plans
description: "Use after software decisions and diagnosis are settled to write source-bound software implementation Handoffs and durable multi-session Programs."
metadata:
  version: 8.4.0
---

Handoff crosses contexts; Program tracks a changing frontier; otherwise stay native. Skill-source changes use skill authoring. Planning follows settled decisions and diagnosis; execution, verification, and completion claims remain with their owners.

A bounded single-session request naming files and checks must end as a native ordered plan even when Git identity, dirty/protected paths, or exact source identity are visible; omit those facts unless named; skip the Handoff/Program contract below. Inspect each available bound file once. State observed symbols and behavior, exact edits, checks, expected results, and failure exits.

Exact means old→new symbols, argument-parser calls, literals/anchors, and complete runnable test bodies when exact tests are requested. Edits keep literals in owning files; each exact check is a runnable command asserting them there; expected snippets, generic "add parsing", prose-only tests, and "follow existing conventions" fail.

Map every observed old-name match to its owning file exactly once; never invent an occurrence or copy one across owners. Files without a match are proof-only; preserve superstrings such as `test_timeout`. Prove residuals with one identifier set: old absent, new present. Substring-only comparison fails; tokenizer type checks may select identifiers, but name comparison uses `token.string`.

Derive one starting cwd and module path; never `cd` into the stated cwd again. Include `PYTHONPATH` when needed: remove the imported package from its path; `fixtures/src/client.py` imported as `src.client` yields `fixtures`. Reuse it in every command.

Use only executable workspace-bound checks. A native proof never adds whole-file snapshots, Git scope, protected boundary, residue/whitespace, rollback/cleanup, attestation, combined-only proof, or repository-wide check unless named by the request or bound source. An explicit non-Git identity forbids Git status, diff, or rollback. No contract rows or unrequested owners.

## Bind

Use invocation-bound source; do not reread it. Treat named plan/owner/test/symbol paths as resolved. Do not inventory, seek alternate owners, or check existence unless the binding fails or contradicts the prompt.

Bind portable identity: revision or explicit non-Git identity, with repo-relative dirty/protected and first-slice paths/symbols. Resolve root once; never bind temporary/home paths or future `pwd` equality.

Facts/authority/evidence stay fixed; retain every named identity/status literal across turns. Unknowns block later slices only; missing intent/write/irreversible approval blocks that slice.

## Contract

Minimal sufficient form: omit generic/empty prose; do not expand one sentence into its own heading. No word/byte reduction target: retain needed facts. Keep each prose paragraph on one physical line; insert line breaks only at Markdown structural boundaries, never inside a sentence or merely to fit a column.

For a Handoff or Program, write a title; use these rows in one contract table or a three- or four-row bullet contract:

- State — Bound source identity; Protected work and allowed effects; Settled decisions; Exact first-slice inputs, outputs, values, invariants; observed protected-test I/O and values, each edit literal and heading exactly once; Later blockers and dependencies. Mark unfinished gates and verification pending even when Slice performs them.
- Resume — Required for any later source edit crossing contexts. Consume a matching freshness-bound host attestation when resolved root, bound source identity, freshness, and dirty scope match; transfer it unchanged and do not rerun it; if missing or mismatched, run one combined preflight. Omit only for an immutable artifact handoff whose next action is verification.
- Slice — Goal / non-goals; First source-changing slice and files/symbols; Exact next source-changing action referencing its State-bound literal and anchor.
- Proof — Acceptance and verification: Acceptance behavior; Minimum sufficient evidence; External owner gates; Escalation and blocked/inconclusive stops; Rollback/cleanup when material.

Fill rows directly from settled facts, assigning each fact to one row. State behavior, not just a symbol/test. Later Slice and Proof rows reference State instead of repeating protected behavior.

Program uses those rows: State contains Current frontier and later blockers; Slice contains named Milestones in dependency order, each with acceptance; dependencies name every prerequisite milestone, never ordinals or collective references. Each exact edit must be executable against the observed body and carry every preserved transformation/invariant into code, not prose. Include Migration/deprecation owner and removal condition when applicable. Update-in-place rule: only a later planning invocation updates the Program; an executor treats it as protected immutable input.

The Resume row resolves root anew; exclude the named plan deliverable itself (including untracked `PLAN.md`) from dirty scope; reject other dirt. Never compare against the original absolute root or require globally clean status.

Next action: first edit/result/check; inspect only if blocked. Use the prompt-bound verification command. With exact files/checks but no repository runner, state the narrow checks implied by those bindings; do not block the plan or invent a full-suite command. The repository's test owner supplies any broader Proof. Prefix tests with `PYTHONDONTWRITEBYTECODE=1`; use `python -m unittest <repo-test>` or `python -m pytest -p no:cacheprovider`; other owners bind residue cleanup. The executor completes coherent edits and selects the lowest-cost evidence; Proof sets no patch-by-patch order.

Before return, require attestation acceptance or one-preflight fallback for Resume; name dependencies; carry every promised transformation or invariant into its exact edit; verify State and Slice bind each relevant observed literal and structural anchor; verify every exact check is runnable. After writing, run at most one planner-only non-content confirmation (`git diff --check` or owner check), then return the plan; Proof remains executor-owned.

Reply only with the plan or named Markdown. The selected Program is the durable planning state; source edits and completion claims remain with execution owners.
