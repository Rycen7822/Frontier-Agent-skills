# Implementation Slicing and Context Capsules

Use this reference when a Handoff or Program plan needs outcome-sized slices, explicit dependencies, parallel-safety reasoning, or a bounded context projection. File count alone is not a trigger.

A slice is valid when it produces one observable, independently judgeable result with clear prerequisites, allowed writes, side effects, and a verifier. If its required context cannot fit in one capsule or failure cannot be localized, split or redesign it. This reference defines planning semantics; SQW owns execution and run-state transitions.

## Slice selection

| Slice type | Use when | Shape |
|---|---|---|
| Vertical slice | A user-visible path crosses UI/API/storage or multiple layers. | Build one end-to-end behavior with tests before expanding. |
| Contract-first slice | Backend/frontend, producer/consumer, plugin/host, or CLI/parser can be developed independently. | Define schema/types/examples first, then implement each side against it. |
| Risk-first slice | The feasibility or correctness risk is concentrated in one unknown. | Prove the risky seam first with a narrow spike or test, then build around it. |
| Cleanup-first slice | Existing design must be simplified or deleted before feature work is safe. | Remove, merge, or rewrite the owning seam, then add only the needed behavior. |
| Compatibility slice | Existing consumers must keep working during migration. | Expand → migrate → prove usage → contract the old path. |
| Verification-only slice | A reliable oracle, fixture, installed-surface proof, or benchmark is missing. | Establish evidence without mixing in the product change it will later judge. |

For autonomous closure, label each slice with its closure phase and frozen contract constraint/corner/verifier references. Strategy-family exploration belongs to SQW candidate state; a candidate is never promoted into a canonical plan node. Only an intended owner/result/dependency change may create or revise a plan node, with a new contract epoch when contract semantics changed.

## Context capsule

A Handoff/Program capsule is a generated projection of canonical plan state, not a hand-maintained second truth. It includes only:

- goal, global invariants, and the current slice objective/completion criterion;
- source revision, scope hash, and required fresh inputs/evidence;
- owner seam plus files/symbols to read first;
- allowed reads/writes, protected resources, side-effect ceiling, and approval boundary;
- dependency outputs summarized by stable ID;
- verifier, expected distinction, and false-green risk;
- explicit non-goals and fog.
- for `autonomous_closure`, contract ID/hash/epoch, node constraint/corner/verifier-requirement refs, authority/protected boundaries, false-green risks, and blocking gaps;
- when supplied by SQW, only bounded incumbent, hard-failure, and budget projections.

Do not include the complete plan, full contract, candidate history, raw logs, long transcripts, broad source dumps, unrelated decisions, future nodes, or sensitive payloads. If the projection exceeds budget, report omitted IDs and on-demand pointers rather than silently truncating required authority, invariants, objective, or proof.

## Source loading guidance

A slice identifies the owner and nearest proof seams; the executor still inspects current source before editing. Exact paths, lines, snippets, versions, and command outputs are freshness-sensitive and carry a source revision or artifact hash when retained.

## Plan refresh after execution

SQW owns slice execution and records actual commands, artifacts, failures, and evidence. Writing-plan state may receive only status/evidence projections, discovered facts, invalidation/supersession, newly visible fog/frontier, plan-change proposals, and closure evidence. If source, scope, or a decision changes, regenerate affected capsules and keep unrelated fresh slices intact.

## Pitfalls

- Horizontal slices such as “build all models, then all APIs, then all UI” delay real integration evidence.
- Context capsules that include everything make agents ignore the critical anchors.
- A “temporary” abstraction added for parallelism must have a deletion row or it becomes permanent debt.
