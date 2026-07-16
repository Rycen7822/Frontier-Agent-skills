---
{
  "card_id": "sqw.verify.gate-execution-integrity",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "verification_plan",
    "source_identity",
    "scope_identity",
    "environment_identity"
  ],
  "produces": [
    "gate_run_records"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "gate-run-to-failure-classification",
      "to_card_id": "sqw.verify.failure-classification",
      "edge_mode": "hard",
      "hard_predicate_id": "required-gate-failed",
      "missing_decision": "A required gate failed and its cause class is unresolved",
      "required_evidence": "Original command, exit status, log slice, and environment identity",
      "evict_when": "Every failed gate has a typed cause classification"
    },
    {
      "edge_id": "gate-run-to-completion-evidence",
      "to_card_id": "sqw.verify.completion-evidence",
      "edge_mode": "hard",
      "hard_predicate_id": "required-gates-fresh-pass",
      "missing_decision": "All required gates passed and the completion record is not assembled",
      "required_evidence": "Fresh gate records bound to current source and scope",
      "evict_when": "Completion evidence record is emitted"
    }
  ]
}
---
# Gate Execution Integrity

## Decision this card owns
Execute selected gates without losing command identity, original status, evidence provenance, or failure visibility.

## Use when
- A verification plan names focused, affected, public-surface, risk, or canonical gates that must now run.

## Do not use when
- No gate is selected, or fresh immutable gate-run records already cover the current source/scope/environment identities.

## Required inputs
- Exact command or procedure, working directory, selected scope, expected distinction, relevant runtime/tool versions, output policy, and evidence location.

## Procedure
1. Execute the exact canonical command when one is named; record any necessary substitution as a different gate.
2. Preserve original return code, stdout/stderr artifact, command, working directory, version/environment, duration, source, and scope.
3. Never pipe a required command through a renderer whose status can replace the command status; never add unconditional success, swallow exceptions, or infer pass from favorable text.
4. Separate execution status from display: capture full evidence first, then render a bounded summary.
5. On success, report command, result, count, duration, and evidence ref. On failure, report original status, failed IDs, first actionable slice, and full-log ref.
6. If summary rendering fails, record a renderer failure without changing the gate result.
7. Emit one immutable record per gate and stop before interpreting failures or claiming completion.

## Output contract
- `gate_run_records[]`: gate ID, exact command/procedure, original status, source/scope/environment binding, duration, log/evidence refs, and `pass|fail|not_run`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `gate-run-to-failure-classification` | A required gate failed and its cause class is unresolved | Original command, exit status, log slice, and environment identity | `sqw.verify.failure-classification` | Every failed gate has a typed cause classification |
| `gate-run-to-completion-evidence` | All required gates passed and the completion record is not assembled | Fresh gate records bound to current source and scope | `sqw.verify.completion-evidence` | Completion evidence record is emitted |

## Stop
Stop after faithful gate records exist; execution output alone does not classify a product defect or authorize a completion claim.
