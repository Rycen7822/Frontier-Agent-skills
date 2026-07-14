# Disposable Feasibility Spikes

Use this branch only when an observable experiment is needed to answer a feasibility question that source inspection cannot settle. It is not an implementation-plan profile and does not authorize production integration.

## Route

Use a spike when the user explicitly wants to try, compare, or de-risk an idea before committing to a build, or when closure admission identifies one bounded feasibility fact that must be resolved before freeze. Do not use it when documentation/source already answers the question, the path is already validated, or the requested work is production implementation.

## Contract

1. State one falsifiable Given/When/Then question and the decision it unlocks.
2. Put the highest idea-killing risk first.
3. Inspect only enough current source/docs/runtime to choose a meaningful experiment.
4. Build the smallest interactive or observable probe.
5. Exercise the happy path plus the edge case most likely to invalidate the result.
6. Record evidence, constraints, surprises, and one of `validated`, `partial`, or `invalidated`.
7. Delete the probe or keep it in a clearly task-owned disposable location; never silently promote spike code.

For several independent questions, use stable IDs such as `S-001`; comparison variants may share a number with suffixes. Parallel work is allowed only when writes/resources are disjoint and the SQW delegation gate says it has net value.

## Suggested artifact

```markdown
# S-001: <feasibility question>

- Decision unlocked: <what this evidence will decide>
- Given/When/Then: <observable criterion>
- Source/runtime inspected: <fresh pointers>
- Experiment boundary: <what is intentionally absent>
- Evidence: <commands, artifacts, or observations actually produced>
- Verdict: validated | partial | invalidated
- Constraints/surprises: <material conditions>
- Production recommendation: <decision proposal, not copied spike code>
- Cleanup/promotion: <delete, retain as fixture, or propose a separately reviewed implementation>
```

`invalidated` is a successful spike when evidence answers the question. `partial` must state the exact constraints. For comparisons, use the same criterion and environment, then report differences rather than choosing by intuition.

## Promotion gate

Production work requires a new Brief, Handoff, or Program plan when a durable plan is warranted, followed by the SQW execution and verification owners. Re-inspect the production seam, replace hard-coded shortcuts, define real contracts, establish proof, and review licensing/security/operations. A spike verdict is evidence, not production readiness.

For autonomous closure, freeze may consume only the source-bound verdict and stated constraints. Silent promotion of spike code, fixtures, mocks, candidate state, or inferred authority is forbidden.

## Ownership

SQW owns authority, experiment side effects, runtime proof, delegation, and cleanup. `writing-plans` may reference the resulting evidence when selecting an implementation profile. Long experiment reports use `long-document-segmented-writing` for document mechanics.

This branch retains the lightweight feasibility method adapted from GSD's MIT-licensed spike workflow; it deliberately omits GSD-specific persistent state and commit conventions.
