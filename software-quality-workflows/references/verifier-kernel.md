# Verifier Kernel

> Owner: verifier-kernel
> Authority: normative_owner
> Role: control_plane
> Phases: VERIFIER_QUALIFYING, SIGNING_OFF
> Requires: verification-discipline, authority-and-scope
> May load: test-lifecycle-management, security-hardening
> Does not own: generic test selection, domain-specific security policy, candidate implementation

## Activation and exclusions

Load for autonomous closure and any task that needs a frozen authoritative oracle set. `verification-discipline` still owns generic gate execution, evidence labels, command integrity, failure classification, and claim wording.

## Verifier Bundle

Freeze one bundle that binds contract/source/scope/environment hashes, epoch, protected paths, oracle manifests, qualification summary, and limitations. Content hashing excludes only its own hash field. Frozen and superseded bundles are immutable.

## Qualification

Qualify each required oracle in order: addressable, stable, discriminating, independent. Record repeats, tolerance/noise, known-failure or mutation sensitivity, authority, expected baseline, cost/timeout, counterexample adapter, evidence schema, and limitations. Risk determines the minimum level; an unavailable or non-discriminating oracle cannot be counted as pass.

## Candidate-added tests

Candidate tests begin as `candidate_supplementary`: useful repair evidence but insufficient alone for a hard constraint. Promotion requires controller validation, independent review, known-failure/mutation sensitivity, and test-lifecycle acceptance. Changing the protected oracle set requires a new verifier/closure epoch.

## Protected surface

Protect contract/verifier locks, controller and policy files, repository protected tests, benchmark definitions/thresholds, goldens, holdouts, publication policy, and authority manifests. A task that changes the kernel uses an outer meta-contract and independent old/hidden/holdout verifier; it cannot grade itself.

## Baseline and cascade

Bind baseline classification before edits, then use a cost-increasing cascade from schema/static/focused through affected, property/differential, public/runtime/security, benchmark, and canonical sign-off gates. Early pruning records every skipped tier and reason.

## Sign-off freshness

At sign-off, revalidate bundle hash/epoch, source/scope/environment, protected surfaces, required corners, oracle results, baseline, and candidate-test authority. Any stale binding invalidates verifier-integrity pass.

## Epoch and invalidation

Oracle, threshold, golden, holdout, environment expectation, counterexample adapter, or protected-path changes invalidate dependent candidate evaluations and sign-off. Global kernel changes cannot be repaired inside the candidate they evaluate.

## Completion

This owner completes when the required bundle is immutable, qualified to the contract's risk floor, independently protected from candidates, and fresh for sign-off. It does not promote candidates or close the workflow.
