# Source-Driven Implementation

Use this reference when implementation depends on current framework, library, runtime, protocol, browser, platform, provider, or version-sensitive API behavior. Skip it for local behavior fully governed by repository code and tests.

For request scope and external side effects, follow the [authority and scope owner](authority-and-scope.md). For proof that the implemented behavior matches the selected source and local contract, follow [verification discipline](verification-discipline.md). When the decision changes or tests a declared runtime support floor, adjacent good/bad versions, manifest/lock/docs/CI alignment, or compatibility versus a floor raise, route that part to [runtime version contracts](runtime-version-contracts.md).

## Workflow

1. Detect the exact dependency, runtime, protocol, generated-client, or compatibility versions from repository-owned declarations and lock state.
2. Identify the question that source evidence must answer; avoid broad research unrelated to the decision.
3. Consult the narrowest authoritative material for the detected version.
4. Extract the signature, lifecycle rule, compatibility boundary, deprecation, or migration constraint that governs the change.
5. Compare that rule with repository conventions, tests, wrappers, and supported environments.
6. Resolve conflicts according to the actual task: preserve local compatibility unless the task explicitly changes it; follow official migration guidance when migration is the goal.
7. Implement at the local owner and retain a concise evidence anchor for non-obvious, version-sensitive choices.
8. Recheck that citations, generated artifacts, and code all describe the behavior actually shipped.

## Source hierarchy

1. Official documentation for the detected version.
2. Official migration guide, changelog, release note, deprecation notice, or standard.
3. Maintained specification or compatibility table.
4. Dependency source, tests, types, generated code, or examples when documentation is incomplete.
5. Community material only as a lead to an authoritative or locally provable rule.

Prefer primary sources for technical claims. Record a source version, date, commit, or local path when the claim can drift.

## Conflict handling

- Preserve repository behavior when the local wrapper intentionally narrows or stabilizes upstream behavior.
- Follow current official migration guidance when removing a deprecated API is the stated objective.
- Do not introduce the newest syntax when supported runtime versions cannot execute it.
- Do not copy an upstream example that bypasses local security, error, lifecycle, or ownership constraints.
- Mark a claim unverified when authoritative material is unavailable or silent; add the strongest local proof available without presenting inference as source fact.

## Citation discipline

- Use a deep link, named section, versioned specification, or exact local source anchor.
- Quote only the small phrase needed to support the decision; paraphrase the rest.
- Keep citations near the decision they support.
- Do not cite model memory or an unsourced example as authority.
- Revisit stale evidence when the lockfile, runtime target, provider version, or public contract changes.

## Verification checklist

- Exact versions or compatibility targets are recorded.
- Evidence is authoritative, narrow, and current enough for the claim.
- Local conventions and supported environments were compared with upstream guidance.
- Deprecated behavior is introduced only when explicitly preserving compatibility.
- Code, tests, generated artifacts, docs, and citations agree.
- Unverified assumptions are labeled and have a local proof or named follow-up gate.
