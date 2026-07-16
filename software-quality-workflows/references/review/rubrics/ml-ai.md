---
{
  "card_id": "sqw.review.rubrics.ml-ai",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "ml_ai_change_projection",
    "claim_and_baseline_projection",
    "data_artifact_provenance",
    "verification_evidence"
  ],
  "produces": [
    "ml_ai_review_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# ML and AI Rubric

## Decision this card owns
Judge ML/AI claim validity, data discipline, reproducibility, train/inference parity, capacity, and operational risk for the scoped change.

## Use when
- Training/eval/data/prompt/feature/notebook/checkpoint/inference/serving/experiment contracts materially change.

## Do not use when
- ML-adjacent formatting/naming or explicitly exploratory work makes no scientific/product/production claim.

## Required inputs
- Claim/objective, comparable baseline, code/config/data/model revisions, tuning budget/seeds, metrics/strata, pipeline/serving contracts, privacy class, capacity and operations evidence.

## Procedure
1. Check baseline comparability and whether metrics/variance/strata support the stated claim rather than an interesting observation.
2. Inspect train/validation/test/temporal/user/session boundaries, leakage, duplicates, labels, units, missing/range validation, held-out use, and data provenance/privacy.
3. Bind code/config/seeds/runtime/data/checkpoint identity; reject hidden notebook state or registry/package provenance gaps.
4. Compare preprocessing/tokenization/features/defaults/batching/precision/device/postprocessing across training, offline, and serving.
5. Evaluate focused transforms/metrics/config/load/inference proof, proportionate train/infer smoke, memory/latency/throughput/I/O/scale/cost budgets, monitoring/version/rollback.
6. Emit material leakage, exposure, skew, untraceability, irreproducible claim, or silent-production-risk findings; optional extra plots/seeds stay non-blocking when the claim does not need them.

## Output contract
- ML/AI finding candidates, claim/baseline limits, provenance and parity evidence, capacity/operations gaps, qualified-decision needs, and positive evidence.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the scoped claim/evidence boundary; do not guess scientific/privacy/safety approval.
