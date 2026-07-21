# Test-suite lifecycle

## Purpose

Govern specialized test cleanup, oracle repair, large-scale supersede/retire work, migration-test removal, and flaky/quarantine policy. Do not load this reference for ordinary feature, bug-fix, or refactor closeout.

## Oracle integrity

Trace expectations to a requirement, literal example, independent reference, stable fixture, or property. Production helpers must not compute their own expected result. Use real collaborators except at genuinely external, destructive, unavailable, costly, or nondeterministic boundaries. Cover contract-owned errors, limits, transitions, negative paths, and externally meaningful serialization.

## Lifecycle decisions

- Keep unique current protection. Merge only when the replacement has equal or stronger oracle quality and localization.
- Update an expectation only for an authorized contract change.
- Quarantine visibly with failure signature, environments, gate treatment, owner, repair condition, and forced review.
- Supersede only with an equal or stronger replacement and a bounded confirmation window that retires or restores the old test.
- Retire only when the requirement/risk no longer exists or an approved replacement makes the test irrelevant. Search its fixtures, scripts, gates, and consumers before removal.
- Remove a `migration_temporary` test only after its recorded observable condition and deterministic removal gate pass.

Never infer lifecycle from age, path, duration, current failure, or file count. Never weaken or retire a valid contract solely to make implementation pass.

## Required result

Record the bounded inventory, oracle provenance and false-green risks, owner and canonical gate, action for each affected test/fixture, replacement or transition evidence, cleanup, retained protection, and residual limits.
