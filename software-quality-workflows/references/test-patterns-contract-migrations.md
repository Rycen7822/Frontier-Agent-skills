# Test Patterns: Contract Migrations

> Owner: test-patterns-contract-migrations
> Authority: companion
> Role: recipe
> Phases: BASELINING, SEARCHING, SIGNING_OFF
> Requires: test-lifecycle-management, verification-discipline, runtime-version-contracts
> May load:
> Does not own: compatibility policy, migration authority, source versions

Use for PAT-06/PAT-09/PAT-14: old/new consumer fixtures, expand-migrate-contract ordering, schema/version negatives, one-time migration lineage, rollback windows, and leftover-name scans. Bind every fixture to a source/version and a consumer oracle.
