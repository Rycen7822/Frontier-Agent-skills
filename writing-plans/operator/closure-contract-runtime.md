# Closure Contract Runtime

This is controller/runtime documentation, not a model-facing reference card. The editable field contract lives in `schemas/closure-contract.schema.json`; canonical hashing and semantic checks live in `_closure_contract.py`, `validate_closure_contract.py`, and `freeze_closure_contract.py`.

## Ownership boundary

- Writing Plans compiles, validates, freezes, persists, and supersedes intended Closure Contract epochs.
- SQW validates the typed handoff, qualifies/runs verifiers, owns candidates and actual evidence, computes execution phases, terminal verdicts, and publication decisions.
- A frozen contract never contains plan, candidate, workflow, runtime-result, or SQW internal-card references. The handoff binds plan and contract identities beside each other.

## Identity and publication

Freeze binds eligible Admission ref/hash, bundle ID, source revision, scope hash, policy bundle/card-manifest identity, authority manifest ref/hash/ceiling, contract ID/epoch, and the canonical self-excluding content hash. Publication is atomic, immutable, and no-overwrite. A material source, policy, authority, scope, intent, constraint, corner, verifier, or search-family change requires a new epoch; old epochs remain inspectable.

The freeze command must validate the authority manifest/hash itself. A stale identity, non-continuous soft-objective priority, unresolved material section, publication race, symlink/oversize/malformed input, or reverse runtime reference fails closed with a stable machine error.

## Compiler certificates and terminal vocabulary

Writing Plans may emit `SPEC_UNDERDETERMINED` or `SPEC_UNSAT` compiler certificates. These are intended-state artifacts, not actual workflow terminal events.

The shared frozen terminal vocabulary is exactly:

```text
CLOSED
SPEC_UNDERDETERMINED
SPEC_UNSAT
AUTHORITY_BLOCKED
ENVIRONMENT_UNAVAILABLE
BASELINE_UNSTABLE
VERIFIER_UNQUALIFIED
NON_CONVERGED
BUDGET_EXHAUSTED
WORKFLOW_INVALID
ABORTED_BY_SOURCE_DRIFT
```

The contract permits these values; only the SQW controller may commit an actual terminal status.

## Handoff boundary

`schemas/plan-execution-handoff.schema.json` is the single editable cross-skill contract. Autonomous handoffs bind non-null Admission and contract identities; standard handoffs keep those fields null. The envelope contains no SQW Markdown path or internal card ID. Bundle release identity exposes the schema contract ID/hash so consumers validate the same source without copying it.

After a valid handoff, WP card leases are cleared. SQW derives `BASELINING` and its own primary card from execution policy; Writing Plans never creates or advances SQW workflow state.
