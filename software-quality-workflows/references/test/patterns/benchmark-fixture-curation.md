---
{
  "card_id": "sqw.test.patterns.benchmark-fixture-curation",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "benchmark_manifest_and_schema",
    "acceptance_oracle_and_target",
    "held_out_policy"
  ],
  "produces": [
    "benchmark_fixture_delta_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Benchmark Fixture Curation Pattern

## Decision this card owns
Add an exact accepted benchmark delta with representative strata, independent oracle quality, and held-out/parity evidence.

## Use when
- A benchmark/evaluation corpus needs an exact accepted count, broader coverage, or a new contract stratum.

## Do not use when
- The input is disposable diagnostic data or raw run output rather than a canonical accepted fixture.

## Required inputs
- Revision-bound manifest and schema, current accepted inventory, exact target/strata, acceptance oracle, duplicate/privacy/license/provenance rules, held-out/parity policy, and noise/threshold contract.

## Procedure
1. Inventory accepted cases from disk and define missing strata plus exact target before generating candidates.
2. Keep candidates/rejections outside canonical data and freeze oracle, benchmark warmup/noise/repeats, thresholds, and aligned failure corpus independently of the candidate.
3. Validate schema, provenance, privacy/license, duplicates, oracle quality, representative corners, and cohort balance.
4. Compare held-out/parity behavior and adjudicate uncertain cases; parse success is not acceptance.
5. Apply only the reviewed manifest delta, re-read canonical fixture, and count accepted cases from disk.
6. Compact durable selection evidence before scratch cleanup; roll back only the task-owned delta after confirming canonical revision has not drifted.

## Output contract
- Before/after manifest revision/hash, candidate/accepted/rejected delta, exact accepted count, strata/diversity, schema/provenance/privacy/license/dedup/oracle checks, held-out/parity outcome, adjudication, and rollback state.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after exact durable count and quality gates; never tune fixtures/thresholds against the candidate under evaluation.
