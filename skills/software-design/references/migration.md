# Compatibility and migration

Use when changing an API, persisted representation or consumers that cannot all move atomically.

Identify the actual contract: accepted inputs, outputs, errors, ordering, partial updates and compatibility commitments. Find direct and indirect consumers, including persisted data, serialization, asynchronous work and external clients. An internal function rename does not itself require a compatibility layer.

For an atomic internal migration, update consumers and delete the old path together. For external or staged migration, define the compatibility period, responsible owner and observable removal condition. Keep only the bridge the real rollout needs; do not let a temporary adapter become an unowned permanent API.

Consider old/new readers and writers, partial failure, retries, rollback and irreversible data loss only where applicable. Distinguish rolling code back from restoring transformed data. State the decisive acceptance behavior and the smallest evidence for it; use existing fixtures or checks before building a migration harness. Apply [Test Behavior](../../test-behavior/SKILL.md) before authoring migration checks, distinguishing one-time acceptance from protection for continuing old data, clients or retryable migration behavior.

Retire the old implementation after its real consumers have moved and required compatibility has ended. Apply Test Behavior to directly affected tests and fixtures in the same change, even if no test has failed: migrate or retain continuing protection and retire checks whose sole obligation ended. Remove obsolete flags with their implementation. A version number alone does not establish the end of compatibility or justify repeating all earlier migration checks.
