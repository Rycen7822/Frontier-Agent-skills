# Real Runtime Stability Loop

Use this recipe when confidence must come from repeated execution of a representative real task through the product's actual user-facing runtime, especially when fixes must be installed or deployed before they can be judged. Typical targets include plugins, CLIs, services, agent workflows, benchmark runners, pipelines, and integrations.

## Contents

- [Owner boundaries](#owner-boundaries)
- [Runtime loop card](#runtime-loop-card)
- [Evidence ledgers](#evidence-ledgers)
- [Loop sequence](#loop-sequence)
- [Long-run control](#long-run-control)
- [Exit contract](#exit-contract)
- [Closeout shape](#closeout-shape)

## Owner boundaries

Do not load it for an ordinary one-shot smoke, a unit-test repair, or a request that does not require runtime hardening. This recipe coordinates existing owners; it does not replace them:

- [Authority and Scope](authority-and-scope.md) owns mode, edit boundaries, protected paths, dirty-worktree handling, and side-effect authorization.
- [Systematic Debugging](systematic-debugging.md) owns reproduction and root-cause sequencing.
- [Test-Driven Development](test-driven-development.md) owns RED/GREEN/REFACTOR for behavior changes.
- [Verification Discipline](verification-discipline.md) owns evidence labels, gate integrity, failure classification, and completion claims.
- [Plugin Installed Surface](plugin-installed-surface.md) owns source-to-installed provenance and fresh-host proof for plugins.
- [Workspace Artifact Hygiene](workspace-artifact-hygiene.md) owns scratch, ledgers, snapshots, and cleanup.
- [Observability Instrumentation](observability-instrumentation.md) owns progress and health semantics for long-running workflows.

## Runtime loop card

Before the first round, establish a compact, durable loop card when the work will span multiple rounds, installations, or context windows. Use the repository's established state or worknotes location; do not invent loose root files when project instructions name another location.

Record:

| Field | Required decision |
|---|---|
| Product and source | System under test, source root, revision, and dirty-state boundary. |
| Runtime target | Installed copy, package, service, container, profile, or deployment being exercised. |
| Representative task | Real user outcome and exact public entrypoint. |
| Required surfaces | Lifecycle stages, commands, endpoints, tools, recovery paths, and outputs that must be exercised. |
| Scope boundary | Allowed edits, protected inputs, third-party systems, user data, and explicit exclusions. |
| Activation path | Canonical build/install/deploy/reload command and proof that the candidate became active. |
| Round oracle | Observable success criteria and evidence artifacts. |
| Clean-round target | Number of consecutive full rounds with no new product issue; default to three only for explicit multi-round stability hardening. |
| Stop boundary | Cost, quota, time, external dependency, destructive action, or authority limit that halts the loop. |

Keep the card current when the user changes the goal, environment, or exit condition. It is an index, not a transcript.

## Evidence ledgers

Reuse project-native issue and progress records. If none exist and durable state is warranted, keep task-owned ledgers under the location selected by the loop card.

For each runtime issue, record:

```text
issue id and first-observed round
real task, entrypoint, and exact symptom
severity and failure classification
product fault rationale or external boundary
owner seam and supported root cause
fix status
focused proof and same-path rerun required
```

For each round, record:

```text
candidate revision and active runtime provenance
real command or procedure
surfaces exercised and surfaces not reached
new product issues and non-product failures
fixes activated since the prior round
result, artifacts, and original command status
next action or exit judgment
```

Do not store secrets, credentials, private tokens, or unrestricted runtime dumps in the ledgers. Preserve only the evidence needed to resume and audit the loop.

## Loop sequence

Repeat the following sequence until the exit contract is satisfied or a declared boundary blocks progress.

### 1. Reconfirm the active candidate

- Re-observe source revision, scope, and relevant dirty paths.
- Verify the runtime target's version, content provenance, configuration, registration, process freshness, and health.
- Build, install, deploy, reload, or restart only through an authorized canonical path.
- After every fix, prove that the changed candidate replaced the previously active runtime before judging the rerun.

Source tests do not establish installed provenance. For copied or installed plugins, follow the complete source-to-build-to-package-to-install-to-fresh-host sequence in [Plugin Installed Surface](plugin-installed-surface.md).

### 2. Execute the representative real task

Use the route a real user or downstream system uses: CLI, API, UI, plugin command or tool, scheduler, benchmark runner, or integration boundary. Internal function calls are supporting evidence unless they are themselves the public contract.

Exercise the lifecycle named in the loop card. Depending on the product, that can include startup and configuration discovery, task intake, planning, worker or tool dispatch, state persistence, resume or idempotency, report or artifact collection, independent verification, finalization, and designed error handling.

Do not weaken the task, verifier, gate, or environment to produce a green result.

### 3. Observe and classify failures

Evaluate behavior, not just process exit:

- parameter or schema mismatch;
- stale installation, discovery, or configuration;
- hidden or swallowed failure;
- corrupt or unrecoverable state;
- missing health or progress signals;
- misleading output or overclaimed final reports;
- resource, latency, or retry behavior that prevents realistic use;
- repeated agent or tool failure caused by unclear public guidance.

Use the classifications in [Verification Discipline](verification-discipline.md). A hard domain task, reward miss, unavailable dependency, permission boundary, harness defect, and product fault are different outcomes. Do not patch product behavior merely because an external oracle or benchmark score is unfavorable.

Record a product issue before fixing it. Continue the round when the issue is non-blocking and further execution remains valid; stop the round when continuing would corrupt evidence, waste material resources, or cross a declared boundary.

### 4. Diagnose and patch the owner seam

- Reproduce and trace the failed public path to its owning code, configuration, installer, documentation, or state transition.
- Produce meaningful RED or characterization evidence under the TDD owner.
- Patch the smallest coherent owner seam; avoid shadow modes, broad fallbacks, and speculative compatibility layers.
- Run focused and affected-area gates with their original statuses preserved.
- Update the issue record with the supported cause and the exact rerun oracle.

For a non-trivial fix, create or update an implementation plan through `writing-plans`; include activation and same-path runtime rerun as explicit tasks.

### 5. Activate and rerun

- Rebuild and reinstall, redeploy, reload, or restart when the real runtime does not execute directly from source.
- Reconfirm active provenance in a fresh process or loader when discovery is startup-bound.
- Rerun the same public path that exposed the issue before broadening the round.
- Mark the issue verified only when focused proof passes and the activated runtime succeeds on that path or reaches a distinct next blocker.

### 6. Judge the round

A clean round requires the full scoped real task to complete through the intended runtime with no newly discovered product issue. It does not prove untested environments or arbitrary future tasks.

End each round with one outcome:

- `clean_round`: all scoped surfaces completed and no new product issue appeared;
- `fix_required`: a product issue is recorded with an owner and rerun requirement;
- `blocked_external`: an environment, permission, cost, quota, service, or authority boundary prevents a valid conclusion;
- `inconclusive`: evidence is incomplete, stale, or nondeterministic.

Reset the consecutive clean-round count after a product fix or when the candidate revision changes materially. Do not reset it for a clearly external failure that leaves product evidence valid; record the boundary instead.

## Long-run control

- Use bounded retries and backoff. A quiet process is not stalled until process, resource, network, log, state, and output-artifact signals support that conclusion.
- Keep operator-visible round and batch boundaries when the workflow is long or quota constrained.
- Preserve resumable state and artifact identity before interruption.
- Check pending processes, agents, jobs, or sessions before reporting completion.
- Do not use repeated reruns to wash out a deterministic failure or unfavorable benchmark result.

## Exit contract

Claim scoped runtime stability only when:

1. The representative task completed through the actual public runtime and every required surface was exercised or explicitly excluded.
2. Every discovered product issue was fixed, activated, and verified on the same real path, or remains as a clearly reported boundary.
3. Required focused, affected-area, public-surface, and canonical gates have valid evidence.
4. The active install or deployment provenance matches the final candidate.
5. The clean-round target is met when the request requires repeated stability proof.
6. Durable state is current enough for another engineer to resume without chat history.

Report real-runtime proof, code-test-only proof, unverified surfaces, baseline failures, and external blockers separately. Treat any absolute-confidence request as a scoped confidence target bounded by the declared task, product, environment, and evidence; never claim universal future reliability.

## Closeout shape

Lead with whether the scoped confidence target was met. Then report:

- round count and outcomes;
- issues, owner seams, fixes, and same-path rerun evidence;
- final source revision and active runtime provenance;
- real entrypoints and surfaces exercised;
- focused, affected-area, public, and canonical gate results;
- remaining external, unverified, and out-of-scope boundaries.
