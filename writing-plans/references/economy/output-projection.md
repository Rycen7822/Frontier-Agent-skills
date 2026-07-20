---
{
  "card_id": "wp.economy.output-projection",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "wp.select.economy.output-projection",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "output-projection"
  ],
  "max_bytes": 8192
}
---
# Output Projection and Verification

## Decision this card owns
Classify agent-facing output by downstream action value and define compact, full, persisted, and resume projections that are measurably smaller without hiding mandatory evidence.

## Use when
- Context replay or output economy is an explicit planning outcome and representative current envelopes can be measured.

## Do not use when
- Ordinary planning only needs a current-node capsule, the quality-critical consumer is unknown, or no representative baseline exists.

## Required inputs
- Reproducible baseline source/command/time or artifact identity, representative outputs/context packs, downstream consumers/actions, protected fields, behavior/golden evidence, storage/retrieval capabilities, compatibility and sensitive-data rules, and actual size/token evidence when available.

## Procedure

### 1. Classify fields and consumers
1. Measure the representative high-level agent envelope; never estimate from memory or add a tokenizer dependency merely for a product check.
2. Classify each field as always-visible anchor, compact evidence, debug/full evidence, or persisted state.
3. Protect goal, constraints, phase/checkpoint, validation, next action, blockers, risks/warnings, authority/budget, source/artifact refs, coverage gaps, and required actions.
4. Move raw traces, full provenance/candidate lists, logs, scoring details, and bulky diagnostics out of the default only when an explicit retrieval path exists.
5. Define only output classes used by real consumers. Tiny budgets are smoke tests, never universal defaults.

### 2. Define projection, persistence, and resume
1. Specify compact/default, full/debug, and machine-export fields plus exact protected anchors.
2. Store bulky state in bounded artifacts, digests, checkpoints, indexes, or versioned documents with resolvable ID/path/hash/size and explicit on-demand reads.
3. Define resume state: current checkpoint/delta, artifact index, validation state, next action, blockers, and freshness/invalidation binding.
4. Set budgets from measured envelopes and protected-anchor cost. Mandatory fields fail closed rather than truncate; optional omissions list stable IDs and pointers.
5. For Writing Plans Program, render only through `card_cycle.py` to fixed `projections/program.md`: validate the complete candidate and total 8,192-byte envelope in memory, commit state once, then publish. The state stores no projection locator or hash, and exact replay repairs state-after/output-before-return loss.

### 3. Prove parity and rollout
1. Compare old/new counts, keys, ordering/ranking, warnings, required actions, coverage, and every quality-critical field. Tests needing full evidence request debug mode explicitly.
2. Measure the actual user/agent envelope, document any justified size regression, and do not claim soak, stability, or savings beyond observed scope.
3. Keep representative behavior, compatibility, and size gates; define rollout/rollback and remove stale literals or copied plans that could masquerade as current truth.

## Output contract
- One `output-projection` containing baseline identity/size, field classes, protected anchors, consumer profiles, storage/lazy-load/resume/freshness contracts, parity/size gates, measured target, rollout/rollback, limitations, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when compact output is measurably smaller or explicitly justified, fully actionable, and parity-verifiable without hidden mandatory omissions.
