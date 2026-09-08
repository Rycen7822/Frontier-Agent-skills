# Compatibility and migration

Use when changing an API, persisted representation or consumers that cannot all move atomically.

Identify the actual contract: accepted inputs, outputs, errors, ordering, partial updates and compatibility commitments. Find direct and indirect consumers, including persisted data, serialization, asynchronous work and external clients. An internal function rename does not itself require a compatibility layer.

For an atomic internal migration, update consumers and delete the old path together. For external or staged migration, define the compatibility period, responsible owner and observable removal condition. Keep only the bridge the real rollout needs; do not let a temporary adapter become an unowned permanent API.

Consider old/new readers and writers, partial failure, retries, rollback and irreversible data loss only where applicable. Distinguish rolling code back from restoring transformed data. State the decisive acceptance behavior and the smallest evidence for it; use existing fixtures or checks before building a migration harness.

Retire the old implementation after its real consumers have moved and required compatibility has ended. Remove obsolete tests and flags with it, retaining unique contract protection. A new revision alone does not require repeating all earlier migration checks.
