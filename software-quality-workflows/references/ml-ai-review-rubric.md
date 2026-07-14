# ML and AI Review Rubric

Load this rubric only when the scoped change touches training, evaluation, datasets, feature or prompt pipelines, notebooks used as source, checkpoints, inference, model serving, experiment claims, or private data used by ML systems.

For trivial formatting or naming changes in ML-adjacent code, apply it lightly. Exploratory work that makes no production or scientific claim does not automatically need production-grade evidence.

Use `references/review-result-schema.md` for findings and `references/verification-discipline.md` to classify evidence. This rubric adds domain questions; it does not redefine either contract.

## Baselines and claims

- Identify the relevant baseline and whether compared code, data, metric definitions, budgets, and environments are commensurate.
- Check that metrics reflect the stated scientific or product objective and important failure modes.
- Require repeated runs, seed variance, confidence intervals, or stratified results only when the strength of the claim needs them.
- Distinguish exploratory observations from a claimed improvement, regression-free replacement, or release decision.

A material finding exists when a stated quality improvement cannot be supported by comparable evidence, not merely because another plot would be interesting.

## Data discipline

- Inspect train, validation, test, temporal, user, and session boundaries for target or evaluation leakage.
- Check duplicate handling, schema and unit validation, label meaning, missing values, and feature ranges at the owning boundary.
- Preserve provenance across raw, intermediate, curated, and evaluation data, including the snapshot used for each claim.
- Keep private, regulated, or user data out of logs, examples, fixtures, notebooks, screenshots, and repository history unless explicitly authorized and protected.
- Confirm that prompt selection, feature selection, and hyperparameter tuning did not consume held-out evaluation information.

## Reproducibility and artifacts

- Record code revision, configuration, seeds, dependency/runtime versions, data snapshot, tuning budget, and model/checkpoint identifiers needed to reproduce or audit the result.
- Make notebooks reviewable: avoid hidden-state-only conclusions, unexplained outputs, or an untracked gap between notebook and executed pipeline.
- Version input/output contracts and retain provenance between a model registry entry, packaged artifact, configuration, and the code that produced it.

## Training and inference parity

- Compare tokenization, preprocessing, feature engineering, normalization, batching, model inputs, and postprocessing across training, offline scoring, and serving.
- Check online/offline skew, batch/online differences, default values, precision/device changes, and fallback behavior.
- Require a focused load-and-predict or pipeline smoke when code inspection alone cannot establish artifact compatibility.

## Validation, capacity, and operations

- Select focused tests for transforms, metrics, losses, config parsing, schema checks, artifact loading, and representative inference behavior.
- Use a lightweight train/infer smoke when a full run is disproportionate; do not present it as full experimental validation.
- Compare memory, latency, throughput, I/O, dataset scale, parallelism, and cost against known budgets when the change affects them.
- For production paths, check data-quality signals, drift or performance monitoring, model/version traceability, diagnosable partial failures, and a suitable rollback or retrain path.

Likely material issues include evaluation leakage, private-data exposure, untraceable artifacts, train/serve skew, an unreproducible central claim, or a production model that can silently emit bad output. Additional seeds, plots, or future monitoring are usually non-blocking for explicitly exploratory offline work.

When a qualified scientific, privacy, safety, or domain judgment is still needed, create a non-code-fixable finding describing the exact decision and evidence required. Do not guess that approval and do not send it to a fixer.
