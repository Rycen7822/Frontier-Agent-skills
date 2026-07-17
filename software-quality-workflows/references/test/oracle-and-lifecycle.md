---
{
  "card_id": "sqw.test.oracle-and-lifecycle",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "sqw.select.test.oracle-and-lifecycle",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "test-oracle-and-lifecycle"
  ],
  "max_bytes": 8192
}
---
# Test Oracle and Lifecycle

## Decision this card owns
Prove oracle quality and govern the meaning, provenance, movement, replacement, quarantine, or retirement of durable tests.

## Use when
- A test's independence/sensitivity or its purpose, layer, lifecycle, owner, gate, replacement, or retention is in question.

## Do not use when
- Only implementation behavior or gate execution changes and no test meaning or retention boundary changes.

## Required inputs
- `workflow-intake`; behavior distinction; test/implementation source; expected-value provenance; doubles/fixtures; plausible defects; requirement/risk anchors; test/gate inventory; authority; replacement and transition evidence.

## Procedure
1. Trace expected values to a requirement, literal worked example, independent reference, stable external fixture, or property/metamorphic relation. Reject production helpers/generators/parsers computing their own expected result.
2. Name and, when proportionate, inject a plausible wrong implementation. Add a fixed expectation/property for shared round trips; use real collaborators except at genuinely external, destructive, unavailable, costly, or nondeterministic boundaries.
3. Prefer public behavior over private call order and cover contract-owned errors, limits, transitions, negative paths, and externally meaningful serialization/migration fixtures.
4. Classify purpose as requirement, regression, characterization, migration, adversarial, or smoke; layer as unit, component, integration, end-to-end, installed-surface, or external-system; lifecycle as active, quarantined, superseded, or retired.
5. Record stable identity, anchor, owner, canonical gate, replacement/transition evidence, and review trigger with the project's lightest searchable convention; never infer lifecycle from age, path, duration, or current failure.
6. Keep unique current protection; merge only with equal oracle/localization; update only for an authorized changed contract; promote only after scaffold/characterization becomes durable evidence.
7. Quarantine visibly with failure signature, environments, gate treatment, owner, repair criterion, and forced review. Supersede only with equal/stronger replacement and a confirmation window that retires or restores the old test.
8. Retire only when the requirement/risk is removed or approved replacement makes it irrelevant. Search all test/fixture/script/gate anchors, prove replacement coverage, preserve the cheapest sufficient observable oracle and explicit gate, and run transition plus affected proof.

## Output contract
- One `test-oracle-and-lifecycle` with oracle adequacy/provenance/sensitivity, false-green risks, per-test purpose/layer/lifecycle/owner/gate, authorized action, before/after location, replacement/confirmation proof, retained protection, cleanup, residual limits, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop completion when an oracle agrees with a plausible defect; never weaken or retire a valid contract merely to make implementation pass.
