# Test Patterns: Workflow Boundaries

> Owner: test-patterns-workflow-boundaries
> Authority: companion
> Role: recipe
> Phases: BASELINING, SEARCHING, SIGNING_OFF
> Requires: test-lifecycle-management, verification-discipline
> May load: none
> Does not own: test authority, verifier qualification, workflow transitions

Use for PAT-01/PAT-05/PAT-08/PAT-10 boundary fixtures: actor authority, state/event transitions, lock/retry, crash replay, and side-effect isolation. A fixture proves one boundary and preserves the original failure class; it does not replace the owning state or verifier contract.
