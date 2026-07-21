# External Source Authority

## Purpose
Select and bind narrow authoritative external/versioned evidence when upstream behavior is genuinely normative for the local implementation decision.

## Use when
- A framework/library/runtime/protocol/browser/platform/provider or generated-client behavior is version-sensitive and repository code/tests do not fully own the answer.

## Do not use when
- Local behavior is fully governed by repository contracts, or the task merely contains a URL without making external source/version authoritative.

## Required inputs
- task context; exact dependency/runtime/protocol/generated-client/compatibility versions from repository declarations/lock state, one decision question, local wrapper/conventions/tests/support range, and candidate primary sources.

## Procedure
1. Detect exact relevant versions locally and formulate the narrow question before research.
2. Prefer detected-version official docs, migration/changelog/deprecation/standard, maintained spec/compatibility table, then dependency source/tests/types/generated examples; community material is only a lead.
3. Extract only the signature, lifecycle, compatibility, deprecation, or migration rule governing the change and bind it to version/date/commit/section/deep link or exact local source anchor.
4. Compare upstream rule with local wrappers, security/error/lifecycle/ownership constraints, tests, and supported environments.
5. Preserve an intentional local narrowing unless the task changes it; follow official migration when migration is the goal; never introduce syntax unsupported by the declared range.
6. Resolve conflicts explicitly and label unavailable/silent authority `unverified`; use strongest local proof without presenting inference/model memory as source fact.
7. Record a concise nearby evidence anchor and recheck code/tests/generated artifacts/docs/citations agree with what ships.

## Required result
- Question and detected versions; selected authoritative source/anchor/freshness; governing rule; local comparison/conflict decision; implementation constraint; unverified assumptions/follow-up; affected consistency surfaces.

## Stop
Stop at the source-authority decision; do not broaden research, copy unsafe upstream examples, or treat citation as implementation proof.
