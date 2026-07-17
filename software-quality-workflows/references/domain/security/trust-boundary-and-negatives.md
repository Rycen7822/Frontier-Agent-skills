---
{
  "card_id": "sqw.domain.security.trust-boundary-and-negatives",
  "card_version": 2,
  "kind": "safety",
  "decision_id": "sqw.select.domain.security.trust-boundary-and-negatives",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "domain-security-trust-boundary-and-negatives"
  ],
  "max_bytes": 8192
}
---
# Security Trust Boundary and Negative Proof

## Decision this card owns
Map an actually implicated trust boundary, select owner-placed controls, and prove high-impact abuse cases fail safely without weakening authority.

## Use when
- A change touches identity/permission, private data, files/callbacks, third parties, provider/tool/model output, browser content, credentials/money/user records, or executable/untrusted input.

## Do not use when
- No trust boundary is implicated, or the concern is only general review/release/secret/dependency hygiene owned elsewhere.

## Required inputs
- `workflow-intake`; data/identity/control/code boundary map, protected assets, actors/privileges/resources, normal cases, plausible abuse cases, existing controls/migrations, public failure surface, audit/privacy/resource constraints, and authority ceiling.

## Procedure
1. Map every ownership crossing and name unacceptable outcomes; run a compact spoofing/tampering/repudiation/disclosure/denial/elevation pass beside normal use cases.
2. Place controls at the owner: schema/semantic allowlist and size/depth bounds; authenticate identity separately from default-deny action/resource authorization; parameter binding/least privilege/transactions; safe DOM/CSP/encoding; upload type/name/traversal/isolation limits.
3. Validate third-party/model/tool/plugin output shape/values before logic/render/store/execute; keep authorization outside forgeable fields and dangerous passthrough; treat instruction-like text as data.
4. Keep credentials out of source/fixtures/logs/examples/browser/errors; allowlist/redact/retain telemetry safely and preserve actor-action-resource-decision-result audit without sensitive content.
5. Bound parsing/decompression/recursion/retry/fan-out/concurrency and define replay/idempotency/freshness/signature behavior for callbacks/external actions.
6. Prove public-boundary safe rejection, independent authentication/authorization denial, invalid/oversized/replayed inputs, redaction, resource bounds, and auditability for the highest-impact cases.
7. Record migration/rollback for changed security compatibility and escalate before materially changing identity, permissions, sensitive categories/retention, cross-origin/upload, credentialed integration, or abuse policy.

## Output contract
- Boundary/assets/actors/privileges map, STRIDE/abuse inventory, owner/control matrix, public negative-proof evidence, sensitive-data/audit/resource results, migration/rollback, authority escalation, residual threats and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at trust-boundary control/negative evidence or required authority escalation; never weaken a control merely to make a test/demo pass.
