---
{
  "card_id": "sqw.review.rubrics.ci-release",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "rubric_review_contract",
    "bounded_change_material",
    "delivery_pipeline_contract"
  ],
  "produces": [
    "ci_release_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# CI and Release Rubric

## Decision this card owns
Identify regressions in build, CI, artifact, migration, deployment, and rollback readiness caused by the scoped change.

## Use when
- Build/CI configuration, generated artifacts, packaging, migrations, deployment, feature rollout, or release gates are affected.

## Do not use when
- No delivery path changes and existing release evidence fully covers the change.

## Required inputs
- Frozen delivery contract, affected pipeline/artifact/deployment paths, local-versus-CI evidence, release controls, and result-envelope contract.

## Procedure
1. Check required build, lint, type, test, security, generated-file, packaging, and artifact gates for preservation and correct ordering.
2. Compare local and CI execution environments, commands, inputs, caches, permissions, and built/installed layers for hidden divergence.
3. Treat removed, bypassed, weakened, or conditional gates as findings unless an equivalent verified control replaces them.
4. Check migration ordering, compatibility windows, smoke checks, canary/rollout controls, observability, and rollback/forward-recovery for affected releases.
5. Emit only scoped delivery failures with the smallest pipeline or release-control correction and executable verification.

## Output contract
- Zero or more local finding candidates with affected gate/stage, evidence, delivery impact, correction, confidence, blocking, and verification.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at CI/release evidence; do not operate deployment systems or rewrite the pipeline.
