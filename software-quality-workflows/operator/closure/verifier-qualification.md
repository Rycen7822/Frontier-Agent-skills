# Verifier Qualification Runtime

This operator contract owns the detailed verifier-bundle and qualification mechanics projected in bounded form to `sqw.closure.verifier-qualification`. It is never a model-navigation card.

## Bundle identity

Freeze contract, plan, policy, authority, source, scope, environment, closure epoch, protected-path manifest, oracle manifests, counterexample adapters, qualification summary, limitations, and content hash. Content hashing excludes only the bundle's own hash field. Accepted and superseded bundles are immutable.

## Per-oracle qualification

Qualify every required oracle in order:

1. addressable through a declared real entrypoint;
2. stable under a bounded repeat/noise protocol;
3. discriminating against known failures, mutations, or plausible wrong implementations;
4. independent of candidate-controlled values and protected from candidate writes.

Record expected baseline, tolerance/noise, known-failure or mutation sensitivity, authority, cost, timeout, counterexample adapter, evidence schema/sensitivity, environment needs, and limitations. Risk determines the minimum qualification floor. Unavailable, unstable, or non-discriminating oracles cannot count as pass.

## Candidate tests and protected surfaces

Candidate tests start as supplementary evidence. Promotion requires controller validation, independent review, known-failure/mutation sensitivity, and test-lifecycle acceptance in a new verifier epoch. Protect controller/policy files, contract/verifier locks, protected tests, benchmark definitions and thresholds, goldens, holdouts, authority manifests, and publication policy. A kernel change requires an outer meta-contract and independent old/hidden/holdout verifier.

## Cascade, freshness, and invalidation

Bind baseline classification before candidate edits. Execute a cost-increasing schema/static/focused/affected/property/differential/public/runtime/security/benchmark/canonical cascade; record every skipped tier and reason. At sign-off revalidate bundle hash/epoch, source/scope/environment, protected surfaces, required corners, results, baseline, and candidate-test authority.

Oracle, threshold, golden, holdout, environment expectation, adapter, or protected-path changes invalidate dependent evaluations and sign-off. Global verifier changes cannot be repaired inside the candidate they evaluate. Only the controller freezes/supersedes bundles, accepts qualification, advances phase, promotes candidates, or closes a workflow.
