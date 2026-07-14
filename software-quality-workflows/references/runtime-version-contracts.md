# Runtime Version Contracts

Use this reference when declared runtime support may not match APIs, syntax, package metadata, generated artifacts, or public adapters used by the repository. It owns runtime-floor diagnosis and migration evidence. General source freshness remains in [Source-Driven Implementation](source-driven-implementation.md).

## Contents

- [Contract inventory](#contract-inventory)
- [Boundary probe](#boundary-probe)
- [Choose the supported contract](#choose-the-supported-contract)
- [Implementation and tests](#implementation-and-tests)
- [Consistency surfaces](#consistency-surfaces)
- [Unverified environments](#unverified-environments)
- [Closeout](#closeout)

## Contract inventory

Record:

- advertised minimum, maximum, or range;
- exact local runtime and package-manager versions;
- manifest, lockfile, documentation, CI, container, generated-client, and installer declarations;
- the API, syntax, module, flag, or behavior whose availability is in question;
- whether the path is core, optional, build-only, development-only, or public-facing;
- consumers that still require an older runtime.

Do not infer support from a major version label alone. A feature can arrive in a later minor release, change status, require a flag, or differ across distributions.

## Boundary probe

1. Reproduce with the exact lowest advertised runtime.
2. When a feature landed inside a supported range, probe the nearest known bad and good versions.
3. Exercise the real import, parse, build, startup, or public adapter path that depends on the feature.
4. Preserve exact version output, exit status, and failure class.
5. Keep environment acquisition separate from the probe.

Prefer an already installed runtime, repository-pinned toolchain, declared container, or existing CI matrix. Do not implicitly download and execute a runtime merely to make the probe convenient. Any network acquisition or environment mutation is governed by [Authority and Scope](authority-and-scope.md).

## Choose the supported contract

Use evidence to choose one explicit outcome:

| Outcome | Appropriate when |
|---|---|
| Raise the runtime floor | Core paths already rely broadly on the newer behavior and older support is not a required contract. |
| Add a compatibility implementation | Older support is explicitly required and fallback semantics can be specified and tested. |
| Isolate an optional feature | The dependency is genuinely optional and its absence has a documented observable result. |
| Defer as unverified | Required boundary environments are unavailable and neither declaration nor behavior can be proven safely. |

Do not hide a broad runtime dependency behind a narrow exception handler. A compatibility path must define behavior, errors, performance limits, maintenance owner, and retirement condition.

## Implementation and tests

For a raised floor:

1. create a contract RED for inconsistent declarations or unsupported startup;
2. update the canonical runtime declaration;
3. align lockfile root metadata, documentation, CI or container matrices, generated metadata, and installer checks;
4. test rejection or clear failure below the new floor;
5. test the first supported boundary.

For continued older support:

1. characterize current behavior on both sides of the boundary;
2. define one shared public contract and allowed implementation differences;
3. add tests for both backends or runtime paths;
4. exercise errors, serialization, persistence, and public adapters;
5. document how and when the compatibility path can be retired.

Use [Safe Test-Driven Development](test-driven-development.md) for RED/GREEN/REFACTOR. If a wrapper or schema can drift from the runtime, also use PAT-05 in [Test Patterns](test-patterns.md).

## Consistency surfaces

Check every applicable surface:

- runtime or package manifest;
- root lockfile metadata;
- developer and installation documentation;
- CI matrix and release workflow;
- container or environment definition;
- generated client, package, or distribution metadata;
- CLI preflight and error message;
- protocol, plugin, or service wrapper;
- examples and templates consumed by users.

A local runtime success does not prove these surfaces agree. Conversely, a stale documentation string does not prove the runtime is broken; classify each mismatch against the chosen contract.

## Unverified environments

If the boundary runtime is unavailable:

- record the missing version and why acquisition was not authorized or practical;
- use static declaration checks and the closest available local proof;
- identify which claim remains unverified;
- do not call the unsupported or supported boundary proven;
- leave a precise follow-up command or CI matrix requirement without executing unapproved setup.

Select and report focused, affected, public-surface, and canonical evidence through [Verification Discipline](verification-discipline.md).

## Closeout

Report the detected versions, authoritative source or local contract revision, old and new support statement, exact boundary evidence, declaration changes, public adapter status, unrun environments, compatibility retirement condition, and cleanup of any task-owned toolchain or artifacts.
