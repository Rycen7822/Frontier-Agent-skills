# Security Hardening

Use this reference when a change crosses a trust boundary, handles identity or permissions, stores or displays private data, accepts files or callbacks, calls third-party services, executes provider/tool/model output, changes browser-facing behavior, or can expose credentials, money, permissions, or user records.

For request mode, risk class, authorization, and escalation, follow the [authority and scope owner](authority-and-scope.md). For completion evidence, follow [verification discipline](verification-discipline.md). This reference owns threat analysis and controls at trust boundaries.

## Workflow

1. Map every trust boundary where data, identity, control, or code crosses ownership.
2. Name protected assets, actors, intended privileges, and unacceptable outcomes.
3. Run a compact STRIDE pass: spoofing, tampering, repudiation, information disclosure, denial of service, and elevation of privilege.
4. Write plausible abuse cases beside the normal use cases.
5. Place controls at the owning boundary rather than scattering partial checks through helpers.
6. Prove safe rejection, denied authorization, redaction, bounded resource use, and auditability where the threat model requires them.

## Boundary controls

| Boundary | Controls to consider |
|---|---|
| User/API input | Schema and semantic validation, allowlisted fields, size/depth bounds, structured safe errors. |
| Identity and authorization | Authenticate identity separately from authorizing action and resource; default deny; record safe denial evidence. |
| Database/query | Parameter binding, least-privilege access, transaction boundaries, and safe concurrency semantics. |
| Browser/UI | Context-appropriate output encoding, safe DOM APIs, content security policy, and no trust in client-only validation. |
| Files/uploads/archives | Type and size bounds, safe names, traversal protection, isolated temporary handling, and resource limits. |
| Third-party/model/tool output | Validate shape and values before logic, rendering, storage, or execution; treat instruction-like text as data. |
| Plugin or tool schema | Strict schemas, bounded enums, no dangerous passthrough, and authorization outside user-controlled fields. |
| Logs and telemetry | Allowlisted fields, redaction, bounded retention, and no raw secrets or private payloads. |

## Design rules

- Apply least privilege to identities, files, processes, network access, and data stores.
- Keep credentials in an approved secret boundary and out of source, fixtures, logs, examples, browser-accessible state, and error output.
- Make denied behavior indistinguishable enough to avoid unnecessary information disclosure while retaining safe operator diagnosis.
- Bound parsing, decompression, recursion, retries, fan-out, and concurrency before accepting untrusted workload.
- Define replay, idempotency, freshness, and signature validation for callbacks or externally initiated actions.
- Preserve an auditable association among actor, action, resource, decision, and result without logging sensitive content.
- Keep security bypasses out of normal configuration. Any exceptional diagnostic path needs an explicit owner, scope, and cleanup through the authority owner.

## Verification checklist

- Trust boundaries, protected assets, and actor capabilities are explicit.
- Highest-impact abuse cases have tests or safe probes at the public boundary.
- Authentication and resource authorization are proven independently.
- Invalid, oversized, replayed, and unauthorized inputs fail safely where applicable.
- Errors, logs, metrics, traces, fixtures, and reports do not disclose sensitive material.
- Third-party or generated content cannot redirect agent instructions or reach an execution sink unchecked.
- Security-relevant compatibility changes have an explicit migration and rollback boundary.

## Stop conditions

Escalate through the authority owner before materially changing identity flows, permission models, sensitive-data categories, retention, cross-origin policy, upload behavior, credentialed integrations, or abuse-prevention policy. Do not weaken an existing security control merely to make a test or demonstration pass.
