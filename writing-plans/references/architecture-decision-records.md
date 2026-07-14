# Architecture Decision Records

Use this reference when a plan or implementation makes a decision that is expensive to reverse, affects public contracts, changes architecture, introduces a major dependency, selects infrastructure/runtime/storage, changes security posture, or defines a cross-team convention.

Do not write ADRs for obvious local edits, one-off bug fixes, routine refactors, generated code, or decisions already captured by a more specific migration/design artifact.

## ADR trigger checklist

Write or update an ADR when at least one is true:

- The decision changes data model, public API, plugin/tool schema, authentication, authorization, deployment topology, storage, queueing, or runtime ownership.
- Multiple plausible alternatives exist and future maintainers need to know why one was chosen.
- Reversing later would require data migration, consumer migration, downtime, or broad rewrites.
- A security, privacy, compliance, or reliability tradeoff is accepted.
- The decision supersedes an older architecture rule.

## Minimal ADR template

```markdown
# ADR-NNN: <decision title>

## Status
Accepted | Proposed | Superseded by ADR-NNN | Deprecated

## Context
What problem, constraints, evidence, and current design assumptions forced a decision?

## Decision
What exact approach is chosen? Name owners, boundaries, and affected contracts.

## Alternatives considered
- Option A: why rejected.
- Option B: why rejected.

## Consequences
What becomes easier, what becomes harder, what risks or follow-up work remain?

## Verification and rollback
What proves the decision works, and how can it be reversed or superseded?
```

## Documentation rules

- Comment the “why” and invariants, not what the code plainly says.
- Keep API/tool-schema docs synchronized with implementation and examples.
- Write runbooks for operational decisions that future operators must execute, not for routine code structure.
- Do not delete old ADRs; supersede them so historical context remains inspectable.
- Keep ADRs concise enough to load; link detailed evidence or scratch notes instead of dumping them into the ADR.

## Pairing with writing-plans

- Use the design audit ledger to decide whether an ADR is necessary.
- Store private implementation plans in project worknotes; store ADRs in the repository’s documented ADR location only when the decision is meant to be durable project documentation.
- If no ADR location exists, choose `docs/decisions/` only when the decision is public developer documentation; otherwise keep the decision in worknotes or the design artifact.
- In autonomous closure, a candidate or incumbent may cite an existing ADR but cannot author, accept, or publish one. A new or changed ADR becomes sign-off-ready only after the independent SQW review and publication gates; until then it remains a proposed intended-state artifact.
