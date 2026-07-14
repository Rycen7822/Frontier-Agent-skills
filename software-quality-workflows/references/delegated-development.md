# Delegated Development

Use this reference only for M2 Sparse or M3 Full execution when approved plan slices are genuinely independent and fresh context, parallelism, or separation of duties has expected net value. It preserves controller ownership, generated context projection, sequential specification and engineering review, and verifiable completion evidence.

This branch owns delegation mechanics only. [Authority and Scope](authority-and-scope.md) owns permission, risk, manifests, and roles; [Test-Driven Development](test-driven-development.md) owns RED/GREEN/REFACTOR; [Requesting Code Review](requesting-code-review.md) and [Requirements Traceability Review](requirements-traceability-review.md) own review; [Verification Discipline](verification-discipline.md) owns proof and completion language.

## Contents

- [When to use](#when-to-use)
- [Prerequisites](#prerequisites)
- [Per-task state machine](#per-task-state-machine)
- [Final integration](#final-integration)
- [Evidence-heavy audit and synthesis delegations](#evidence-heavy-audit-and-synthesis-delegations)
- [Failure and timeout handling](#failure-and-timeout-handling)
- [Common failure modes](#common-failure-modes)

## When to use

Delegate writable slices only when all of these conditions hold:

1. no unresolved control/data dependency exists between concurrent slices;
2. declared `write_set` values do not overlap;
3. declared `resource_set` values do not conflict;
4. a shared schema/ledger is frozen or each child writes only a unique candidate artifact;
5. source revision and scope hash are the same for every child;
6. the controller has a concrete merge and verification path; and
7. expected reliability/latency benefit exceeds capsule, review, and reconciliation cost.

Read-only research may relax the write-set condition, but final synthesis and canonical decisions remain controller-owned. Prefer controller-side execution when work is small, repeatedly touches the same owner seam, depends on immediate local evidence, is dominated by one slow operation, or has hidden/shared mutable state. Do not fan out merely because workers are available.

## Prerequisites

Before dispatching:

1. Confirm M2/M3, `change` authority, the full scope manifest, risk ceiling, and any required approvals.
2. Validate the durable plan, source/scope hash, current frontier, global invariants, dependency outputs, and unresolved fog; do not mirror every future task into `todo`.
3. Declare each slice's control/data dependencies, `read_set`, `write_set`, `resource_set`, side effect, verifier, and false-green risk.
4. Resolve user decisions before dispatch. Subagents cannot ask the user questions, so ambiguous acceptance criteria remain controller-owned blockers.
5. Acquire required locks and record the current source/scope snapshots and state version used to detect drift while work is pending.

## Per-task state machine

Run each task through this sequence. Tasks with a dependency or shared writable path are serial even if unrelated evidence gathering is parallel.

### 1. Dispatch one bounded implementer

Generate the child's self-contained context capsule from canonical plan/workflow state. Include only:

- goal, global invariants, exact slice objective, and completion criterion;
- source revision, scope hash, state version, dependency outputs, and evidence pointers;
- allowed reads/writes, protected paths/resources, side-effect ceiling, approval, and lock boundaries;
- relevant decisions/facts, verifier, expected distinction, and false-green risk;
- explicit out-of-scope/fog items, nesting limit, output language, and required return fields.

Do not copy the full plan, chat transcript, unrelated completed history, or all future nodes. A generated capsule records included and omitted refs; when it exceeds budget, omit optional history before authority, invariants, objective, scope, or proof.

Use the active host's live delegation interface exactly as exposed. Do not invent operation names or parameters copied from another host or version. Inspect the returned payload to determine whether the result completed immediately, fell back synchronously, or remains background-pending.

The implementer reports touched files, commands and original statuses, evidence paths, unresolved questions, and any external side-effect handles. A child self-report is not controller proof.

### 2. Controller validation

When the result returns, the controller must:

- verify every claimed file write and inspect the actual diff or artifact;
- confirm the task stayed inside the manifest and did not overwrite unrelated work;
- rerun or independently inspect the smallest critical proof when the claim is consequential;
- re-observe revision/path snapshots before review;
- classify failures as product, harness, environment, permission, baseline, or stochastic failures.

Do not advance because the child said “tests passed,” “uploaded,” “saved,” or “committed.” Verify local state directly and verify remote writes using the returned URL, ID, account, session, checksum, or status.

### 3. Specification gate first

Run a fresh-context requirements review against the original task, acceptance criteria, approved design rows, paths, signatures, and explicit non-goals. Use [Requirements Traceability Review](requirements-traceability-review.md) when stable anchors exist.

The specification gate must detect both omissions and scope creep. Fix only confirmed in-scope gaps, then recheck within the review tier's bounded cycle budget. Engineering quality review does not begin while a specification blocker remains open.

### 4. Engineering-quality gate second

After specification conformance is established, run the engineering review through [Requesting Code Review](requesting-code-review.md). Evaluate correctness, conventions, error handling, test quality, security, compatibility, design seams, and the domain owners triggered by the changed surface.

A fixer cannot approve its own work. Review/fix cycles are bounded by the selected review tier; unresolved blockers are reported rather than hidden in an open-ended loop.

### 5. Complete the task deliberately

Mark the task complete only after controller validation, specification review, engineering review, and applicable focused evidence have closed. Record remaining affected-area, public-surface, or canonical gates for final integration rather than claiming them early.

## Final integration

After all slices are complete:

1. Reconcile the plan, `todo`, design ledger, actual diff, and any project progress note.
2. Inspect cross-task contracts and integration seams, including dormant schema/introspection paths, generated docs or clients, package/install output, and direct protocol calls when applicable.
3. Run the affected-area, public-surface, and canonical gates required by [Verification Discipline](verification-discipline.md).
4. Perform a final fresh-context review only when the chosen review tier or cross-task risk justifies it.
5. Report actual evidence, baseline failures, unavailable gates, unresolved blockers, and residual risk separately.

Do not claim completion while a required delegated result, review, canonical gate, or blocker audit is pending. If the runtime returns results asynchronously, any earlier user-facing status is explicitly interim.

## Evidence-heavy audit and synthesis delegations

For analysis, reverse engineering, repository audits, product-path simulations, or source comparisons, require each child to write a unique Markdown report in the active workspace or a task-owned temporary directory before returning. Each report includes exact sources read, path/line or page evidence, commands used, conclusions, risks, open questions, and the output path.

Assign work by evidence weight and risk rather than equal file count. A single high-risk control surface or very large file can justify its own worker, while many short related files can be grouped.

The controller reads every report, independently reproduces high-severity claims, and merges only confirmed findings into canonical notes or ledgers. Parent-owned artifacts such as `problems.md` are not edited concurrently by children. If a child times out, consume and validate any durable partial report, then cover the missing evidence centrally or dispatch a narrower replacement.

For broad surveys, use a second cross-validation wave when source authority, venue status, original-source reading, link correctness, duplicate control, or architecture coverage materially affects the conclusion. The controller still spot-checks high-risk claims after that wave.

When delegation is explicitly testing proactive memory behavior, require every child report to record `SAVE` only for a genuinely reusable lesson or `SKIP` with rationale. Verify a claimed save and the absence of an unexpected save using the exact same provider identity/account and session used by the child.

For plugin-managed shared ledgers, load [Shared-Ledger Delegation](shared-ledger-delegation.md). For paper plus released source plus target-system comparisons, load [Paper, Source, and Target-System Gap Audits](paper-source-target-gap-audits.md). For large report consolidation, load [Multi-Source Markdown Synthesis](multi-source-markdown-synthesis.md).

If the user asks for a swarm, maximum safe fan-out, or a product stress simulation, prefer a dedicated host-compatible swarm-coordination owner when one is available and authorized rather than expanding this branch into a second swarm protocol. Give workers distinct scenarios that cover normal workflows and edge surfaces such as isolation, navigation or ranking, public CLI/API contracts, boundary validation, refresh/recovery, and persistent state side effects.

## Failure and timeout handling

- If a child fails before producing trustworthy artifacts, dispatch a narrower replacement or complete the bounded slice in the controller; do not preserve context purity at the expense of finishing the task.
- For bulk generation, give every child a unique candidate file and a parseable count/validation contract. Merge into the canonical dataset only after controller-side quality and diversity checks.
- If concurrency confounds a result, downgrade it to unverified evidence and reproduce in isolation.
- Respect user-specified delegation depth and count caps. Never nest beyond the live runtime limit or the user's bound.
- Do not launch more workers merely to maximize count; fan out only across genuinely independent risk surfaces.

## Common failure modes

- Dispatching children without complete context or stable requirement anchors.
- Making children reread an entire plan instead of passing the exact assigned slice.
- Running specification and quality review in the wrong order.
- Allowing the implementer or fixer to self-approve.
- Treating child summaries as proof of files, tests, remote writes, or completion.
- Concurrent edits to shared files, datasets, ledgers, or final reports.
- Open-ended review loops that ignore the selected tier's budget.
- Reporting final completion while background work is pending.
