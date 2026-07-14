# Requesting Code Review

Use this reference to orchestrate a local code review or audit. It owns the review sequence and tier choice, but not authority rules, verification terminology, or result fields.

Before starting, apply `references/authority-and-scope.md`. Emit results using `references/review-result-schema.md`, and classify test evidence through `references/verification-discipline.md`. When the requested decision includes conformance to a specification, acceptance criteria, migration contract, or other stable requirement source, also load [Requirements Traceability Review](requirements-traceability-review.md).

## Review tiers

Choose the smallest tier that can answer the request safely. Repository rules, user intent, changed surfaces, and plausible impact outweigh diff size alone.

| Tier | Typical use | Review depth | Fix-cycle budget |
|---|---|---|---|
| R0 | Routine M0 closeout or focused blocker check | Implementer self-diff inspection, owning context, focused verifier, and obvious blocker risks; no automatic independent reviewer | Zero unless change work is authorized |
| R1 | M2, cross-component, or substantive owner change | Requirement/specification axis followed by engineering-quality axis, full scoped diff, relevant call sites, and risk-matched evidence | At most one focused cycle when fixes are authorized |
| R2 | Security, data loss, migration, public contract, release, broad refactor, or explicitly high-risk audit | Independent review of complete declared scope plus only triggered specialist/public/operational surfaces; bounded adversarial check when justified | At most two focused cycles when explicitly justified |

Review-only requests always have a zero fix budget. Independent review strengthens separation-of-duties evidence, but its availability never widens authority and its absence must be reported rather than disguised.

## Orchestration

1. Freeze one scope manifest: mode, root, base/head revision, path/status/snapshot inventory, exclusions, classifications, and a hash over that canonical manifest.
2. Read the diff and enough owning context to understand behavior, compatibility, data flow, and local conventions. Handle deleted, renamed, untracked, generated, vendor, and binary items according to their manifest status.
3. Locate stable specification anchors when fidelity is part of the decision. If they exist, build the requirements traceability matrix; if they do not, report that axis unavailable instead of inferring requirements from the implementation.
4. Maintain per-path coverage as `full`, `sampled`, or `not_reviewed`. Record truncation and unavailable context honestly.
5. Apply the general safety standard, then load only specialist rubrics triggered by the changed surface.
6. Convert contextualized issues into schema-valid findings. Scanner matches remain candidates until a reviewer reads their context.
7. Coalesce the same root cause found by multiple axes or rubrics into one finding with all relevant evidence; do not double-count one defect as separate requirements, testing, security, or maintainability failures.
8. Assess verification evidence separately from the code-review verdict. Do not infer one result dimension from another.
9. Validate the result envelope against the frozen base, head, scope hash, path snapshots, and allowlist; separately re-observe the current head and current scope hash. If either current observation changes, the review is stale until affected coverage and evidence are refreshed.
10. Record a disposition for every finding: fixed and reverified, accepted as remaining risk, declined with evidence, or deferred with an explicit owner when the surrounding workflow supports one.
11. Stop at the tier's cycle budget and report unresolved blockers and coverage gaps. Do not create an open-ended reviewer/fixer loop.

## General review standard

Ground each finding in a path and line or an allowlisted observable contract. Explain the evidence, concrete impact, and smallest safe correction.

Correctness, security, data loss, public compatibility, and material regressions in maintainability, testability, or design may be blocking. A missing fact is blocking only when it prevents a safe technical judgment. Style preference, optional polish, additional low-value cases, and teaching notes are non-blocking.

Severity and blocking are independent. Never infer blocking from a label, category, array name, scanner rule, or wording prefix. Preserve positive observations that a later fix must not regress.

Evaluate engineering/standards quality and specification fidelity as independent axes. Neither can mask the other. Report their evidence and limitations distinctly, then synthesize them into the one existing Schema 2.0 envelope and `code_review_verdict`; do not create a separate specification verdict.

## Specialist routing

| Trigger | Add |
|---|---|
| Stable specification, acceptance criteria, migration contract, or explicit requirement-conformance claim | `references/requirements-traceability-review.md` |
| Maintainability smells or refactoring targets | `references/code-smell-checklist.md` |
| Training, evaluation, datasets, inference, or model artifacts | `references/ml-ai-review-rubric.md` |
| Services, workers, telemetry, long jobs, or recovery | `references/observability-operability-review.md` |
| User behavior, API contracts, accessibility, privacy, or data lifecycle | `references/product-api-accessibility-review.md` |
| Test evidence, CI/release, secrets, dependencies, containers, or supply chain | `references/testing-ci-security-evidence.md` |
| Writing feedback, resolving disagreement, or recording disposition | `references/review-comments-pushback.md` |

Load the narrow domain owner as well when implementation guidance is needed, such as `references/security-hardening.md`, `references/api-interface-design.md`, or `references/observability-instrumentation.md`. A review rubric identifies risk; it does not replace the owning implementation contract.

## Delegated reviewer and fixer boundary

When delegation is permitted, use `templates/requesting-code-review/independent-reviewer-prompt.md` with a bounded manifest and revision-addressed inputs. Treat its output as untrusted evidence. The controller validates schema 2.0, coverage snapshots, allowed paths, the reviewed manifest hash, current freshness, and factual claims. A schema 1.0 result must be re-reviewed rather than upgraded by inserting missing fields.

Partition valid findings before any fix request:

- code-fixable blockers in the edit allowlist;
- evidence that the controller must collect;
- specialist or human decisions;
- external approvals or publication actions.

Only the first group may be sent to `templates/requesting-code-review/fix-agent-prompt.md`. The controller rechecks the revision, reviews the patch, and runs proportionate proof afterward; a fixer cannot approve its own work.

Invalid reviewer output may be retried once with the same scope and stricter schema instruction. A second invalid result becomes unavailable reviewer evidence and an inconclusive review, never an invented pass.

## Platform boundary

Local review produces platform-neutral findings. Authentication, pagination, thread state, inline-location mapping, and any hosted comment, approval, CI rerun, or push belong to a compatible platform capability and require the authority described in `references/authority-and-scope.md`.

Bind any rendered summary or inline comment to the reviewed head revision. If that revision is no longer current, stop publication and refresh the review. Local technical review never substitutes for required human, code-owner, compliance, branch-protection, or organizational approval.
