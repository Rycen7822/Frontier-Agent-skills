# Product, API, Accessibility, and Privacy Review

Load this rubric only for user-facing behavior, UI flows, public or internal consumer contracts, SDK/tool schemas, accessibility, user-data handling, or release and migration behavior.

Use `references/review-result-schema.md` for findings. Consult `references/api-interface-design.md` and `references/security-hardening.md` for implementation policy, and `references/verification-discipline.md` for evidence. This rubric adds domain review questions only.

## User outcome

- State the intended user outcome and the acceptance path affected by the change.
- Check error, empty, loading, cancellation, and recovery states as applicable.
- Ask for a screenshot, browser/runtime observation, demo, or local behavior proof only when code evidence cannot establish the changed experience.
- Confirm that new dependencies and components follow established product and design-system conventions.

User-visible behavior that is plausibly wrong and cannot be decided from available evidence needs a concrete finding; optional presentation polish does not.

## API and consumer contract

- Keep endpoint, method, status, pagination, authentication, error, idempotency, and version semantics internally consistent.
- Update the owning specification, schema, generated consumer, documentation, and examples together when they share one contract.
- Identify compatibility impact. A breaking change needs explicit acceptance and a suitable versioning, deprecation, migration, or release path.
- Keep examples executable and free of secrets or private data.

Silent consumer breakage, implementation/spec drift, or inconsistent authorization and error behavior are material risks.

## Accessibility

For changed user interfaces, inspect the applicable subset of:

- keyboard access, focus order, and visible focus;
- semantic names, labels, headings, alt text, and link purpose;
- screen-reader state and dynamic announcements;
- contrast and meaning that does not depend on color alone;
- automated checks plus a manual spot check when the interaction risk warrants it.

Ground findings in the changed path and user impact. Do not mechanically load this checklist for an internal non-UI edit.

## Privacy and data lifecycle

- Identify private or sensitive data collected, stored, logged, displayed, shared, exported, retained, deleted, or used for training/evaluation.
- Minimize data and enforce the applicable access, consent, audit, retention, and deletion boundaries.
- Use synthetic or de-identified examples where real records are unnecessary.
- Check that newly exposed fields, diagnostics, caches, analytics, and model inputs do not bypass the owning privacy contract.

Private-data leakage, missing authorization, unclear material collection, or uncontrolled lifecycle changes require specialist or owner attention. When that decision cannot be made by a generic reviewer, mark it non-code-fixable and state the exact qualified review needed.

## Risk-matched completion

Depending on the changed surface, completion evidence can include acceptance criteria, focused behavior proof, updated specs/SDK/docs, accessibility evidence, diagnostics for new failure modes, and migration or rollback evidence. Require only the subset needed for a safe judgment; do not invent a heavy product process for a small internal change.
