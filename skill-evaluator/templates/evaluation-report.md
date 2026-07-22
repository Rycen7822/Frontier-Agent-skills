# Skill Evaluation Report: {{EVALUATION_ID}}

> Keep only sections supported by the selected level and declared controls. Delete inapplicable sections. Put missing required evidence under **Known gaps**; placeholders never count as evidence.

## Status

```yaml
level: {{L0|L1|L2|L3|L4}}
evidence_status: {{complete|incomplete|invalid}}
usefulness_status: {{not_applicable|supported|not_supported|inconclusive}}
final_authority_status: {{eligible|blocked}}
decision_signal: {{analyzer decision signal}}
evaluation_id: {{immutable ID}}
target: {{skill version + package hash}}
baseline: {{declared baseline identity; L2+ only}}
claim_scope: {{model/harness/suite/environment}}
blocking_observations: []
```

These fields remain separate. `supported` is not a release decision; `eligible` means only that the frozen evidence may proceed to its declared external authority.

## 1. Identity and scope

- Candidate revision/source-tree/plugin-tree and target package hash:
- Treatment and catalog identities:
- Model, harness, system configuration, and environment fingerprint:
- Spec/schema, cases, case contracts, fixture set, grader set/schedule, and analyzer revisions:
- Authority, permissions, network, and credentials boundary:
- Declared variants/repeats and claim ceiling:
- L3/L4 only — holdout manifest/payload custody and exposure:

## 2. Package audit — L0+

- Provenance, inventory, links, and progressive-disclosure findings:
- Scripts, dependencies, network, permissions, and side effects:
- Static findings and controlled runtime probes actually run:
- Text-scan completeness, opaque surfaces, and unresolved risks:
- Audit-only claim boundary:

## 3. Method — L1+

- Frozen cases, variants, repeats, run order, reset, and isolation:
- Canonical `requirements[]` and declared grader ownership:
- Deterministic/model/manual graders actually used:
- Safety containment and protected cases:
- L2+ — case-cluster interval configuration and designated benefit gate:
- Contract changes or invalidated evidence:

## 4. Receipt integrity and run accounting — L1+

- Receipt-index version and immutable raw-bytes path/hash:
- Receipt v2 and arm-report v2 self-hash verification:
- Receipt verification status and checked-run count:
- Recomputed fixture/package/artifact/grader/provenance/invocation bindings:
- Trust boundaries still externally attested or unverified:

| Variant | Planned | Present | Valid | Invalid | Timed out | Missing |
|---|---:|---:|---:|---:|---:|---:|
| | | | | | | |

- Duplicate or mismatched `variant × case_id × repeat` keys:
- Missing/invalid key sample and affected claim:

## 5. Routing and outcome — L1+

- Explicit/implicit/contextual/negative routing slices:
- False positives, false negatives, and stage localization:
- Deterministic required-outcome and case-grader failures:
- Process, recovery, termination, cleanup, and residue:
- Decisive case IDs and evidence locators:

## 6. Independent-case attribution — L2+

- Baseline/candidate identities:
- Distinct case count (`paired_case_count`):
- Descriptive repeat-level pair count (`run_pair_count`):
- Wins / losses / tie-pass / tie-fail:
- Case-mean lift point / lower / upper:
- Confidence level / iterations / seed / `resampling_unit=case_id`:
- Candidate-only and baseline-only failures:
- Missing paired fields or attribution limits:

Repeats are not independent inferential samples.

## 7. Frozen gates and usefulness — L2+

| Gate | Role | Metric | Rule | Observed | Status |
|---|---|---|---|---:|---|
| | benefit/guardrail | | | | pass/fail/not_evaluable |

- Protected-outcome failure count and affected keys:
- Material safety harm:
- Exact derivation of `usefulness_status`:
- Contrary cases that remain after aggregate gates:

## 8. Skill context and total cost — L1+

- Intended-trigger denominator / complete attributed runs:
- Attribution rate and measurement-source counts:
- Verified Skill body/resource component bytes:
- Host-receipt component tokens, when present:
- Skill-context bytes/tokens p95 and frozen budget gate:
- Context-budget authority reference and verification boundary:
- Captured-zero versus missing context rows:
- Host/model body loads, reference/load/protocol/prewrite/task calls, workflow artifacts, and prewrite output bytes:
- End-to-end input/output tokens, latency, retries, and residue:

Report Target-Skill context separately from total prompt/run usage. Do not derive token counts from replay-manifest bytes.

## 9. Manual authority — only when declared

- Receipt path/hash and reviewer role:
- Decision and attestation:
- Required evidence objects and recomputed hashes:
- Signature text present; cryptographic verification not performed:
- Effect on `final_authority_status`:

## 10. Version/cycle monitoring — L4 only

- Prior/candidate package and cycle identities:
- Contract/environment comparability:
- Protected regression, context, cost, safety, and drift results:
- Rollback target and incident/retest triggers:
- Orchestration boundary: no library-scale claim without verified selection/order/composition receipts:

## 11. Findings

### {{FINDING-ID}} — {{title}}

- Severity, dimension, and cases:
- Evidence status and confidence basis:
- Observed fact and exact locators:
- Impact and root-cause status:
- Required action and retest:

## 12. Known gaps

| Gap | Cause | Affected claim | Blocking? | Required next evidence |
|---|---|---|---|---|
| | | | | |

## 13. External decision record — only after authority acts

- External owner and decision:
- Evidence bundle reviewed:
- Accepted residual risks:
- Monitoring/rollback obligations:

Do not infer this record from analyzer eligibility.

## 14. Artifact manifest

- Spec and public/holdout case bindings:
- Receipt index, receipts, artifacts, and grader outputs:
- Package inventory and environment fingerprint:
- Analyzer arm-report v2 JSON/Markdown, raw report hash, and package audit:
- Manual-review receipt when declared:
- Cleanup verification:
