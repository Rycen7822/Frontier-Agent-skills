# Workflow State and Event Contract

This reference owns the semantics of M1 trace and M2/M3 workflow state. `schemas/workflow-state.schema.json` and `schemas/workflow-event.schema.json` own shapes/enums; scripts enforce deterministic checks but do not grant authority or decide product design.

## Activation and ownership

- M0 creates no durable workflow state.
- M1 may retain append-only observed trace events but cannot carry a predeclared execution graph.
- M2/M3 use strict UTF-8 JSON state and JSONL events.
- Plan state owns intended outcomes, invariants, decisions, coarse dependencies, and required proof.
- Workflow state owns actual runs, transitions, locks, attempts, outputs, evidence, failure, invalidation, and execution closure.
- Execution discoveries use `plan_change_proposed`; workers never rewrite canonical plan decisions or closure.

## Identity and limits

Namespaces are `wf-*`, `N-*`, `evt-*`, `RUN-*`, `EV-*`, `VER-*`, `I-*`, `AP-*`, `LOCK-*`, `X-*`, and `ERR-*`. Cross-artifact refs use `<kind>:<artifact>#<local-id>`; bare IDs are local only. Unknown fields, duplicate JSON keys, inputs over 2 MiB, nesting over 40, and collections over 1,000 items (2,000 edges) fail closed. Canonical hashes use sorted compact JSON with `state_hash` omitted.

## Transitions

Workflow status is `open | active | blocked | closing | closed | aborted`.

Node status is `pending | ready | running | blocked | done | failed | invalidated | superseded | skipped | cancelled`.

Core transitions:

- `pending -> ready` after dependencies, authority, freshness, approval, retry, and lock gates pass;
- `ready -> running` only with current state version and required resource ownership;
- `running -> done` only after output/evidence and required verifiers are atomically accepted;
- `running -> failed|blocked` with structured failure or blocker evidence;
- `done -> invalidated` when a sensitive dependency changes;
- `failed|blocked|invalidated -> ready` only after bounded repair/retry approval;
- unfinished nodes may become `superseded` with retained lineage;
- `active -> closing -> closed` only when closure evidence, background work, and locks reconcile.

Every accepted state transition increments `state_version` by exactly one. Workflow ID, request mode, and mode are immutable. Scope or authority cannot silently expand.

## Evidence, approval, retry, and locks

Evidence records a versioned `schema_id`, claim, producer/run, source revision/scope hash, original exit code, duration, classification, coverage, freshness, limitations, content hash, and controlled artifact pointer. Node input/output contracts must match observed artifact schemas before readiness or completion. Verifier `evidence_sensitivity` declares which evidence fields can invalidate its claim. `baseline_failure` is distinct from `product_failure` and cannot satisfy a product-regression verifier.

External or destructive nodes require a granted scoped approval and an authority ceiling covering the effect. Non-idempotent retries require an idempotency key or manual reconciliation. Locks contain resource, owner, acquisition/lease times, and state version; two live owners cannot hold the same resource.

## Event authority

Events are append-only, schema-valid, unique, contiguous, ordered, and bound to one workflow. Workers may submit reference-load, output, failure, artifact-observation, and plan-change-proposal events. Reviewers may submit review/artifact observations. Only controller/system actors accept canonical node completion, approval, lock, invalidation, retry, resume, and closure transitions.

No event stores private reasoning or raw credentials. Sensitive content is represented by classification, hash, and a controlled pointer.

## Closure

Closure requires all named verifiers passed with fresh evidence, no unfinished nodes, pending background work, active locks, or known blocking gaps, and current source/scope/plan hashes. Use both closure status and scoped epistemic status. Schema validity is not semantic correctness, and local closure does not imply merge, deploy, publish, or human approval readiness.

Hermes live todos remain ephemeral projections. Reconciliation may compare a supplied node-status mapping and report missing, orphaned, or drifted todo rows, but todo never overrides canonical workflow state and is regenerated after resume.

## Stable validator codes

State codes: `workflow.schema`, `workflow.id-duplicate`, `workflow.owner-unknown`, `workflow.plan-ref-mismatch`, `workflow.ref-missing`, `workflow.control-cycle`, `workflow.frontier-stale`, `workflow.io-schema-mismatch`, `workflow.scope-write`, `workflow.authority-exceeded`, `workflow.approval-missing`, `workflow.retry-unsafe`, `workflow.done-without-evidence`, `workflow.lock-conflict`, `workflow.sensitive-unclassified`, `workflow.m1-graph`, `workflow.state-hash`, `workflow.source-stale`, `workflow.plan-stale`, and `workflow.closure-premature`.

Transition/event codes: `workflow.identity-change`, `workflow.state-version`, `workflow.status-transition`, `workflow.node-deleted`, `workflow.authority-expanded`, `workflow.event-schema`, `workflow.event-duplicate`, `workflow.event-workflow`, `workflow.event-order`, `workflow.event-version`, `workflow.actor-forbidden`, and `workflow.event-shape`.

Use `scripts/validate_workflow_state.py` for state, event-stream, transition, freshness, approval, retry, and closure checks.
