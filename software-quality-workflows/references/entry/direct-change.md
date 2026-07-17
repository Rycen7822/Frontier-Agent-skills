---
{
  "card_id": "sqw.entry.direct-change",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "sqw.select.entry.direct-change",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "workflow-intake"
  ],
  "max_bytes": 4096
}
---
# Direct Change Entry

## Decision this card owns
Form the smallest authorized change intake without selecting downstream work by prose.

## Use when
- Intent is defined, cause is known or inapplicable, change authority exists, and recovery is inactive.

## Do not use when
- The request is read-only, the cause is unknown, intent is materially open, or repository recovery has precedence.

## Required inputs
- Observable outcome, source/scope/authority/effect facts, protected work, existing patch, owner/proof evidence, and implicated surfaces.

## Procedure
1. Bind outcome, source, allowed writes/effects, protected dirty/concurrent work, publication ceiling, and cleanup boundary.
2. State the falsifiable before/after distinction; for a bug bind the supported cause, original reproduction, and regression oracle.
3. Preserve existing work and identify the smallest coherent owner seam; do not add parallel implementations, speculative seams, or unrelated cleanup.
4. Record public/API, architecture, runtime, security, data, plugin, performance, browser, observability, dependency, and migration implications as typed facts.
5. Record focused and affected/public proof needs, false-green risk, residue/generated/dependency inspection, and all not-run or blocked gates.
6. Emit `workflow-intake` plus at most one schema-valid decision request for the earliest unresolved mapped decision; never name or load a card directly.

## Output contract
- One `workflow-intake` with identities, seam, distinction, protected surfaces, implications, proof needs, existing-work disposition, blocker, and optional typed decision request.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the intake or blocker; do not implement, approve, publish, or infer completion.
