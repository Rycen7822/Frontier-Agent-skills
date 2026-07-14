# Review Comments and Pushback

Use this reference when presenting findings, responding to an author, or resolving disagreement. It governs communication and the separate finding-disposition ledger; immutable result fields and outcome meanings remain owned by [Review Result Schema](review-result-schema.md).

## Write actionable comments

- Comment on the code or observable behavior, never the developer.
- State what is observed, why it matters, and whether action is required for the current change.
- Connect the request to correctness, user impact, security, compatibility, maintainability, testability, or a documented local rule.
- Offer the smallest useful correction when it clarifies the request, while leaving implementation ownership with the author.
- Ask an open question when intent is genuinely unclear; do not use a question to hide a required finding.
- Keep optional polish visibly non-blocking. Do not make preference sound mandatory.
- Include positive evidence and why it is worth preserving, especially after a strong simplification, test, or response to earlier feedback.

Avoid vague, personal, sarcastic, or absolute wording. A line reference without impact is not actionable, and a large redesign without a demonstrated problem is not proportionate.

## Preserve explanations

If an explanation is necessary for future maintainers, prefer clearer code, a precise name, a contract test, or durable documentation over a review-thread-only answer. If the explanation only corrects the reviewer's missing domain context and normal readers would already understand, accept it without demanding redundant prose.

## Handle pushback

1. Re-read the evidence and the author's argument; they may be right or closer to the domain.
2. Restate the strongest version of their point before responding.
3. If it resolves the risk, withdraw or downgrade the finding and record why.
4. If the risk remains, explain the unresolved impact and the smallest evidence or change that would settle it.
5. If disagreement depends on product, security, privacy, architecture, or organizational ownership, route the exact decision to that owner instead of escalating rhetoric.
6. Record the disposition so the same issue is not repeatedly rediscovered without new evidence.

Do not invent a ticket, owner, synchronous meeting, or hosted comment as a prerequisite for an ordinary local review. Use the project's established process only when it exists and the current authority permits it.

## Follow-up debt

New complexity introduced by the current change should normally be addressed before landing unless an explicit emergency or accepted tradeoff applies. Pre-existing debt outside scope may be recorded as residual risk; creating an external issue requires the applicable workflow and authorization.

For each finding, preserve whether it was fixed and reverified, accepted as risk, declined with evidence, or explicitly deferred. Keep this disposition outside the immutable review-result snapshot and bind it to the finding ID and revision.

## Rendering boundary

Render required and optional feedback from the schema's independent `blocking` and `severity` values; do not infer either from prose prefixes. Local feedback can be returned directly. Publishing to a hosted review, approving, or requesting changes is a separate external action governed by [Authority and Scope](authority-and-scope.md).
