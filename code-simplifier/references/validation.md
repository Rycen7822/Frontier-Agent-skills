# Validation for simplification

Use this reference when a candidate has unresolved semantic or operational risk, or when a check fails. Validation answers the actual uncertainty; it is not a fixed testing pipeline.

## Select the smallest decisive evidence

First identify the input domain and the behavior being preserved: result values, errors, side effects, mutation or identity, ordering, resource lifetime and relevant performance limits. For an authorized behavior change, state the intended difference and the guarantees that remain. A desirable new behavior is not evidence that the old and new implementations are equivalent.

Reuse a recent check when its code, dependencies, inputs and environment still cover the claim. Otherwise obtain a targeted baseline before a risky edit, or retain enough of the original implementation to compare safely. Do not run two full suites merely to create symmetrical reports. Keep user changes intact; a dirty working tree is not permission to reset, stash or replace it.

Choose from existing repository facilities according to the candidate:

| Uncertainty | Useful evidence |
|---|---|
| Local control flow or types | Relevant compiler/type/lint result, targeted test, or a clear semantic argument for a no-op. |
| Removed code or registrations | Relevant consumer trace, supported build/import/entrypoint check and generator output where applicable. |
| Merged branches or conversions | Boundary examples, an existing property test, or a bounded before/after comparison. |
| Errors, cancellation or cleanup | Failure injection or controlled event ordering that reaches the affected transition. |
| Removed caches, copies or representations | Ownership/identity checks and a representative measurement when a performance contract is implicated. |

Use the repository's supported matrix when the edit crosses platforms, feature flags or build modes. Do not claim a matrix was tested from one configuration. An unavailable decisive check leaves that candidate unverified; preserve the risky behavior or report the block rather than manufacture a pass.

## Search for a distinguishing counterexample

For a risky rewrite, start with an input or event sequence most likely to separate the implementations: an empty or boundary value, an error after partial work, a repeated call, cancellation during publication, or a late callback. Prefer an existing test framework. Add bounded differential or property-based checks only when they resolve more uncertainty than the available examples; do not add a generic fuzzing system to the target project.

When comparing implementations, control relevant randomness, clocks and scheduling; use isolated state or equivalent resets. Compare contract-relevant observations, not only return values. Mutations, exceptions, emitted events, I/O attempts and resource releases may be the thing being changed. Do not run both versions against live external systems just to compare them.

The original implementation is a reference for preserved behavior, not a specification for an explicitly authorized fix. Use the stated contract to judge intended differences. Generated inputs must respect legitimate input preconditions; separately test boundary validation when it belongs to the public contract. Avoid tautological checks or expectations regenerated from the modified implementation.

No difference found means no difference found within those inputs, transitions and environment. Passing tests is not a proof of universal equivalence; a complexity score is not a proof of maintainability. State the evidence at its actual strength.

## Handle failing checks without weakening protection

Determine whether a failure is introduced by the patch, pre-existing, environmental or caused by an intentionally changed contract. Compare the same test identities and conditions where possible; equal pass counts can hide a newly failing test. Do not edit unrelated code simply to obtain a green summary.

Keep unique behavior assertions. When an interface or module boundary legitimately changes, migrate its tests to the new boundary and retain the protected behavior. Delete an expectation only when it duplicates retained protection or checks behavior explicitly authorized to retire. Do not remove a failing test, relax its assertions, update snapshots blindly or rewrite the oracle to fit the patch.

If the simplification causes a regression, revise it within scope or undo only the edits belonging to that candidate. Preserve prior user edits and independent valid changes. Do not use a repository-wide reset or overwrite the whole file from an older revision. After a corrective edit, rerun the check whose evidence changed; reuse unrelated valid results.

## Stop and report accurately

After a candidate's meaningful gain and decisive checks are established, stop rather than repeatedly rewording or reformatting it. Stop pursuing a candidate whose remaining risk or investigation cost exceeds its concrete benefit. A risky blocked candidate and an inspected no-change result are different outcomes.

Report the actual removed obligation or readability gain, the checks or reused evidence that support it, and material unverified boundaries. Do not claim lower token use, higher task success, better future maintainability or host activation from package tests. A controlled agent evaluation is separate work, not an automatic prerequisite for ordinary simplification or package integration.
