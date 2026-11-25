---
name: test-behavior
description: Use when preparing to write or modify tests or code/scripts that check software behavior, including temporary scripts, inline checks, reproductions, debug probes, smoke/install/migration checks, benchmarks, fixtures and mocks. Apply before editing those checks to decide necessity, timing, meaningful expectations and temporary versus permanent placement. Also use to review directly affected tests when a task removes or replaces a behavior contract, completes a migration or ends compatibility obligations. Requirements and architecture decisions stay with the main workflow; design discussion and ordinary implementation alone do not call for this skill. Running existing checks alone does not require new tests.
license: MIT
metadata:
  version: 1.0.0
  author: Frontier Agent Skills
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, testing, verification]
    category: software-development
    related_skills: [software-quality-workflows, debugging, runtime-verification]
---

# Test Behavior

Choose checks that resolve a concrete uncertainty or add missing protection for the current task. Respect explicitly requested tests and project conventions. Verification, writing a check, and retaining a permanent test are separate decisions; a code edit alone does not justify all three.

## When to apply

Use this skill as soon as you consider writing or changing code to test, reproduce, probe, validate, verify, compare, benchmark, or smoke-check software behavior. Apply it before the first code or script edit, even without a named skill request or an SQW invocation. Do not wait until adding a permanent test or seeing a failure.

This includes formal tests, one-off scripts, installation and migration checks, harness or mock checks, inline Python or shell code, here-docs, REPL snippets, and wrappers or fixtures created for a check. Judge by purpose, not filename, directory, language, framework, assertion syntax, or whether the artifact is temporary.

Also apply when the current task removes or replaces a behavior contract, completes a migration, or ends compatibility or a migration obligation, even if no test edit is planned and no test has failed. Inspect directly affected tests and fixtures as part of that change, then preserve, migrate, merge, or retire protection according to the lifetime rules. Completing a migration calls for checking which obligations continue; a version bump alone does not end them.

Running an existing runner or specified check does not by itself call for new test code. If that work leads you to write a helper, wrapper, assertion, fixture, or reproduction, apply these decisions before authoring it.

Apply these decisions alongside the workflow handling implementation, diagnosis, or verification. A generic suggestion to "add tests" does not settle necessity or permanent placement; honor explicit user or project delivery requirements while deciding valid protection here.

## Decide whether to write

Identify the remaining behavior or risk question and the observation that would resolve it; for an assertion, name a plausible error it should reject. Reuse valid results, suitable existing tests, fixtures, and runners when they answer that question. Extend the nearest useful test or write a new check only when it adds needed discrimination or protection. Choose the least costly sufficient observation; creating a temporary probe can be cheaper than running an unsuitable suite.

Documents, formatting, confirmed simple equivalent edits, and already-covered fixes usually need no new test. Check relevant executable examples, bindings, effects, or consumers when they create uncertainty. Do not invent test quotas per function, file, branch, or task, or omit necessary verification merely because no new test is needed.

## Choose the time

For a bug with a clear independent expectation and a cheap valid reproduction, prefer confirming the target failure before fixing it, then check the repair under the same conditions. If setup or the cause is unclear, diagnose those first with a bounded temporary probe. If the expectation is unclear, establish the requirement before writing a normative assertion.

Use a flexible order when an existing reproduction suffices or creating one first is disproportionate. Preserve or recover a controlled baseline if a later comparison needs it. After a coherent edit, run the relevant check and nearest affected controls. Do not force global TDD, artificial RED, a test after every small edit, or a full suite without a relevant reason; honor an explicitly requested method or check scope.

## Build a meaningful check

Derive expected behavior from requirements, justified examples, an independent reference, or a contract-supported property. Read implementation to locate paths and reuse setup; its observed output, a self-generated patch, a specification derived from suspect code, or a second agent agreeing with it is not independent correctness evidence. Characterization can record uncertain current behavior without declaring it required.

Use inputs and fixtures consistent with the contract and exercise the target consumer or state transition. Unit, integration, mock, negative, property, differential, snapshot, smoke, and real-service checks can all be useful. Choose inputs that distinguish relevant behavioral conditions rather than surface variants.

For harness or mock checks, confirm the substitute is bound at the actual consumption point, runtime types and synchronous or asynchronous behavior match the protocol, and required state or history is established. Absence assertions need a real opportunity for the forbidden effect. A round trip or a difference between candidates needs an independent basis before it can establish correctness. Exact wording, order, structure, or call counts need a real protection obligation.

For consequential acceptance gaps, check that the verifier rejects a plausible error and does not reject a correct alternative. Use a small counterexample when useful, not mandatory mutation, exhaustive matrices, extra agents, or repeated real-model calls.

## Reject invalid evidence

Confirm that execution reached the intended behavior. Missing dependencies, uncollected targets, bad fixtures, wrapper failures, and infrastructure errors are diagnostics, not target RED or a passing result. A source-induced exception can be valid behavioral failure; classify by cause, not exit code or assertion name. Coverage, a test file, candidate separation, and red-to-green are signals rather than sufficient correctness proofs. Report missing execution or results as unverified.

Before changing product code, expectations, or setup in response to a failure or conflicting result, identify the cause as product behavior, the expectation, setup, an unrelated issue, or unknown. For unknown causes, choose the smallest independent observation that can distinguish them. If candidates all pass or all fail, that check does not distinguish them in this comparison; it does not rule out a fault location or justify deleting valid protection.

Compare complete candidate changes under comparable initial conditions. Preserve history required by the scenario and avoid leakage from unintended workspace changes. Keep confirmed comparison standards fixed within a round; changing a test, fixture, or environment requires rebuilding affected evidence.

Never invent an unsupported expectation or impossible state to manufacture a defect. Test invalid inputs when their rejection or handling is part of the requirement. Never change expectations, skip failures, or delete unique valid protection merely to make the current patch green. Update an incorrect or retired expectation when independent requirements justify it, preserving remaining protection.

## Decide lifetime and retirement

Choose initial lifetime and placement before writing, respecting requested delivery. By default, put one-off diagnosis, candidate comparisons, installation probes, and migration acceptance checks in the project's temporary area, defaulting to `.work`, outside normal test discovery and permanent delivery. A useful temporary check does not automatically deserve promotion.

When the task requests tests in the project suite or regression tests or bug reproduction tests (BRTs) delivered with a patch, deliver them with justified expectations and valid execution. A request to test or verify a change, or produce a checking script, does not by itself require placement in the permanent suite. Do not discard requested suite protection as a temporary tool.

Retain a permanent test by your own choice only when it adds missing protection for a continuing contract or credible recurrence risk, has a justified expectation, and has reasonable maintenance and execution cost. Prefer extending existing protection. Do not add duplicate, implementation-mirroring, incidental-text, or migration-completion-only tests to the permanent suite without that justification. Continuing support for old data, clients, retryable migrations, or multiple versions can justify permanent protection.

When the current task removes or replaces behavior, completes a migration, or ends compatibility, inspect directly affected tests and fixtures in the same scope. Preserve or migrate continuing protection, merge duplicates, and delete checks whose sole obligation has ended. A new version number or a failing test alone is not retirement evidence. Do not expand this into unrelated suite cleanup or require a retention registry and per-test reports.

## Stop with sufficient evidence

Reuse evidence while relevant behavior, inputs, dependencies, environment, state, and consumers remain valid. Recheck affected claims when these conditions change or a new observation can alter the conclusion. Preserve the outputs and execution conditions needed to reuse costly checks.

When shared state or caches, import effects, dynamic dispatch, or external callbacks are relevant to the change, an unchanged direct file or an unobserved historical call does not prove no impact. Follow the affected consumer and select the nearest sufficient check or report the evidence gap. A check not selected for this run is not thereby obsolete.

Bound costly or open-ended test generation, repair, and candidate comparison by the unresolved question and task resources. Consider setup, returned output, model calls, retries, and retained maintenance cost, not command count alone. A new detail per attempt does not by itself justify continuing.

Repeating an unchanged, nondiscriminating check needs a concrete information reason, such as restoring missing output; otherwise change the observation or stop. Stop when evidence is sufficient or further exploration is no longer justified; remaining unavailable evidence requires an honest limit, not an endless loop. Delegation remains optional.

For a concrete handoff to the surrounding workflow, read [workflow ownership](references/workflow-ownership.md) only when needed.
