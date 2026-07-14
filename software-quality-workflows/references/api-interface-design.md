# API and Interface Design

Use this reference when changing a public or semi-public contract: an endpoint, SDK, command output, configuration shape, file format, event, plugin manifest, tool schema, or interface consumed outside its owning module.

For request mode, authorization, and side effects, follow the [authority and scope owner](authority-and-scope.md). For completion evidence, follow [verification discipline](verification-discipline.md). This reference owns API and protocol compatibility, not global risk or completion policy.

## Contract-first workflow

1. Inventory current consumers, producers, examples, generated clients, fixtures, and documentation.
2. Record the observable contract before implementation: inputs, outputs, errors, authorization assumptions, idempotency, ordering, pagination, versioning, defaults, and side effects.
3. Classify the change as additive, compatible with a transition, or breaking.
4. Choose the smallest authoritative schema or implementation seam. Avoid an adapter unless its owner, expiry, and removal proof are explicit.
5. Add or update consumer-visible proof before changing the contract.
6. Implement at the owner, regenerate derived clients or artifacts, and scan for stale examples.
7. Verify representative consumers and the relevant compatibility boundary.

## Contract record

| Question | Record |
|---|---|
| Consumers | Humans, modules, services, clients, browsers, plugins, or automation that rely on the surface. |
| Stable behavior | Names, types, fields, errors, ordering, identifiers, defaults, timing guarantees, and side effects. |
| Allowed variation | Optional fields, bounded experimental values, cursors, retry timing, and explicitly non-contract diagnostics. |
| Failure model | Machine code, safe human summary, retryability, partial success, and validation/authentication/dependency distinctions. |
| Evolution | Compatibility window, migration sequence, deprecation signal, rollback, and removal owner. |
| Proof | Contract tests, schema snapshots, fixture round-trips, generated clients, command goldens, or tool-schema validation. |

## Compatibility rules

- Assume any observable behavior can become a dependency, including omission, field order, error shape, and default values.
- Prefer additive evolution only when existing consumers can safely ignore the addition. Adding an enum value can still break exhaustive consumers.
- Do not silently reuse a field with a new meaning. Introduce a versioned or explicitly migrated representation.
- Keep one consistent machine-readable error envelope per surface. Do not require callers to parse prose to determine state.
- Define idempotency and partial-success behavior for retryable operations.
- Keep temporary compatibility paths measurable and removable; give each one an owner and a retirement condition.

## Wide migrations: expand, migrate, contract

When a contract cannot change safely in one behavior-complete slice, use three explicit phases:

1. **Expand:** add a backwards-compatible representation, reader, writer, adapter, or version while preserving the old contract. Prove old and new consumers at the real boundary.
2. **Migrate:** move producers, stored forms, callers, generated clients, and documentation in bounded batches. Each batch declares its consumer set, focused proof, failure boundary, and rollback path; keep compatibility telemetry where practical.
3. **Contract:** remove the old path only after evidence shows no old readers, old writers, callers, stored representations, fixtures, generated artifacts, or supported clients remain. Run affected, public-surface, and canonical gates appropriate to the removal.

Do not disguise an unavoidable coordinated cutover as independently green slices. Record the integration gate, compatibility window, rollback boundary, and authority for the cutover. A preparatory refactor is justified only when it is the smallest separately provable change that makes the migration safer.

## Boundary validation

Use [Security Hardening](security-hardening.md) for the governing trust-boundary and abuse-case analysis. The checks below are interface-specific consequences of that policy.

- Parse and normalize external input before business logic.
- Bound collection sizes, strings, recursion, file sizes, and pagination parameters where resource use matters.
- Reject or safely ignore unknown control fields according to the published compatibility rule.
- Keep authorization decisions outside user-forgeable payload fields.
- Validate third-party, model, browser, and tool output before using it as data or rendering it.
- Keep examples synthetic and free of credentials, private identifiers, or realistic sensitive payloads.

## Verification checklist

- The consumer inventory covers every supported surface affected by the change.
- Contract proof observes the public boundary rather than only private helpers.
- Errors, defaults, optional fields, ordering, and partial success have explicit cases where relevant.
- Implementations, schemas, generated artifacts, docs, and examples agree.
- A breaking change has a migration path, compatibility window or coordinated cutover, and rollback boundary.
- Removed compatibility behavior has no remaining consumers or stale generated artifacts.
- Every contract-phase removal has evidence that old readers, old writers, callers, and stored forms are absent.

## Red flags

- A field changes meaning without migration guidance.
- Similar failures use incompatible shapes.
- Tests prove a helper but no actual consumer contract.
- A compatibility layer has no owner or end condition.
- Documentation advertises a surface not present in the shipped artifact.
