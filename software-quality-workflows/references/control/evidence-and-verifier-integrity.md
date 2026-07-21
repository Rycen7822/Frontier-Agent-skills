# Evidence and Verifier Integrity

## Purpose
Decide evidence coverage/freshness, verifier independence, and the exact invalidation or repair boundary.

## Use when
- A claim depends on multi-item, sampled, truncated, stale, candidate-influenced, changed, or preserved evidence/state.

## Do not use when
- One fresh bounded proof covers the whole declared seam and no relevant identity or dependency changed.

## Required inputs
- task context; source/scope/environment/artifact identities; coverage and truncation metadata; required oracles/protected surfaces; typed dependencies and changed fields; side effects, authority, locks/leases/background work; and repair budget.

## Procedure
1. Mark every scoped item `full`, `sampled`, or `not_reviewed`; scanner hits remain candidates until contextual review. Unread, omitted, failed, or truncated material is partial and disclosed.
2. Bind findings and proof to source revision, scope, environment, producer, artifact hash, command/status, and freshness policy. Re-observe identity at review, fix, resume, and completion boundaries.
3. Classify each oracle's authority, addressability, stability, discrimination, independence, protected inputs/thresholds/expected outputs, false-green risk, and cost/timeout/noise limit.
4. Keep controller/policy, authoritative tests, benchmarks, thresholds, goldens, holdouts, authority manifests, and counterexample adapters outside candidate effects. Candidate-added tests are supplementary until independently reviewed, sensitivity-tested, lifecycle-accepted, and promoted by their owner.
5. A verifier/kernel change requires an outer contract plus independent old/hidden/holdout proof; it cannot approve itself. Unavailable, skipped, self-derived, or non-discriminating evidence never counts as pass.
6. Propagate changed refs through typed data/evidence/invariant/effect/resource/control dependencies; intersect declared fields and fail conservative when field detail is missing.
7. Allow local repair only at one modeled owner seam when preserved dependencies remain fresh/equivalent, effects are known/reversible, precision proof exists, and retry/approval budget remains. Goal, authority, security, global invariant, root cause, multi-owner/shared state, uncertain rollback, or non-local changes require parent/global replan.
8. Reconcile source/scope/plan/evidence hashes, state versions, locks/leases, background work, effects, retry, and approvals before resume. Never silently rewrite decisions, broaden scope, grant approval, weaken a gate, or retry a non-idempotent effect.

## Required result
- One `control-evidence-and-verifier-integrity` with coverage ledger, freshness decision, oracle authority/independence map, protected surfaces, changed/affected/invalidated/preserved IDs, required rechecks, local-repair/global-replan/blocker decision, resume reconciliation, limitations, and evidence refs.

## Stop
Stop any completion/approval/publication claim with unread, stale, truncated, self-graded, unavailable, or insufficiently local evidence.
