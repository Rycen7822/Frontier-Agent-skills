# Skill Evaluation Report: {{EVALUATION_ID}}

> Keep only sections supported by the selected level and declared controls. Delete inapplicable sections. Put missing required evidence under **Known gaps**; placeholders never count as evidence.
> Copy analyzer facts exactly. This file is an interpretation and external-decision overlay, not a second schema or evidence source.

## Status

```yaml
schema_version: 4
evaluation_id: {{immutable evaluation ID}}
plan_id: {{compiled plan ID}}
analysis_ready: {{true|false}}
applicability_status: {{applicable|not_applicable}}
feasibility_status: {{feasible|unsupported|not_evaluable}}
evidence_status: {{complete|incomplete|invalid}}
usefulness_status: {{supported|not_supported|inconclusive_ceiling|not_evaluable}}
final_authority_status: {{eligible|blocked}}
subject: {{skill ID/version/shape/package hash}}
counts: {{plan/execute/unsupported/not-evaluable/attempt/valid/invalid/missing}}
blocking_observations: []
```

These five axes remain separate. `supported` is not a release decision; `eligible` means only that the frozen evidence may proceed to its declared external authority.

## 1. Identity and scope

- Summary/spec/scenario/host/plan hashes:
- Subject package and declared treatment identities/intervention axes:
- Model, harness, host, catalog, tool/policy, compiler, clock, tokenizer/pricing identities:
- Required/not-applicable modules and evidence:
- Authority, permissions, network, credentials, artifacts, retention, and claim ceiling:
- L3/L4 only — holdout manifest/payload custody and exposure:

## 2. Package audit — L0+

- Provenance, inventory, links, and progressive-disclosure findings:
- Scripts, dependencies, network, permissions, and side effects:
- Static findings and controlled runtime probes actually run:
- Text-scan completeness, opaque surfaces, and unresolved risks:
- Audit-only claim boundary:

## 3. Method — L1+

- Frozen scenario × treatment × repeat plan, dispositions, order, reset, isolation, and host protocol:
- Scenario v1 `requirements[]`, state/fault/routing/coordination/observation contracts:
- Deterministic/model graders and preparation artifacts actually used:
- Safety containment, protected scenarios, and host boundaries:
- L2+ — case-cluster estimand, interval configuration, and hard gates:
- Contract changes or invalidated evidence:

## 4. Receipt integrity and run accounting — L1+

- Plan v3, run index v3, receipt v5, summary v6, and failure-index v2 verification:
- Planned/execute/unsupported/not-evaluable entry counts:
- Attempts, valid terminal attempts, invalid attempts, and missing entries:
- Recomputed scenario/host/package/catalog/treatment/fixture/grader/calibration/quality/artifact/invocation bindings:
- Output-manifest paths, view versions, counts, truncation, and external byte bindings:
- Trust boundaries still externally attested or unverified:
- Representative failure IDs and exact locators:

## 5. Modules and stages — L1+

- Module status/planned/present/valid/invalid/missing/eligible/pass-rate/consistency:
- Plan exists/contract-quality/compliance/execution/outcome stages:
- Applicable routing, state, fault, coordination, action/safety, observation/grounding, critique, independence, and host stages:
- Hard requirement IDs, failure mechanisms, worst slices, and reason keys:
- Decisive failure IDs and evidence locators:

## 6. Independent-case attribution — L2+

- Candidate/comparator identities:
- Primary estimand/metric/direction/effect/minimum benefit:
- Distinct `case_count` / `excluded_pairs`:
- Keyed direction-normalized `case_differences`:
- Benefit point / lower / upper:
- Confidence level / iterations / seed / case-cluster resampling:
- Missing fields, relative-zero handling, or attribution limits:

Repeats are not independent inferential samples.

## 7. Frozen gates and usefulness — L2+

- `primary_benefit` status and interval:
- Required gate-family failure IDs, expected/observed facts, and locators:
- Quality, calibration, module, host, context, protected, safety, noninferiority, and manual boundaries:
- Exact derivation of `usefulness_status` and `final_authority_status`:
- Contrary cases that remain after passing summary rates:

## 8. Skill context and total cost — L1+

- Attribution coverage:
- Paired total, controlled, and controlled-core Skill-context byte metrics:
- Input/output/cache token classes and pricing identities:
- Queue/runtime latency and per-principal/turn/phase/call totals:
- Tool/network calls, retries/rework, requested/effective effort:
- Workflow artifacts, checkpoints, residue, and failure/recovery overhead:
- Provider-cache versus application-cache status:
- Frozen context gates and external authority boundary:

Report Target-Skill context separately from total run usage. Do not derive token counts from bytes.

## 9. Manual authority — only when declared

- Receipt path/hash and reviewer role:
- Decision and attestation:
- Required evidence objects and recomputed hashes:
- Signature text present; cryptographic verification not performed:
- Effect on `final_authority_status`:

## 10. Version/cycle monitoring — L4 only

- Prior/candidate package and cycle identities:
- Contract/plan/host/module/environment comparability:
- Protected regression, context, cost, safety, host, and drift results:
- Rollback target and incident/retest triggers:
- Orchestration boundary: no library-scale claim without verified selection/order/composition receipts:

## 11. Findings

### {{FAILURE-ID}} — {{family/code}}

- Severity, reason key, and evidence state:
- Typed case/treatment/entry/attempt/requirement/principal/handoff/action/observation/fault/gate/finding joins:
- Expected/observed facts and exact locator:
- Impact, retest, and occurrence count:

## 12. Known gaps

| Gap | Cause | Affected claim | Blocking? | Required next evidence |
|---|---|---|---|---|
| | | | | |

## 13. External decision record — only after authority acts

- External owner and decision:
- Evidence bundle reviewed:
- Accepted residual risks:
- Monitoring/rollback obligations:

The named external authority issues this record after reviewing analyzer eligibility and retained evidence.

## 14. Artifact manifest

- Summary v5 and sibling `output_manifest`:
- Failure index v2 and full details when emitted:
- Markdown view when emitted:
- Bound spec/plan/scenario/host/index/receipt/artifact/package/grader/preparation identities and external digests:
- Package audit and environment identity:
- Manual-review receipt when declared:
- Cleanup verification:
