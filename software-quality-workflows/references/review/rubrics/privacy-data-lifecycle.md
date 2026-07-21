# Privacy and Data-Lifecycle Rubric

## Purpose
Identify privacy or data-lifecycle regressions in data flows affected by the scoped change.

## Use when
- Personal, sensitive, tenant, analytics, diagnostic, model-input, or retained user data can be collected, transformed, exposed, or deleted.

## Do not use when
- The concern is only credential handling or exploit security without a privacy/data-lifecycle contract.

## Required inputs
- Frozen purpose and data contract, affected flows/stores, policy and jurisdictional constraints supplied by the repository, evidence, and result-envelope contract.

## Procedure
1. Trace collection, validation, storage, logging, display, sharing, export, retention, deletion, backup, analytics, caches, and model/training use where affected.
2. Check purpose limitation, minimization, access boundaries, consent/notice, auditability, retention, deletion, and tenant isolation against the local contract.
3. Inspect diagnostics, examples, fixtures, screenshots, telemetry, and derived artifacts for unintended sensitive-data persistence or disclosure.
4. Prefer synthetic/redacted evidence and identify lifecycle gaps across failure/retry/recovery paths, not only the happy path.
5. Emit only scoped findings with concrete data subject/system impact and smallest compliant correction; do not invent legal requirements.

## Required result
- Zero or more local finding candidates with data class and lifecycle stage, evidence, impact, violated local contract, correction, confidence, blocking, and verification.

## Stop
Stop at privacy/data-lifecycle evidence; do not provide legal advice or enter implementation.
