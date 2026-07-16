# Publication Readiness Consistency

This operator contract owns validation of `schemas/publication-readiness.schema.json`. Local review and publication are separate artifacts and authorities.

- Bind one validated local review by exact ref and content hash, then bind the publication decision to the same current source revision and scope hash.
- Re-observe remote host checks, required approvals, and branch/protection policy. Evidence refs must identify the observation used; cached prose is not a current check.
- Record the requested action and an explicit set of allowed actions plus its authority source. A requested action outside that set is authority-blocked even when all technical checks pass.
- `ready` requires a full-scope local pass with passed verification, complete or inapplicable spec traceability, no blockers, passing/applicable remote checks, satisfied/applicable approvals, satisfied/applicable branch policy, fresh identity, and no publication blocker.
- A sampled local pass is useful review evidence but cannot support remote readiness. Local success never implies merge, release, deploy, publish, or hosted approval.
- Publication remains a separately authorized side effect after readiness validation; readiness does not execute it.

Duplicate check or approval IDs, stale review hashes, source/scope drift, missing authority, and contradictory ready states are typed validation failures. Render hosted summaries only from the validated pair of local-review and publication-readiness artifacts.
