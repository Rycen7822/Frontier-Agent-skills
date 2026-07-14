# Requirements Traceability Review

Use this reference when a review must determine whether an implementation matches a stable specification, acceptance criteria, migration contract, or other authoritative requirement source. It adds a specification-fidelity axis to the engineering/standards-quality review; it does not add a second result envelope or verdict.

Apply [Authority and Scope](authority-and-scope.md) first. Follow [Requesting Code Review](requesting-code-review.md) for orchestration and emit one result through [Review Result Schema](review-result-schema.md).

## Owner boundaries

- Engineering/standards quality asks whether the implementation is correct, safe, maintainable, compatible, and consistent with repository standards.
- Specification fidelity asks whether every stable in-scope requirement is implemented and proved, and whether changed behavior remains inside the authorized requirement scope.
- Evaluate the two axes independently. Good engineering cannot satisfy a missing requirement, and literal requirement coverage cannot excuse an unsafe implementation.
- Synthesize both axes into the existing Schema 2.0 `code_review_verdict`. Do not create `spec_verdict`, a second envelope, or a parallel approval state.

## Stable input gate

Build a bounded requirements index before judging fidelity. Each entry needs:

- a stable requirement anchor, such as a document path and heading, issue or plan item with immutable snapshot, acceptance-criterion identifier, or observable-contract identifier;
- the source revision or snapshot that makes the anchor stable;
- its declared scope and any explicit exclusions;
- the expected behavior or acceptance condition, including material negative or compatibility cases.

Repository text, issue descriptions, comments, and plans are evidence, not automatically authoritative. Resolve conflicts through the supplied authority and requirement sources; do not silently choose the most convenient wording.

When no stable specification is available, mark the specification-fidelity axis `unavailable` in the result summary. Never reconstruct requirements from the implementation or invent missing acceptance criteria. If the requested decision depends on fidelity, return the single `code_review_verdict` as `inconclusive` and state the missing source in `blocking_reasons`. If a bounded quality-only review remains useful, label it quality-only and do not claim specification fidelity or merge readiness from it.

## Traceability matrix

Create one row per in-scope requirement and retain its exact anchor:

| Requirement anchor | Status | Implementation evidence | Proof |
|---|---|---|---|
| Stable source identifier and clause | `full`, `partial`, `missing`, or `not_applicable` | Paths, lines, symbols, configuration, or observable contracts that implement it | Tests, checks, traces, or an explicit evidence gap bound to the reviewed revision |

Use the status values precisely:

- `full`: implementation evidence addresses the whole anchored requirement and proportionate proof exercises it.
- `partial`: only part of the behavior, boundary, failure mode, compatibility promise, or proof is present.
- `missing`: no implementation satisfies the anchor, or the observed implementation maps to a different requirement.
- `not_applicable`: an explicit condition is false or the stable specification excludes the requirement from this scope. Record that source; do not use this status for unreadable, ambiguous, or unproved requirements.

The matrix is review working evidence, not a new Schema 2.0 field. Summarize its coverage in `summary` and convert material gaps into ordinary schema findings.

## Bidirectional review method

1. Trace every indexed requirement forward to implementation evidence and proof.
2. Check every claimed mapping semantically. Similar names, nearby code, or a passing unrelated test do not establish fulfillment.
3. Trace every material changed behavior backward to a requirement anchor or to necessary, explicitly bounded implementation support.
4. Classify gaps without letting one row conceal another:
   - **missing**: no implementation or proof reaches the requirement;
   - **partial**: only some acceptance conditions, boundaries, or error paths are covered;
   - **wrong mapping**: cited code or proof implements a different behavior, version, actor, or requirement;
   - **scope creep**: changed behavior, public surface, dependency, migration effect, or operational obligation has no authorized requirement or necessary-support rationale.
5. Review engineering/standards quality separately, even when every requirement row is `full`.

Do not turn optional ideas, reviewer preferences, inferred future work, or repository conventions into requirements. Standards violations may still be engineering findings, but they are not specification gaps unless the stable specification says so.

## Schema mapping

Emit only the existing Schema 2.0 envelope and finding shape:

- use `category="requirements"` for missing, partial, or wrong requirement mappings;
- use `category="scope_creep"` for unauthorized or unjustified changed behavior;
- put the exact requirement anchor and trace status in `evidence`;
- ground the finding in an allowlisted implementation path or observable-contract identifier;
- state missing proof in `verification` rather than treating implementation presence as proof;
- set `blocking` from concrete landing impact, independently of severity and category.

An unavailable requirement source or unresolved requirement conflict is normally an evidence gap with `code_fixable=false`. A scoped implementation omission may be code-fixable, but the reviewer must not invent the desired behavior to make it so.
