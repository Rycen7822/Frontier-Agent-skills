# Systematic Debugging

Use this reference for unexpected behavior, failing tests or builds, regressions, integration failures, and performance or runtime anomalies. It owns the diagnosis and bugfix state machine. It does not own authorization or completion-gate policy.

## Contents

- [Authority and ownership](#authority-and-ownership)
- [Five request routes](#five-request-routes)
- [Root-cause workflow](#root-cause-workflow)
- [Authoritative bugfix state machine](#authoritative-bugfix-state-machine)
- [Blocked and live-system cases](#blocked-and-live-system-cases)
- [Failed hypotheses and architecture signals](#failed-hypotheses-and-architecture-signals)
- [Closeout](#closeout)

## Authority and ownership

Classify the request mode, allowed scope, side effects, and escalation boundary with [Authority and Scope](authority-and-scope.md) before running an experiment. Select and report gates through [Verification Discipline](verification-discipline.md).

This file owns only:

- the order from symptom to supported root cause;
- the transition from diagnosis to an authorized repair;
- the evidence required to reset a failed hypothesis.

The authority owner governs whether a probe or repair is permitted. Persistent product instrumentation is a separate planned change, not an incidental diagnostic side effect.

## Five request routes

| Request shape | Route | Required stopping point |
|---|---|---|
| Report or review | Inventory the supplied evidence and identify gaps within the report-mode boundary set by the authority owner. | Findings and evidence limits. |
| Diagnose only | Reproduce, localize, trace, and test hypotheses within the diagnose-mode boundary set by the authority owner. | Supported root cause or an explicit inconclusive result. |
| Fix an unmodified baseline | Follow the full bugfix state machine below. | Verified repair within the authorized scope. |
| Finish an existing patch | Preserve the patch, characterize its current behavior, then locate the remaining gap. | Improve in place; never discard the existing implementation merely to recreate test order. |
| Feature, refactor, or migration | Use the applicable planning and TDD route. Return here only for unexplained failures. | The owning workflow’s stopping point. |

## Root-cause workflow

### DBG-01 — Establish a reviewable cause

Do not stack speculative patches or anchor on the first plausible story. List a small ranked portfolio of plausible causes, ordered by discriminatory value and test cost. Select exactly one active hypothesis and one controlled variable for the next experiment:

> The observed symptom occurs because cause C changes boundary B, which should be visible as evidence E.

Record what supports the claim, what would disprove it, and what remains unknown. A supported causal explanation is enough to proceed; do not pretend certainty that the evidence cannot justify.

### DBG-02 — Capture the exact symptom and reproduction

- Read the complete error, stack, exit status, and immediately relevant logs.
- Record the smallest repeatable input, environment assumptions, and command or user path.
- Distinguish the target failure from setup, fixture, import, permission, environment, or harness failure.
- If reproduction is intermittent, record frequency and controlled variables instead of guessing.

A command that never reaches the target behavior is not a valid reproduction of that behavior.

### Feedback-loop quality and minimisation

Treat the reproducer as an engineered diagnostic instrument. Choose the narrowest loop that can observe the exact symptom: a focused test, CLI or HTTP invocation, browser path, recorded replay, property harness, differential comparison, or revision bisection. Record a named command or procedure that another agent can run.

A useful loop is:

- **symptom-specific:** its oracle distinguishes the target defect from setup or unrelated failures;
- **repeatable:** deterministic when possible, or statistically characterised with trial count and failure rate;
- **discriminating:** its result separates the active hypothesis from plausible alternatives;
- **fast enough:** cheap enough for controlled iteration without weakening the symptom or bypassing the real boundary;
- **safe and owned:** task-scoped, bounded, and runnable without undeclared production or external-state effects.

Preserve the original reproduction unchanged as a control. Minimise a copy by removing one input, step, configuration value, dependency, timing condition, or concurrency factor at a time. After every reduction, use the same oracle to prove the original failure mechanism remains. The conditions that cannot be removed are evidence; a smaller example that produces a different failure is not a successful minimisation.

### DBG-03 — Check change history without disturbing it

Inspect relevant recent changes, configuration, dependency metadata, and the current worktree. Treat user and concurrent changes as evidence and protected state. Use read-only history and diff inspection by default; any restoration or discard decision belongs to the authority owner.

### DBG-04 — Observe component boundaries

For each relevant boundary, compare:

| Boundary evidence | Questions |
|---|---|
| Input | Is the value, type, encoding, identity, or version already wrong? |
| Output | Does the component preserve its documented contract? |
| Configuration | Which effective value was loaded, and from which source? |
| State | Which store, process, cache, or artifact is actually being read? |
| Failure | Is the error transformed, swallowed, retried, or misclassified? |

Prefer an external or task-scoped probe. If evidence must be added to production code, treat that instrumentation as a separate authorized change with its own tests and privacy review.

### DBG-05 — Trace data to its origin

Follow the bad value backward through callers, conversions, serialization, routing, and state ownership until reaching the earliest boundary where actual and expected behavior diverge. Do not stop at the line that finally throws if the invalid state was created earlier.

### DBG-06 — Compare a working path

Find a working example governed by the same contract. Read the complete semantic unit, then list every relevant difference: input shape, configuration, lifecycle, dependency version, ordering, ownership, and error path. Do not assume a small-looking difference is irrelevant before testing it.

### DBG-07 — Test one hypothesis minimally

Change one controlled variable or add one task-scoped observation. Predict the result before running it. A hypothesis experiment must:

- preserve unrelated work;
- have the smallest practical side-effect surface;
- distinguish the hypothesis from plausible alternatives;
- be reverted or incorporated deliberately after the result.

An experimental patch is evidence, not automatically the final repair.

## Authoritative bugfix state machine

This sequence resolves the plan-first, root-cause-first, and RED-first conflict:

1. **Reproduce and localize.** Complete DBG-01 through DBG-07 far enough to support a root-cause hypothesis.
2. **Decide repair scope.** If the supported repair changes architecture, ownership, public contracts, migrations, schemas, or multiple components, complete the applicable plan/design audit now. A small repair can proceed directly.
3. **Create a meaningful regression RED (DBG-08).** Exercise the user-visible behavior or contract gap. Run it and confirm it fails for that gap, not because a helper, fixture, import, or harness is missing.
4. **Repair the owning seam.** Make the smallest general change that addresses the supported cause. Avoid unrelated cleanup.
5. **Run proportional proof (DBG-09).** Prove the focused regression, affected behavior, and any real public surface implicated by the fault. The verification owner decides which broader and canonical gates apply and how unrun gates are reported.
6. **Close the evidence loop.** Re-run the original reproduction and confirm the causal boundary now behaves as predicted.

For an existing patch, insert a characterization step before step 1: establish what the patch currently preserves, what remains broken, and which changes belong to the user. A characterization test may pass as a baseline; the later regression test must still demonstrate the unresolved behavior gap.

Public adapters deserve direct proof. If runtime internals pass but a CLI, protocol wrapper, schema, preflight, installed entrypoint, or other public path fails, the repair is incomplete. Use PAT-05 in [Test Patterns](test-patterns.md).

## Blocked and live-system cases

### No canonical test reaches the behavior

Confirm the documented setup and runner once. If the target remains unreachable, use the narrowest repeatable characterization or public-path probe available and label its evidence accurately under the verification owner. Do not rename harness failure as a product RED, and do not claim an unrun canonical gate passed.

### Nondeterministic behavior

Control seed, clock, concurrency, input, resource limits, and external dependencies where practical. Before a repeated experiment, declare a bounded trial/time budget and the decision rule appropriate to the observed base rate: what result retains a factor, weakens a hypothesis, or remains inconclusive. Record trial count, failure count, failure rate, and the controlled variables. There is no universal run count; when the budget cannot distinguish the alternatives, report the statistical limit instead of treating absence as proof. A single passing rerun does not disprove an intermittent defect. Bounded stress may amplify a known mechanism, but an unbounded load run or a changed symptom is not stronger evidence.

### Live process or debugger evidence

Use [Debugger-Assisted Diagnosis](debugger-assisted-diagnosis.md). Prefer a controlled task-owned launch. If ownership, host policy, or safe isolation cannot be established, continue with logs, traces, a local reproduction, or other non-invasive evidence and report the limitation.

## Failed hypotheses and architecture signals

### DBG-10 — Reset the model before widening the repair

When a repair attempt fails:

1. preserve the new evidence;
2. revert only task-owned experimental changes;
3. state why the previous hypothesis was weakened;
4. return to the earliest unsupported boundary;
5. form a materially different hypothesis.

Repeated failure is a signal to reassess, not a magic numeric rule. Re-plan when attempts reveal shared state in new locations, require widening adapters or modes, move symptoms between components, or show that the proposed ownership boundary cannot express the contract.

## Closeout

Report:

- symptom and exact reproduction;
- root-cause hypothesis, supporting evidence, and confidence boundary;
- repair location and why it owns the behavior;
- regression RED and focused result;
- affected and public-surface evidence selected through the verification owner;
- canonical gate status, including not-run or blocked items;
- residual risk, unresolved alternatives, and any cleanup still required.
