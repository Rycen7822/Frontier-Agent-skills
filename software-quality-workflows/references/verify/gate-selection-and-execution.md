---
{
  "card_id": "sqw.verify.gate-selection-and-execution",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.verify.gate-selection-and-execution",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "verify-gate-selection-and-execution"
  ],
  "max_bytes": 8192
}
---
# Verification Gate Selection and Execution

## Decision this card owns
Select proportionate gates and execute them without losing command identity, original status, provenance, or failure visibility.

## Use when
- A bounded change or audit requires focused, affected, public, risk, or canonical proof not already fresh.

## Do not use when
- No applicable gate exists yet, or immutable records already cover the unchanged source/scope/environment.

## Required inputs
- `workflow-intake`; changed behavior/surface/callers; available repository/plan/CI/user gates; risks and baseline; exact working directory; source/scope/environment; expected distinctions; output/evidence policy.

## Procedure
1. Select valid RED when behavior changes, then the smallest focused gate proving the contract and only affected gates for real dependent seams.
2. Add public/installed/fresh-process proof for APIs, schemas, protocols, CLIs, UIs, packages, registration, generated clients, or installed copies.
3. Add risk-specific negative, rollback, and operational proof for security, data migration, release, or runtime changes. Preserve named canonical commands; do not invent full-suite requirements from generic process language.
4. Record inapplicable or infeasible gates with reason and remaining narrower evidence; bind every gate to source, scope, environment, expected distinction, applicability, and artifact type.
5. Execute the exact command/procedure. A necessary substitution is a different gate, never a silent equivalent.
6. Preserve original return code, stdout/stderr artifact, command, working directory, versions/environment, duration, source, and scope. Never pipe through a renderer whose status can replace the gate, add unconditional success, swallow exceptions, or infer pass from favorable text.
7. Capture complete evidence before bounded rendering. A renderer failure is separate and cannot change the gate result.
8. Emit one immutable `pass|fail|not_run` record per gate with failed IDs/actionable slice and full-log ref. Stop before classifying failure or claiming completion.

## Output contract
- One `verify-gate-selection-and-execution` with verification plan, applicability/not-run reasons, exact immutable gate records, original statuses/log refs, public/risk proof records, baseline refs, and execution limitations.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after faithful gate records exist; execution output alone does not prove a product defect or completion.
