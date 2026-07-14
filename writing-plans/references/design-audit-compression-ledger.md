# Design Audit and Compression Ledger

Use this reference only for D1 Focused or D2 Full planning when the requested change could alter ownership, introduce a seam, affect a public/shared contract, or make a costly-to-reverse decision. D0 changes stay in the Brief or Handoff plan and do not load this reference.

## Objective

Change the default objective from “add code that satisfies the request” to “re-evaluate the owning seam, then decide whether to keep, add, delete, rewrite, merge, split, replace, or defer.”

The output is a compact decision artifact tied to inspected evidence and discriminating proof, not a second implementation plan.

## Design depth

| Depth | Trigger | Required artifact |
|---|---|---|
| D0 None | Mechanical/local, owner and contract already clear, no new seam. | One sentence in the plan confirming no new owner/abstraction. Do not load this reference. |
| D1 Focused | A helper, adapter, cache, mode, schema, dependency, or owner change is plausible. | Only the relevant baseline/fact, decision, compression action, proof, and rollback rows. |
| D2 Full | Public contract, cross-module migration, security/shared state, hard-to-reverse architecture, or materially different viable options. | Full scoped artifact with alternatives, counterevidence, migration/rollback, and proof. |

Do not select depth from file count, line count, or a generic complexity score. If root cause or intended outcome is unresolved, return to the SQW diagnosis or intent owner before auditing a solution.

## Operating principle

Do not start by asking “what new code can satisfy the ask?” Start by asking:

1. What existing behavior, ownership boundary, assumption, or public contract is relevant?
2. Which current decision should remain, change, merge, split, be deleted, be replaced, or be deferred?
3. What is the smallest proven implementation that preserves maintainability and limits blast radius?

Write concise decision artifacts. Do not expose private chain-of-thought; expose inspected evidence, assumptions, questions, decisions, rejected alternatives, proof plan, rollback plan, and residual risks.

## Design artifact by depth

D1 may be embedded in the Handoff/Program artifact when that remains durable and unambiguous. D2 uses a separate task-owned design artifact at the user/project canonical worknote or external scratch path; do not create repository `tmp/` merely to satisfy this process.

The artifact is a decision record, not a transcript or duplicate plan.

- **D1 minimum:** request/contract, sources, one or more baseline/fact rows, decision/compression rows, proof/false-green risk, and rollback or removal condition.
- **D2 minimum:** D1 plus materially viable alternatives, counterevidence, migration/blast radius, unresolved fog, and a closure reason for the selected design.

Use stable IDs. The Program state introduced by the plan-state contract may project these rows; do not maintain two canonical copies.

## Workflow

### 0. Normalize the request

Restate the task in implementation-neutral terms:

- desired user-visible or system-visible outcome;
- constraints and non-goals;
- suspected files, domains, or public surfaces;
- ambiguity or missing input;
- planned mode: `design-only`, `design-plus-implementation`, `review`, or `deslop/refactor`.

Ask at most one focused clarification if missing input blocks safe design. Otherwise proceed with explicit assumptions.

### 1. Inspect repository evidence

Before designing, inspect actual project evidence using the active host's available read/search capabilities and read-only commands first.

Useful starting points:

```text
<host search capability>: find domain terms, symbols, errors, and behavior within the project
<host file discovery capability>: locate project instructions, README files, and relevant tests
<host read capability>: open only the bounded source spans needed for the decision
```

Also read nearby call sites, tests, configs, type definitions, architecture notes, and documented conventions. Use git history only when ownership, regression history, or compatibility risk matters.

Record sources inspected in the design artifact. Do not claim a fact unless it is grounded in inspected evidence or clearly marked as an assumption.

### Large-source boundary

When evidence spans a large code/document corpus, `long-document-segmented-writing` owns inventory, scratch notes, segmented drafting, reread, and scoped closure repair. This reference receives only the relevant source/evidence pointers and design implications. Reopen a pointer when an exact symbol, contract, or freshness claim affects a row; do not duplicate the long-document workflow here.

### 2. Baseline design inventory

Create stable IDs for relevant existing decisions and assumptions. Include the touched area, not the whole repository.

| id | existing element | current assumption/contract | evidence | owner/seam | risk if changed |
|---|---|---|---|---|---|
| B1 |  |  |  |  |  |

Include assumptions that make the task hard, brittle, duplicated, over-flexible, or append-only. Include known compatibility and rollback constraints. Later rows must reference these IDs.

### 3. Proposed design ledger

Name every important implementation move and tie it back to baseline rows.

| id | baseline refs | proposed decision | intent | files/seams touched | expected impact | rollback/proof |
|---|---|---|---|---|---|---|
| D1 | B1 |  |  |  |  |  |

No important new file, abstraction, dependency, public API, migration, schema, cache, adapter, mode, or test strategy may appear without a ledger row. If new code is proposed, state why existing code cannot be changed, deleted, merged, or reused instead. Keep the ledger small; split rows only when proof or rollback differs.

### 4. Compression review

Compare proposed decisions against baseline decisions and force an explicit keep/rewrite/split/merge/defer/delete/replace decision.

| id | baseline refs | decision refs | compression action | why this is not append-only | code-size pressure | proof or deferral owner |
|---|---|---|---|---|---|---|
| C1 | B1 | D1 | rewrite |  | delete/reduce/neutral/add |  |

Allowed actions:

- `keep`: the existing decision remains and is protected by proof.
- `rewrite`: change the existing decision in place because an assumption is too narrow, stale, or wrong.
- `split`: separate concerns currently coupled together.
- `merge`: remove a parallel path by folding it into the owning seam.
- `defer`: do not solve now; name risk, owner, and trigger.
- `delete`: remove dead, duplicate, misleading, or unnecessary logic.
- `replace`: substitute a simpler or safer existing mechanism.

Compression review must answer: “Am I adding code because it is right, or because I failed to improve an earlier design decision?”

### 5. Add another design round only when evidence requires it

Perform another round only when D2 applies or the current artifact still has a materially different viable option, unresolved counterexample, hidden dependency, ambiguous owner, or high-cost decision. Each added round must change evidence, a decision/compression row, proof, rollback, or blast radius. If independent evidence already excludes the alternatives, record the closure reason and stop; never add a ritual second round.

### 6. Planning gate

The design portion is ready only when:

- the chosen D0/D1/D2 depth matches observable risk;
- the relevant existing owners, assumptions, and contracts are grounded;
- decision rows cover each owner/seam change rather than every mechanical edit;
- compression review rejects avoidable append-only work;
- each retained decision has discriminating proof and false-green risk;
- migration, rollback, approval, and unresolved fog are explicit where applicable.

If the gate fails, inspect the missing source, reopen the decision, or return to diagnosis/intent discovery. Do not hide a gap by expanding prose.

For autonomous closure, the ledger must name each admitted strategy family, its discriminating evidence, and the lexicographic objective it can affect before contract freeze. A material change to intent, authority, a hard constraint, corner, verifier requirement, or search family requires a new contract epoch. If no safe choice follows from authoritative evidence, emit a bounded noninteractive ambiguity/unsat certificate; do not select a preference merely to keep the workflow moving.

### 7. Project decisions into plan slices

Each outcome slice references only the decisions, facts, invariants, and evidence it needs. State the observable result, dependency, allowed writes, proof claim/oracle, false-green risk, and rollback/removal condition. The SQW TDD/verification owner selects the concrete proof mechanism during execution.

Do not turn every changed file or action into a ledger row. Do not let a child or runtime rewrite canonical decisions; execution discoveries become plan-change proposals or invalidations.

## Handoff and closure

SQW owns implementation, review, verification, and closeout. Pass the design artifact ID/path/hash, selected rows, source/scope identity, global invariants, and unresolved fog. If actual evidence changes a decision, patch the canonical artifact and invalidate dependent slices before continuing.

A completed design artifact reports:

- selected depth and closure reason;
- source/evidence scope and freshness;
- retained facts/assumptions and decisions;
- compression actions and rejected alternatives;
- proof/false-green requirements;
- rollback, gaps, and empirical validation boundary.
