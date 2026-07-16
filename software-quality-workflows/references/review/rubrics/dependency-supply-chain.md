---
{
  "card_id": "sqw.review.rubrics.dependency-supply-chain",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "rubric_review_contract",
    "bounded_change_material",
    "dependency_artifact_contract"
  ],
  "produces": [
    "dependency_supply_chain_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Dependency and Supply-Chain Rubric

## Decision this card owns
Identify dependency, provenance, packaging, and build-input risks introduced or materially worsened by the scoped change.

## Use when
- Dependencies, lockfiles, package registries, install/build scripts, binaries, containers, base images, or release artifacts change.

## Do not use when
- No dependency or build-input surface changes and the claim belongs to CI operation or application security.

## Required inputs
- Frozen dependency/artifact contract, manifests and locks, provenance/integrity evidence, build/container changes, and result-envelope contract.

## Procedure
1. Check necessity, maintenance posture, license/policy compatibility, trusted source, version constraints, and update strategy for changed dependencies.
2. Compare manifests, resolved lock state, checksums/signatures/provenance, transitive impact, install hooks/scripts, vendored code, and produced binaries.
3. Inspect container base-image pinning, package residue, build/runtime separation, unexpected admin/debug tools, and reproducibility of the delivered artifact.
4. Verify scanning or policy gates were not disabled or narrowed to make the change pass; tool output alone does not prove provenance or necessity.
5. Emit only concrete change-caused supply-chain findings with smallest correction, safe verification, and explicit uncertainty where evidence is unavailable.

## Output contract
- Zero or more local finding candidates with affected dependency/artifact, evidence, provenance or delivery impact, correction, confidence, blocking, and verification.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at dependency/supply-chain evidence; do not install, publish, or mutate registries.
