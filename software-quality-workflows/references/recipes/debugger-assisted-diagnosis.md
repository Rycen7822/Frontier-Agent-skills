---
{
  "card_id": "sqw.recipes.debugger-assisted-diagnosis",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "reproduction_record",
    "active_hypothesis",
    "safe_process_ownership"
  ],
  "produces": [
    "debugger_discrimination_observation"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Debugger-Assisted Diagnosis

## Decision this card owns
Capture one task-owned debugger observation that directly discriminates the active hypothesis from a named alternative.

## Use when
- A reproducible failure and falsifiable hypothesis identify debugger state as the cheapest direct discriminator.

## Do not use when
- Process ownership, safe isolation, source identity, or a predicted discriminating observation is missing.

## Required inputs
- Reproduction command, active and alternative hypotheses, predicted breakpoint/watchpoint observation, source revision, process ownership, classification/redaction rules, and time/attempt budget.

## Procedure
1. Prefer a controlled task-owned launch; never attach to an unowned or production process by convenience.
2. Bind breakpoints and watchpoints to the current source revision and predicted causal boundary.
3. Capture only the minimal values needed to distinguish hypotheses; redact sensitive values and retain no credentials.
4. Record command, process identity class, observation, source identity, and whether the prediction was supported, weakened, or remained inconclusive.
5. Convert the observation into replayable evidence or an explicit limitation, then detach and clean up task-owned resources.

## Output contract
- `prediction`, `observation`, `hypotheses_distinguished`, `source_identity`, `evidence_ref`, `classification`, `cleanup_status`, and `limitation|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop without attaching when safe ownership or isolation is uncertain; continue with logs, traces, local reproduction, or another non-invasive discriminator.
