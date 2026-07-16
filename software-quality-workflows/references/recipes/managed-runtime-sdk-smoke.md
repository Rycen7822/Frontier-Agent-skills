---
{
  "card_id": "sqw.recipes.managed-runtime-sdk-smoke",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "declared_runtime_matrix",
    "sdk_entrypoint",
    "runner_provenance"
  ],
  "produces": [
    "managed_runtime_smoke_evidence"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Managed-Runtime SDK Smoke

## Decision this card owns
Establish whether the declared SDK import and smallest meaningful entrypoint work under an addressable managed-runtime combination.

## Use when
- A managed language/runtime SDK surface needs a bounded compatibility smoke check rather than a full integration suite.

## Do not use when
- The runtime combination is undeclared, cannot be provisioned safely, or the claim requires production/integration behavior.

## Required inputs
- Declared supported matrix, exact SDK import/entrypoint, clean environment contract, dependency lock or package identity, and authoritative runner provenance.

## Procedure
1. Freeze the declared runtime/SDK combination and the exact claim being tested; do not infer support from an adjacent version.
2. Start from a clean task-owned environment and record the actual executable, runtime, package, lock/source revision, and official runner or entrypoint.
3. Exercise the import and the smallest meaningful public entrypoint, capturing status and minimal redacted output.
4. Classify the combination as supported, failed, or not addressable. Keep provisioning/tooling limitations separate from product failures.
5. Record adjacent declared combinations not exercised and limit conclusions to the observed combination.
6. Dispose of task-owned runtime state and preserve the replay command plus evidence reference.

## Output contract
- `declared_combination`, `actual_runner_provenance`, `clean_environment`, `import_result`, `entrypoint_result`, `classification`, `evidence_ref`, and `adjacent_limitations`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop without a support claim when runner provenance or the declared combination cannot be established.
