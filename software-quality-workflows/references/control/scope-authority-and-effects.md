# Scope, Authority, and Effects

## Purpose
Freeze the smallest coherent owner, request mode, scope, durability need, and effect boundary before work proceeds.

## Use when
- Any owner seam, instruction authority, dirty/concurrent scope, durable-state need, probe, external effect, or cleanup boundary is unresolved.

## Do not use when
- A fresh bound decision already covers the unchanged intake, source, authority, workspace, and proposed effects.

## Required inputs
- task context; instruction stack; callers/owners/dependencies; logical root and revision; status/diff; proposed reads/writes/resources/effects; credentials/cost; recovery horizon; and rollback/cleanup evidence.

## Procedure
1. Apply instruction precedence and classify `report`, `review`, `diagnose`, `change`, `recovery`, or `plan` from the requested outcome; read-only work stays read-only unless separately authorized.
2. Trace caller to outcome and select the smallest existing owner seam that expresses the entire distinction. Reject pass-through wrappers, parallel implementations, speculative extension points, and hidden public-contract changes.
3. Freeze one source/scope identity for reads, edits, scans, tests, review, staging, and reporting. Classify tracked, untracked, ignored, generated, vendor, binary, renamed, deleted, protected, dirty, and concurrent paths explicitly.
4. Keep same-session local reversible work Direct. Use durable coordination only for cross-context recovery, destructive/external effects, staged migration/release/rollout, multiple authorized writers, or a requested recoverable audit trail. File count, token count, worker availability, and subjective complexity never create durability.
5. Classify actual effects as `READ_ONLY`, `LOCAL_REVERSIBLE`, `EXTERNAL_STATE`, or `PRIVILEGED_DANGEROUS`. Command names and dry-run labels are not evidence.
6. Bind external targets, credentials/cost, approvals, idempotency/retry, persistent processes, and publication separately. Privileged, destructive, ambiguous, or unauthorized effects block.
7. For a probe, allocate task-unique paths/resources/ports, redaction, attempt/time/cost ceilings, residue policy, and cleanup proof. Reject traversal, unsafe links, shared temp paths, and ambiguous candidate counts.
8. Preserve unrelated work and clean only certainly task-owned artifacts. Emit typed escalation for multi-owner/public/migration/architecture ambiguity rather than widening scope or authority.

## Required result
- Request mode, owner seam, source/scope/protected identity, Direct or durable disposition, allowed reads/writes/resources/effects, risk class, approvals/publication ceiling, probe/cleanup/rollback contract, escalation, and blocker.

## Stop
Stop before any unowned write, uncertain cleanup, ungranted external/destructive effect, or materially broader technical route.
