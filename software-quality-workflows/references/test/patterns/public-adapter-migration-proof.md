# Public Adapter Migration Proof Pattern

## Purpose
Prove that every public adapter preserves the approved contract, identity, read/write boundary, and legacy behavior during migration.

## Use when
- CLI, wrapper, protocol, schema, preflight, router, installer, or another public adapter is migrated or disagrees with an internally green runtime.

## Do not use when
- The change is wholly internal and no public boundary, identity, schema, or compatibility behavior changes.

## Required inputs
- task context; public contract/schema/docs; adapter inventory; state identity rules; approved legacy compatibility/rejection; old/new fixtures; and risk authority.

## Procedure
1. Inventory adapters translating arguments, identities, paths, schemas, errors, or versions, including dormant/generated surfaces.
2. Use a task-unique state root and neutral working directory; prove read-only calls create no durable state and first authorized write creates only canonical new state.
3. Exercise current and stale/legacy selectors through wrappers, preflight, schema, runtime, and installed/public entrypoints; internal unit success is not adapter parity.
4. Assert state location, schema/version negatives, errors, read/write boundaries, migration lineage, and approved compatibility or rejection.
5. Keep rollback/migration artifacts until gates pass; cleanup only isolated state and task-owned configuration.

## Required result
- One `test-patterns-public-adapter-migration-proof` with adapter/consumer coverage matrix, old/new fixture identities, public-path command/status evidence, state/schema/error assertions, residual-name scan, rollback evidence, and cleanup status.

## Stop
Stop at public adapter migration evidence; do not infer public parity from internal calls or perform an unauthorized migration write.
