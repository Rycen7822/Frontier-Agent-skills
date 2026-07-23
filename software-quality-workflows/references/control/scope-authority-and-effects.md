# Scope, Authority, and Effects

## Purpose
Freeze the smallest coherent owner, request mode, scope, durability need, and effect boundary before work proceeds.

## Known read-only/local boundary
When the user already binds the target, protected paths, and forbidden effects:
- accept those boundaries;
- permit only reads and declared local proof;
- do not inspect Git authorship, filesystem ownership, refs, object inventory, credentials, rollback, or publication unless one is material to the request;
- stop before the first write or external effect.

This fast path takes precedence; do not continue into the full procedure.

## Use when
- Write scope; protected, dirty, or concurrent work; destructive, external, or privileged effects; a materially relevant source root or revision; multiple owners or writers; or authority for the proposed effect is unresolved.

## Do not use when
- The known-boundary fast path applies, or a fresh decision already covers the unchanged material boundary.

## Required inputs
- Collect only fields needed to resolve the current uncertainty.

## Procedure
1. Apply instruction precedence and classify `report`, `review`, `diagnose`, `change`, `recovery`, or `plan` from the requested outcome; read-only work stays read-only unless separately authorized.
2. Trace caller to outcome and select the smallest existing owner seam that expresses the entire distinction. Reject pass-through wrappers, parallel implementations, speculative extension points, and hidden public-contract changes.
3. Bind source root/revision only when material. Identify only protected, dirty, concurrent, generated, or external paths that affect the requested outcome.
4. Keep same-session local reversible work Direct. Use durable coordination only for cross-context recovery, destructive/external effects, staged migration/release/rollout, multiple authorized writers, or a requested recoverable audit trail. File count, token count, worker availability, and subjective complexity never create durability.
5. Classify actual effects as `READ_ONLY`, `LOCAL_REVERSIBLE`, `EXTERNAL_STATE`, or `PRIVILEGED_DANGEROUS`. Command names and dry-run labels are not evidence.
6. Bind external targets, credentials/cost, approvals, idempotency/retry, persistent processes, and publication separately. Privileged, destructive, ambiguous, or unauthorized effects block.
7. For a probe, allocate task-unique paths/resources/ports, redaction, attempt/time/cost ceilings, residue policy, and cleanup proof. Reject traversal, unsafe links, shared temp paths, and ambiguous candidate counts.
8. Preserve unrelated work and clean only certainly task-owned artifacts. Emit typed escalation for multi-owner/public/migration/architecture ambiguity rather than widening scope or authority.

## Required result
- Record only decisions needed to bind the unresolved scope, authority, source, effect, recovery, escalation, or blocker.

## Stop
Stop before any unowned write, uncertain cleanup, ungranted external/destructive effect, or materially broader technical route.
