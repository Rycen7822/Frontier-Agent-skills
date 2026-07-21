# Review Tier Selection

## Purpose
Choose the smallest R0/R1/R2 review tier that can answer the requested local technical question safely.

## Use when
- Request mode is review and tier, independence, scope depth, or fix-cycle budget is unresolved.

## Do not use when
- The request is a general report/audit, or a fresh tier decision already binds the same scope and risk surfaces.

## Required inputs
- Review outcome, authority, frozen-scope readiness, changed/implicated surfaces, plausible impact, repository rules, available independent context, and fix authorization.

## Procedure
1. Select R0 for routine closeout or focused blocker inspection: implementer self-diff, owner context, focused evidence, zero automatic independent reviewer.
2. Select R1 for substantive owner or cross-component work: full scoped diff, relevant call sites, specification axis when applicable, engineering axis, and at most one authorized focused fix cycle.
3. Select R2 for security, data loss, public contract, migration, release, broad refactor, or explicit high risk: independent complete declared-scope review, only triggered specialist surfaces, and at most two explicitly justified fix cycles.
4. Review-only always has zero fix budget. Reviewer availability never widens authority; absence is an evidence limit.
5. Record exactly which rubric surfaces are implicated without loading them into this decision.
6. Record the tier, independence need, bounded input requirement, cycle budget, implicated rubric surfaces, and blocker. The owning task controls continuation.

## Required result
- Tier, reason, scope depth, independence, implicated rubrics, fix-cycle budget, required input, and blocker.

## Stop
Stop at the tier decision and return it to the owning task.
