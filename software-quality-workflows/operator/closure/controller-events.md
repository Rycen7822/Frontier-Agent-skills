# Controller State and Event Runtime

This operator contract owns durable M1 trace and M2/M3 workflow transition semantics. It is controller input, never a model-navigation card. JSON shapes and enums remain canonical in `schemas/workflow-state.schema.json` and `schemas/workflow-event.schema.json`; scripts validate them without granting authority or making product-design decisions.

## Activation and ownership

- M0 creates no durable workflow state.
- M1 may retain append-only observed trace events but cannot carry a predeclared execution graph.
- M2/M3 use strict UTF-8 JSON state and JSONL events.
- Plan state owns intended outcomes, invariants, decisions, coarse dependencies, and required proof.
- Workflow state owns actual runs, transitions, locks, attempts, outputs, evidence, failure, invalidation, and execution closure.
- Execution discoveries emit `plan_change_proposed`; workers never rewrite canonical plan decisions or closure contracts.

## Transition contract

Workflow status is `open | active | blocked | closing | closed | aborted`. Node status is `pending | ready | running | blocked | done | failed | invalidated | superseded | skipped | cancelled`.

- `pending -> ready` only after dependencies, authority, freshness, approval, retry, and lock gates pass.
- `ready -> running` requires the current state version and required resource ownership.
- `running -> done` requires atomic acceptance of output/evidence and required verifiers.
- `running -> failed|blocked` records structured failure or blocker evidence.
- `done -> invalidated` follows a sensitive dependency change.
- `failed|blocked|invalidated -> ready` requires bounded repair and retry approval.
- Unfinished nodes may become `superseded` with retained lineage.
- `active -> closing -> closed` requires reconciled closure evidence, background work, and locks.

Every accepted transition increments `state_version` exactly once. Workflow ID, request mode, and mode are immutable. Scope and authority cannot silently expand.

## Event authority

Events are append-only, schema-valid, unique, contiguous, ordered, and bound to one workflow. Workers may submit reference-load, output, failure, artifact-observation, and plan-change-proposal events. Reviewers may submit review and artifact observations. Only controller/system actors accept canonical node completion, approval, lock, invalidation, retry, resume, and closure transitions.

No event stores private reasoning or raw credentials. Sensitive content is represented by classification, hash, and controlled pointer.

## Closure semantics

Closure requires every named verifier to pass with fresh evidence; no unfinished node, pending background work, active lock, or known blocking gap; and current source, scope, plan, contract, and policy identities. Record both closure status and scoped epistemic status. Schema validity is not semantic correctness. Local closure never implies merge, deploy, publication, approval, or release readiness.

## Stable validator codes

State codes: `workflow.schema`, `workflow.id-duplicate`, `workflow.owner-unknown`, `workflow.plan-ref-mismatch`, `workflow.ref-missing`, `workflow.control-cycle`, `workflow.frontier-stale`, `workflow.io-schema-mismatch`, `workflow.scope-write`, `workflow.authority-exceeded`, `workflow.approval-missing`, `workflow.retry-unsafe`, `workflow.done-without-evidence`, `workflow.lock-conflict`, `workflow.sensitive-unclassified`, `workflow.m1-graph`, `workflow.state-hash`, `workflow.source-stale`, `workflow.plan-stale`, and `workflow.closure-premature`.

Transition/event codes: `workflow.identity-change`, `workflow.state-version`, `workflow.status-transition`, `workflow.node-deleted`, `workflow.authority-expanded`, `workflow.event-schema`, `workflow.event-duplicate`, `workflow.event-workflow`, `workflow.event-order`, `workflow.event-version`, `workflow.actor-forbidden`, and `workflow.event-shape`.

Use `scripts/validate_workflow_state.py` for state, event-stream, transition, freshness, approval, retry, and closure checks. Host-native todos are disposable projections and never override this controller truth.
