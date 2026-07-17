---
{
  "card_id": "sqw.domain.runtime.version-and-consistency",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.domain.runtime.version-and-consistency",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "domain-runtime-version-and-consistency"
  ],
  "max_bytes": 8192
}
---
# Runtime Version and Consistency

## Decision this card owns
Select an explicit runtime boundary and reconcile every declaration, consumer, generated surface, and managed-runtime smoke against it.

## Use when
- Declared support conflicts with syntax/API/module/flag behavior, or runtime declarations/consumers may disagree.

## Do not use when
- Runtime support is unaffected and no consistency surface changes.

## Required inputs
- `workflow-intake`; advertised range and exact versions; manifests/locks/docs/CI/containers/generated/package/installers/adapters; questioned core/optional/build/public feature; consumers; exact bad/good/public probes; compatibility/retirement constraints; environment authority.

## Procedure
1. Inventory all support declarations and consumers. Probe the exact lowest advertised and nearest bad/good versions through the real import/parse/build/start/public path; preserve versions, statuses, and cause classes.
2. Keep environment acquisition separately authorized; prefer installed, pinned, container, or CI evidence and never download a runtime implicitly.
3. Select one outcome: raise floor, semantically bounded compatibility, genuinely optional isolation with observable absence, or `unverified` with exact missing environment/claim. Reject broad dependencies hidden by narrow exceptions.
4. For a raised floor update canonical declaration plus locks/docs/CI/container/generated/installer checks and prove clear below-boundary rejection plus first-supported success. For compatibility, characterize both sides under one public contract with allowed differences, owner, limits, and retirement.
5. Reconcile code/config/tests/docs/CI/packaging/generated/installers/examples/templates/CLI preflight/protocol/plugin/service adapters and dormant surfaces; stale prose alone is not runtime failure and local success is not consistency proof.
6. For a managed-runtime SDK smoke, freeze one declared combination, create a clean task-owned environment, record actual executable/runtime/package/lock/source and authoritative runner, then run import plus smallest meaningful public entrypoint with redacted output.
7. Classify supported/failed/not-addressable, separate provisioning from product, list adjacent untested combinations, and preserve replay command/evidence. If unavailable, record strongest static proof, exact unverified claim, and precise follow-up without unapproved setup.
8. Report focused, affected, public, and canonical evidence separately; clean only task-owned runtime state.

## Output contract
- One `domain-runtime-version-and-consistency` with selected range/outcome, version probe matrix, consumer impact, compatibility/optional contract, cross-surface matrix and changed declarations, below/at-boundary and managed-runtime smoke results, runner provenance, unverified follow-up, retirement, cleanup, gaps, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at explicit cross-surface evidence; never call an unavailable or adjacent boundary proven or mutate environments without authority.
