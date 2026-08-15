---
name: writing-plans
description: "Use after software decisions and diagnosis are settled to write source-bound software implementation Handoffs and durable multi-session Programs."
metadata:
  version: 8.4.0
---

Handoff crosses contexts; Program tracks a changing frontier; otherwise stay native. Skill-source changes use skill authoring. Planning begins after decisions and diagnosis are settled; execution, verification, and completion claims remain with their owners.

A bounded single-session request naming files and checks must end as a native ordered plan even when Git identity, dirty/protected paths, or exact source identity are visible; omit those facts unless named; skip the Handoff/Program contract below. Inspect each available bound file once. State observed symbols and behavior, exact edits, checks, expected results, and failure exits.

Exact means observed old→new symbols, argument-parser calls, literal edits and structural anchors, and complete runnable test bodies when exact tests are requested. Every exact check is a runnable command asserting its edit literals; expected snippets, generic "add parsing", prose-only tests, and "follow existing conventions" fail.

For a symbol rename, make the residual check identifier-aware: test old-name absence and new-name presence against the same collected identifier set; avoid raw substrings when names overlap and never compare identifiers with a tokenizer token-type constant.

Derive one starting cwd and module path from imports/layout; never `cd` into the stated cwd again. Include `PYTHONPATH` when needed; set it to the directory containing the top-level imported package, not the directory above, and use that value in every command.

Use only executable workspace-bound checks. A native proof never adds whole-file snapshots, Git scope, protected boundary, residue/whitespace, rollback/cleanup, attestation, combined-only proof, or repository-wide check unless named by the request or bound source. An explicit non-Git identity forbids Git status, diff, or rollback. No contract rows or unrequested owners.

## Bind

Use invocation-bound source; do not reread it. Treat named plan/owner/test/symbol paths as resolved. Do not inventory, seek alternate owners, or check existence unless the binding fails or contradicts the prompt.

Bind portable identity: revision or explicit non-Git identity, with repo-relative dirty/protected and first-slice paths/symbols. Resolve root once; never bind temporary/home paths or future `pwd` equality.

Facts/authority/evidence are fixed. Unknowns block later slices only; missing intent/write/irreversible approval blocks that slice.

## Contract

Minimal sufficient form: omit generic/empty prose; do not expand one sentence into its own heading. No word/byte reduction target: retain needed facts. Keep each prose paragraph on one physical line; insert line breaks only at Markdown structural boundaries, never inside a sentence or merely to fit a column.

For a Handoff or Program, write a title; use these rows in one contract table or a three- or four-row bullet contract:

- State — Bound source identity; Protected work and allowed effects; Settled decisions; Exact first-slice inputs, outputs, values, invariants; observed protected-test I/O and values, each edit literal and heading exactly once; Later blockers and dependencies. Mark unfinished gates and verification pending even when Slice performs them.
- Resume — Required for any later source edit crossing contexts. Consume a matching freshness-bound host attestation when resolved root, bound source identity, freshness, and dirty scope match; transfer it unchanged and do not rerun it; if missing or mismatched, run one combined preflight. Omit only for an immutable artifact handoff whose next action is verification.
- Slice — Goal / non-goals; First source-changing slice and files/symbols; Exact next source-changing action.
- Proof — Acceptance and verification: Acceptance behavior; Minimum sufficient evidence; External owner gates; Escalation and blocked/inconclusive stops; Rollback/cleanup when material.

Fill rows directly from settled facts, assigning each fact to one row. State behavior, not just a symbol/test. Later Slice and Proof rows reference State instead of repeating protected behavior.

Program uses those rows: State contains Current frontier and later blockers; Slice contains named Milestones in dependency order, each with acceptance; dependencies name every prerequisite milestone, never ordinals or collective references. Each exact edit must be executable against the observed body and carry every preserved transformation/invariant into code, not prose. Include Migration/deprecation owner and removal condition when applicable. Update-in-place rule: only a later planning invocation updates the Program; an executor treats it as protected immutable input.

The Resume row resolves root anew; exclude the named plan deliverable itself (including untracked `PLAN.md`) from dirty scope; reject other dirt. Never compare against the original absolute root or require globally clean status.

Next action: first edit/result/check; inspect only if blocked. Use the prompt-bound verification command. When the prompt binds exact files and required checks but omits a repository-wide runner, state the narrow checks implied by those bindings and leave only the broader runner as a blocker; do not block the plan or invent a full-suite command. The repository's test owner supplies any broader Proof. Prefix tests with `PYTHONDONTWRITEBYTECODE=1`; use `python -m unittest <repo-test>`, or `python -m pytest -p no:cacheprovider`; other owners bind residue cleanup. The executor completes coherent edits, then selects the lowest-cost evidence for risk/gate; Proof sets no patch-by-patch order.

Before return, require attestation acceptance or one-preflight fallback for Resume, name dependencies, and carry every promised transformation or invariant into its exact edit, including each observed literal and structural anchor. After writing, run at most one planner-only non-content confirmation (`git diff --check` or owner check), then return the plan; Proof remains executor-owned.

Reply only with the plan or named Markdown. The selected Program is the durable planning state; source edits and completion claims remain with execution owners.
