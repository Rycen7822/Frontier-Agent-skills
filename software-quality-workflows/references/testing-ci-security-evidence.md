# Testing, CI, Security, and Release Evidence Review

Load this rubric when review readiness depends on test selection, CI/CD changes, release evidence, secrets, dependencies, containers, licensing, or supply-chain risk.

Verification levels and command integrity belong to `references/verification-discipline.md`; security implementation policy belongs to `references/security-hardening.md`; result meanings belong to `references/review-result-schema.md`. This rubric identifies evidence relevant to the reviewed risk without redefining those contracts.

## Author and scope evidence

A reviewable change should make its purpose, affected behavior, exclusions, evidence, and material migration or rollback assumptions understandable. Use issue, design, completion, or repository criteria when they actually apply.

Missing prose is not inherently blocking. Record an evidence finding only when the absence prevents a safe decision about the scoped change. Screenshots, logs, API examples, benchmark tables, or experiment results are useful when they are the only practical proof of the changed surface.

## Risk-based test selection

| Introduced risk | Evidence to consider |
|---|---|
| Pure parser, transform, or decision rule | Focused public-behavior or unit contract |
| Filesystem, database, network, queue, or pipeline seam | Local integration path with controlled dependencies |
| API, schema, generated consumer, or protocol | Contract snapshot, compatibility case, and real boundary smoke |
| User workflow or deployment path | Representative smoke or end-to-end behavior |
| Retry, cancellation, resilience, or failure handling | Deterministic failure-path proof |
| Performance or capacity claim | Reproducible baseline and comparable after-measurement |
| Notebook used as source | Reviewable execution/export and output hygiene |

Do not require every layer for every change. Ask whether the selected proof would fail for the plausible regression introduced by this diff.

## Test quality

- Prefer behavior and public contracts over private implementation details.
- Extend an existing relevant case before creating another test surface.
- Keep setup isolated and deterministic; avoid real user accounts, uncontrolled external services, wall-clock sleeps, and accidental dependence on developer state.
- Use mocks at true boundaries without turning a test into an assertion about mock configuration.
- Cover representative error and boundary behavior; exhaustive negative matrices need a protocol, safety, or migration reason.
- Distinguish a test that cannot exercise the contract from a product failure.

Tests that would remain green when the product behavior breaks create false confidence and can be material findings.

## Automation and human judgment

Formatting, lint, type, test, and scanner results are inputs to review. They do not decide business logic, architecture, user impact, or approval by themselves. A scanner hit becomes a finding only after contextual inspection.

Local AI review does not satisfy peer, code-owner, compliance, privacy, security, accessibility, or branch-protection approval. Report authoritative approval state only through the schema's separate external-approval dimension.

## CI and release path

- Preserve required build, test, lint, type, security, artifact, and generated-output coverage for the changed surface.
- Keep local reproduction sufficiently aligned with CI to diagnose failures; record environment-only differences.
- Treat a removed or bypassed gate as a behavior change requiring a reason and replacement evidence where needed.
- For deployment-affecting changes, inspect the applicable smoke, migration, rollback, canary, or feature-control path.
- Source-tree success does not prove a built artifact, installed copy, generated client, or fresh runtime; verify the layer users execute when it is in scope.

## Secrets and sensitive data

- Treat repository history and artifacts as potentially visible later.
- Keep credentials, tokens, cookies, authorization material, connection strings, private prompts, and user records out of code, logs, fixtures, examples, screenshots, and build artifacts.
- Prefer the project's scoped secret provider and least-privilege credentials with an operable rotation path.
- Use neutral placeholders that cannot be mistaken for live credentials.
- If exposure is found, distinguish source removal from credential rotation and history/artifact response; do not perform destructive cleanup without separate authority.

Link to `references/security-hardening.md` for threat-specific implementation checks rather than copying its complete checklist here.

## Dependencies, containers, and OSS

- Confirm a new dependency is necessary, maintained enough for the use, compatible with project licensing, and consistent with existing version policy.
- Prefer an already-trusted project dependency or standard capability when it meets the need.
- Inspect lockfile and provenance changes, package scripts, generated binaries, and integrity metadata proportionately.
- Keep container bases and contents scoped to the runtime need; avoid secret-bearing build residue and unnecessary administrative tooling.
- Preserve the project's dependency, container, license, and supply-chain scanning rather than silently disabling it.

## Evidence-gap handling

Separate four outcomes before remediation:

- source defects a scoped code edit can fix;
- evidence the controller must collect or rerun;
- specialist or human decisions;
- external approvals or publication actions.

Only the first group may be marked code-fixable. A missing baseline, unavailable workflow result, absent qualified decision, or unknown approval is not repaired by editing arbitrary code. Report the exact missing evidence and why it changes the safety judgment.
