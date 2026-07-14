# Verification Discipline

Use this reference to decide what evidence is required, execute canonical gates without losing their status, classify failures, and make completion claims. It is the single normative owner for verification levels and evidence terminology.

## Contents

- [Evidence model](#evidence-model)
- [Applicability matrix](#applicability-matrix)
- [Canonical command integrity](#canonical-command-integrity)
- [Compact output without false success](#compact-output-without-false-success)
- [Failure classification](#failure-classification)
- [Installed and public surfaces](#installed-and-public-surfaces)
- [Completion record](#completion-record)

## Evidence model

Five gates may appear in order; two labels remain orthogonal to those gates.

| Evidence | Meaning | Applicability |
|---|---|---|
| `RED evidence` | The user-visible or contract-level behavior fails for the expected reason before a behavior change | Required for behavior changes when a meaningful before/after distinction can be produced |
| `focused gate` | The smallest test, smoke, contract check, or reproduction proving the changed behavior | Required for code behavior changes |
| `affected-area gate` | Existing checks for touched modules, packages, languages, or dependent seams | Required when nearby behavior can regress |
| `public-surface proof` | Real CLI, API, UI, protocol, artifact, installed copy, or other user path | Required when the change touches that surface |
| `canonical gate` | The repository-, CI-, verifier-, plan-, or user-named landing command | Run when required by the project or warranted by blast radius |
| `ad-hoc evidence` | A temporary probe or scanner that supplements a gate | Never describe it as suite success |
| `baseline delta` | The difference between pre-existing and newly introduced failures, warnings, or flakiness | Record separately from gate status |

RED is not valid when failure comes only from syntax, import, environment, a broken fixture, or a helper that the proposed implementation invented. For an existing implementation that cannot produce a historical RED safely, use characterization and a regression that distinguishes the faulty and corrected behavior; state the evidence shape honestly.

## Applicability matrix

| Change type | Minimum evidence | Conditional additions |
|---|---|---|
| Documentation or metadata | Static contract checks and targeted reread | Official metadata validator when available |
| Internal behavior fix | RED, focused, affected-area | Canonical gate according to blast radius |
| New behavior or refactor | Design/plan when needed, RED, focused, affected-area | Public and canonical gates for exposed surfaces |
| Public API, schema, protocol, CLI, UI, or package | RED/contract proof, focused, affected-area, public-surface | Canonical compatibility or migration gate |
| Security, data migration, release, or installed runtime | Risk-specific negative proof plus relevant gates | Rollback, clean install, external approval, or operational proof |
| Performance optimization | Reproducible baseline, behavior parity, equivalent after-measurement | Broader load or resource gate when the result warrants it |

Do not require a full suite, a pristine historical baseline, or zero warnings solely because a reference uses strong language. Run the project's actual canonical gate when it exists and is applicable. If a broad gate is infeasible, report `not_run` with the reason and the narrower evidence actually obtained.

## Canonical command integrity

- Execute the canonical command itself; do not replace it with a similar command without naming the substitution.
- Preserve the original process return code, stdout/stderr log, command, working directory, relevant version, and duration.
- Do not connect the command to a display truncator or formatter whose status can replace the command's status.
- Do not add an unconditional success fallback, swallow exceptions, or infer success by searching output for a favorable word.
- When a user, plan, repository, CI job, or verifier names an exact command, run it once when feasible before inventing an alternative.

Project-local command rules remain authoritative. If a wrapper is the canonical project entrypoint, use it; if a wrapper is merely cosmetic, keep the underlying result independently observable.

## Compact output without false success

Output volume and execution status are separate concerns.

1. Capture the original return code before rendering a summary.
2. Keep the complete log in a scoped artifact when it is needed for diagnosis or audit.
3. On success, report a compact command/result/count/duration summary.
4. On failure, report only the command, original return code, first actionable root-cause slice, failed test or rule identifiers, and full-log location.
5. If summary rendering itself fails, report that as a renderer failure without changing the gate result.

Both a short failure and a failure with hundreds of context lines must remain failures. A missing error keyword does not turn a non-zero result into success.

## Failure classification

Before modifying product code, classify a failed check:

- `product_failure`: reproducible behavior owned by the changed product.
- `harness_gap`: the test, adapter, fixture, or verifier cannot exercise the intended contract.
- `environment_unavailable`: missing service, runtime, credential, network, hardware, or compatible platform.
- `permission_denied`: the required operation exceeds current authority.
- `baseline_failure`: the same failure predates the scoped change.
- `stochastic_or_flaky`: the result is not stable enough to support a product conclusion.

Static scanners produce candidates, not confirmed findings. A validator must also prove it can fail for the intended reason; a permanently green self-check is not conformance evidence.

## Installed and public surfaces

Source-tree tests do not prove a built artifact, installed copy, fresh process, registration layer, generated client, browser runtime, or protocol surface. When such a surface is in scope:

1. Identify the source, build/package, installed/registered, and public layers separately.
2. Verify provenance and version at the layer users execute.
3. Exercise the smallest real public path from a neutral working context.
4. Record cache, process, port, state-root, and cleanup conditions.
5. Distinguish implementation failure from stale installation or harness mismatch.

## Completion record

For each applicable gate, record:

```text
gate
command or procedure
result and original return code
scope/revision
evidence artifact or concise observation
```

Also list gates that were not applicable or not run and why. Record `ad-hoc evidence` and `baseline delta` separately. If any required async review, blocker audit, or canonical result is pending, status is interim. If evidence is insufficient, return `inconclusive` rather than a guessed pass.
