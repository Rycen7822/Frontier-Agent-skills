# Safe Test-Driven Development

Use this local fallback for features, bugfixes, refactors, and behavior changes when the active plan routes TDD here. It owns the RED/GREEN/REFACTOR method, not bug diagnosis, authorization, verification policy, or test retirement.

## Contents

- [Owner boundaries](#owner-boundaries)
- [Entry rules](#entry-rules)
- [RED/GREEN/REFACTOR](#redgreenrefactor)
- [Test design](#test-design)
- [Existing code and old tests](#existing-code-and-old-tests)
- [When automated RED is unavailable](#when-automated-red-is-unavailable)
- [Completion evidence](#completion-evidence)

## Owner boundaries

- Bugfix order is owned by [Systematic Debugging](systematic-debugging.md). Enter this workflow at the RED transition it selects.
- Test purpose, layer, provenance, quarantine, promotion, and retirement are owned by [Test Lifecycle Management](test-lifecycle-management.md).
- Gate selection, canonical status, baseline deltas, and completion claims are owned by [Verification Discipline](verification-discipline.md).
- Side effects and scope are governed by [Authority and Scope](authority-and-scope.md).

Do not recreate those policies here.

## Entry rules

### TDD-01 — Define behavior before test shape

Write the success contract in user-observable terms:

- input or trigger;
- expected output, state transition, or rejection;
- relevant boundary and error behavior;
- explicit non-goals and compatibility constraints.

Derive the test from that contract, not from a desired diff, helper name, or internal call sequence.

For a non-trivial feature, refactor, or migration, finish the required design/plan audit before RED. For a bugfix, follow the debugging owner: diagnose the cause first, plan only when the supported repair is design-sensitive, then return here for the regression RED.

Documentation, metadata, and configuration-only edits do not require an invented behavioral RED. Use their real static or runtime contract proof as selected by the verification owner.

### Advance by a behavior-complete vertical slice

For multi-part behavior, take one narrow vertical slice through the real owning path from observable input to observable result. Complete its RED, GREEN, and focused proof before starting the next slice. Do not write all tests first and then all implementation, or build disconnected layers that cannot yet demonstrate one contract. A slice may be small, but it must be behavior-complete and independently reviewable.

## RED/GREEN/REFACTOR

### TDD-02 — RED must fail for the expected reason

Write the smallest test that demonstrates one missing behavior, then run it.

A valid RED:

- reaches the intended code or public surface;
- fails because the specified behavior is absent or wrong;
- has a failure message that distinguishes the contract gap;
- is deterministic enough to repeat or has a documented statistical oracle.

A typo, broken fixture, missing import, unavailable environment, or harness setup error is not a RED. Fix the test harness or report the blocker before implementation. If the test passes immediately, determine whether the behavior already exists, the assertion is too weak, or the wrong surface was exercised.

### TDD-03 — GREEN is the smallest general contract implementation

Implement only what is needed to satisfy the current behavior contract, including edge cases already inside that contract. Prefer the owning seam over a wrapper, mode, cache, adapter, dependency, or parallel path. A special-case constant is acceptable only when that constant is the actual contract, not when it merely satisfies one fixture.

Run the focused test after each coherent change. If GREEN requires a new public behavior or architecture choice outside the approved plan, return to planning instead of expanding scope silently.

### TDD-04 — Refactor only while green

After the focused behavior passes:

- remove duplication;
- improve names and boundaries;
- simplify setup and assertions;
- extract reusable helpers only when repeated evidence warrants them.

Keep the focused proof green in small steps. Preserve user and predecessor implementations; do not delete working code merely because its tests were added later.

## Test design

### TDD-05 — Test behavior with controlled boundaries

- Prefer public behavior and real internal collaborators.
- Use test doubles for nondeterministic, expensive, destructive, unavailable, or genuinely external boundaries.
- Give each double an explicit contract and keep it narrower than the real dependency.
- Do not assert private call order when an observable result protects the same risk.
- Test errors, limits, transitions, and negative paths that belong to the stated behavior.

#### Independent oracle and sensitivity

Expected results must come from an independent oracle: a requirement, worked literal example, independently implemented reference, stable cross-version fixture, or property/metamorphic relation. Do not compute the expected value with the production helper, generator, parser, or the same algorithm under a different name; that tautological test cannot contradict the implementation.

For each non-trivial test, name at least one plausible wrong implementation that the assertion would kill. Round-trip tests need a second independent check when encoder and decoder could share the same defect. Serialization and migration tests should include a fixed externally meaningful fixture or cross-implementation expectation, not only newly generated goldens.

### TDD-06 — Expand proof proportionally

After focused GREEN, use the verification owner to select affected and canonical gates. Compare failures and warnings with the recorded baseline rather than assuming the repository was pristine. Preserve the canonical command’s real result.

### TDD-07 — Prove the user-facing surface

When behavior is exposed through a CLI, API, protocol, UI, generated artifact, package, or installed entrypoint, add proof at that surface. Internal unit success alone does not establish that routing, serialization, packaging, or runtime loading still works. An ad-hoc probe is supplementary evidence, not a replacement for the project’s canonical gate.

## Existing code and old tests

### TDD-08 — Interpret old tests before changing either side

When a new implementation conflicts with an old test, classify the test:

- still-valid contract;
- intentionally changed contract;
- stale implementation-detail assertion;
- genuine regression;
- harness or environment failure.

Preserve still-valid contracts, update intentionally changed contracts with their requirement decision, and treat genuine regressions as product failures. Use the lifecycle owner for merge, promotion, quarantine, supersession, and retirement decisions.

For an existing untested patch:

1. preserve it;
2. characterize current observable behavior;
3. identify the unresolved contract gap through the debugging owner;
4. run a regression RED for that gap;
5. make the smallest in-place GREEN change.

### TDD-09 — Keep planning and diagnosis in one order

TDD does not own a second bugfix sequence. Bugfixes enter from the authoritative debugging state machine. Non-trivial new behavior and refactors enter after planning. If a test reveals an unplanned public contract, dependency, mode, schema, or ownership change, return to the plan before writing production code.

### TDD-10 — Treat tests as maintained assets

Every durable test needs enough provenance to explain what it protects. Do not duplicate lifecycle rules here; record and evolve that provenance under [Test Lifecycle Management](test-lifecycle-management.md).

## When automated RED is unavailable

Use the narrowest repeatable contract probe, script, fixture, or characterization that can fail before the change and pass after it. If no pre-change failure can be observed:

- do not label the work strict TDD;
- state why RED was unavailable;
- preserve other before/after evidence;
- use the verification owner to report the resulting evidence limit.

Manual exploration may discover behavior, but it is not a durable regression test until encoded in a repeatable check.

## Completion evidence

Before claiming the TDD slice complete, confirm:

- the behavior contract and exclusions were written before implementation;
- RED was run and failed for the intended reason, or the exception was accurately reported;
- GREEN is general enough for the stated contract and no broader;
- refactoring occurred only after GREEN;
- real collaborators or controlled doubles match the risk boundary;
- focused, affected, public-surface, and canonical statuses are reported through the verification owner as applicable;
- changed tests have lifecycle provenance and a deliberate retention decision.
