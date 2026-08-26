# Evidence and Verifier Integrity

## Purpose
Decide evidence coverage/freshness, verifier independence, and the exact invalidation or repair boundary.

## Use when
- A claim depends on multi-item, sampled, truncated, stale, candidate-influenced, changed, or preserved evidence/state.

One fresh bounded proof for the whole declared product surface stays Direct and uses its existing verifier.

## Required inputs
- task context; source revision, explicit scope, environment facts, named external/raw artifact bindings; coverage and truncation metadata; required oracles/protected surfaces; typed dependencies and changed fields; side effects, authority, locks/leases/background work; and repair budget.

## Procedure
1. Mark every scoped item `full`, `sampled`, or `not_reviewed`; scanner hits remain candidates until contextual review. Unread, omitted, failed, or truncated material is partial and disclosed.
2. Bind findings and proof to source revision, explicit scope, environment, producer, command/status, freshness policy, limitations, and raw evidence refs. Repository evidence uses revision plus path; transaction-owned derived evidence uses state revision plus path and consumer reprojection; external, unversioned, or non-replayable raw bytes use one digest. Re-observe these identities at review, fix, resume, and completion boundaries.
3. Classify each oracle's authority, addressability, stability, discrimination, independence, protected inputs/thresholds/expected outputs, false-green risk, and cost/timeout/noise limit.
4. Keep controller/policy, authoritative tests, benchmarks, thresholds, goldens, holdouts, authority manifests, and counterexample adapters outside candidate effects. When one of these support/control surfaces fails during a product task, record the verification limitation and do not repair it unless the user explicitly targets that surface. Candidate-added tests are supplementary until independently reviewed, sensitivity-tested, lifecycle-accepted, and promoted by their maintainer.
5. A verifier/kernel change closes through an outer contract plus independent old/hidden/holdout proof. Pass evidence is available, executed, independently owned, and discriminating.
6. Propagate changed refs through typed data/evidence/invariant/effect/resource/control dependencies; intersect declared fields and fail conservative when field detail is missing.
7. Allow a local product repair only when preserved dependencies remain fresh or equivalent, effects are known and reversible, precise proof exists, and retry or approval budget remains. A problem in the goal, authority, security boundary, global invariant, controller, oracle, multi-writer state, or rollback assumptions requires a bounded report or separately authorized task—not an automatic control-code repair or global replan.
8. Reconcile source/state revisions, explicit scope, each named external/raw binding, locks/leases, background work, effects, retry, and approvals before resume. A binding mismatch invalidates its direct claims and consumers; typed dependencies determine the smallest recheck or replan boundary. Settled decisions, scope, approvals, gates, and non-idempotent effects retain their named owners.

## Required result
- One result in the current reply, existing project state, or admitted fallback ledger with coverage, freshness decision, oracle authority/independence, protected surfaces, changed/affected/invalidated/preserved IDs, required rechecks, local-repair/separate-task/blocker decision, resume reconciliation, limitations, and evidence refs. Keep one selected record location.

## Stop
Completion, approval, and publication claims require fresh, sufficiently local, independently owned evidence with disclosed coverage and truncation.
