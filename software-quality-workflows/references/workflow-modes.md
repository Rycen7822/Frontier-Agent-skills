# Workflow Modes

This file is the normative detail owner for M0–M3 activation. The router chooses the lightest mode that preserves authority, proof, recovery, and auditability; mode never expands user authority.

## M0 Direct

- Entry: same-session, local/reversible, known intent and owner seam, focused proof available, no risk upgrade signal.
- State: no durable graph or `.workflow/` directory. A short session todo or scope/proof note is allowed.
- Execution: inspect owner, establish a meaningful distinction, make the smallest coherent change, inspect the diff, and run proportional proof.
- Close: report observed evidence, not-run or blocked gates, baseline issues, and residual risk.

M0 is a disciplined direct path, not an exemption from the safety kernel.

## M1 Trace

- Records only observed action summaries, artifact pointers, gate outcomes, and failure classifications.
- Does not predeclare nodes, alter reference loading, or change execution strategy.
- Stores no private chain-of-thought and no raw sensitive input/output.
- Counterfactual claims about M2 are labeled as inference, not observed benefit.
- Does not require durable graph state; a task-owned append-only trace may be retained only for an explicit evaluation window.

The local public surface is intentionally separate from M2/M3 initialization:

```bash
python scripts/local_workflow_adapter.py /absolute/task-root append-trace event.json \
  --trace-path trace/events.jsonl --expected-sequence 0
```

`--trace-path` must resolve inside the explicit task root. This command validates the event schema and compare-and-appends the trace; it creates no `.workflow/`, `state.json`, or `locks.json` graph state. Retention and cleanup remain part of the declared evaluation window.

## M2 Sparse

Use for costly or independently recoverable boundaries: delegated slices, public contracts, expensive gates, approval/external-state seams, dirty/concurrent work, or a durable handoff. Persist only nodes, locks, evidence, and events whose recovery value exceeds their maintenance cost.

## M3 Full

Use for multi-session migration, release, destructive recovery, shared mutable state, repeated real-runtime stability work, or strong audit/resume requirements. M3 adds complete transition, lock, invalidation, reconciliation, and closure contracts; it does not add product-design authority.

## Upgrade and downgrade

- Upgrade when authority, source, hidden/shared state, conflict, failure-locality, or proof assumptions invalidate the lighter mode.
- Downgrade after the risky boundary closes and retained state no longer adds recovery value.
- File count, token count, available workers, or subjective complexity alone are not upgrade signals.
- M2/M3 state is optional infrastructure, never a prerequisite for ordinary M0 work.

Use `scripts/route_workflow.py` for deterministic route fixtures. Stable reason codes explain every route; unknown high-risk facts choose a conservative bounded check rather than silently becoming `false`.
