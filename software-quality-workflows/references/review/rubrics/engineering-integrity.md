# Engineering Integrity Rubric

## Purpose
Identify scoped regressions across API consumers, architecture maintainability, CI/release controls, dependency provenance, and test evidence.

## Use when
- Review scope implicates one or more developer/public contract, ownership, delivery, dependency, or proof surfaces.

## Do not use when
- None of these five engineering surfaces changes or a security/privacy/product specialist owns the actual concern.

## Required inputs
- `review-tier`; frozen scope/change material; consumer and architecture conventions; delivery pipeline; manifests/locks/provenance; behavior/risk contract; verification evidence; and result contract.

## Procedure
1. For API consumers, compare methods/parameters/errors/auth/pagination/idempotency/version plus implementation, schemas, generated SDK/types, docs/examples, compatibility, deprecation, migration, defaults, and executable success/failure examples.
2. For maintainability, read owner/data-flow context and check only introduced/worsened duplicated policy, confused responsibilities, feature envy/data clumps/primitives, dispatch, shotgun/divergent change, speculative seams, message chains, pass-through middlemen, or refused contracts. Prefer the smallest owner-aligned correction.
3. For CI/release, verify build/lint/type/test/security/generated/package/artifact gate order, local/CI parity, no weakened/bypassed control, migration/compatibility/smoke/canary/observability/rollback readiness; do not operate delivery systems.
4. For dependencies/supply chain, check necessity, maintenance/license/policy/trusted source, manifest/lock/checksum/signature/provenance/transitives/hooks/vendor/binaries, container pinning/residue/build-runtime separation, artifact reproducibility, and preserved scanners; do not install/publish/mutate registries.
5. For test evidence, map material behavior/risk to the lowest sufficient boundary, reject mock/private/stale/skipped/unexercised/swallowed false greens, and check determinism/isolation/data plus actual collection/execution; do not implement tests.
6. Emit only change-caused, line/contract-grounded findings with impact, smallest correction, confidence, blocking, executable verification, explicit uncertainty, and useful positive evidence; never manufacture generic smells.

## Required result
- One `review-rubrics-engineering-integrity` with zero or more candidates classified by the five subdomains, evidence/impact/correction/confidence/blocking/verification, uncertainties, and positive notes.

## Stop
Stop at scoped review evidence; do not redesign, fix, operate pipelines, install, publish, or traverse another rubric.
