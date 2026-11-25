# Security boundaries

Use only when the reviewed change implicates identity, authorization, private data, untrusted input or a consequential external effect.

Trace the actual trust crossing and the unacceptable outcome. Place validation and authorization at the owning boundary, not in forgeable data supplied by the caller. Authentication does not establish permission for an action on a resource. Validate third-party, model and tool data before it drives storage, rendering or execution.

Inspect the relevant constraints: input shape and size, path/URL handling, parameter binding, output encoding, least privilege, replay/idempotency and resource bounds. Prioritize realistic high-impact abuse cases alongside intended use; do not fill a generic threat checklist.

Check that denial happens through the public boundary with safe errors and no unauthorized side effects. Preserve credentials and private payloads from logs, fixtures and reports. Keep audit signals useful without exposing the protected data. Never weaken a control to make a demonstration pass.

Explain compatibility and operational consequences when changing a real security contract. Escalate a consequential unresolved policy choice; do not turn ordinary boundary verification into a blanket approval requirement.
