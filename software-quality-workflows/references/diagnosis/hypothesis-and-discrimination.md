---
{
  "card_id": "sqw.diagnosis.hypothesis-and-discrimination",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "reproduction_record",
    "failure_boundary",
    "source_identity",
    "probe_authority"
  ],
  "produces": [
    "hypothesis_table",
    "supported_cause_or_inconclusive"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 8192,
  "neighbors": [
    {
      "edge_id": "hypothesis-to-debugger",
      "to_card_id": "sqw.recipes.debugger-assisted-diagnosis",
      "edge_mode": "semantic",
      "missing_decision": "A task-owned debugger observation is the cheapest direct discriminator between current competing hypotheses",
      "required_evidence": "Fresh reproduction, bounded failure surface, ranked hypothesis table, and safe process ownership",
      "evict_when": "The discriminating debugger observation or explicit limitation is recorded"
    }
  ]
}
---
# Hypothesis and Discrimination

## Decision this card owns
Select and test discriminating causal hypotheses until one cause is supported or the bounded evidence remains inconclusive.

## Use when
- A fresh reproduction record and bounded failure surface exist, but the root cause is not yet supported.

## Do not use when
- The symptom has not reached the target behavior, the reproduction is stale, or a supported-cause artifact already exists.

## Required inputs
- Exact reproduction and control, boundary observations, source/environment identity, working-path evidence when available, probe authority, and experiment budget.

## Procedure
1. List a small ranked portfolio of materially distinct causes, ordered by discriminatory value and experiment cost.
2. For each cause record the affected boundary, supporting evidence, disproof observation, remaining unknowns, and confidence limit.
3. Select exactly one active hypothesis and one controlled variable. Predict the observation before running the experiment.
4. Prefer the cheapest safe observation that distinguishes the active hypothesis from plausible alternatives; an experimental patch is evidence, not the repair.
5. Load the debugger recipe only when a task-owned debugger observation directly separates the current competing hypotheses.
6. Preserve the original reproduction as control and bind every observation to source, environment, and trial identity.
7. When an experiment fails, retain its evidence, revert only task-owned experimental changes, state why the hypothesis weakened, and return to the earliest unsupported boundary.
8. Reassess ownership or request global replanning when evidence exposes shared/hidden state, moves the symptom across components, or shows the proposed seam cannot express the contract.
9. Emit a supported cause only when the predicted causal boundary is observed and alternatives are materially weakened; otherwise emit typed `INCONCLUSIVE` with the minimal missing discriminator.

## Output contract
- `hypothesis_table`, `active_hypothesis`, `experiments`, `controlled_variables`, `supported_cause|null`, `confidence_boundary`, `weakened_alternatives`, `evidence_refs`, `next_edge_id|null`, and `blocker|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `hypothesis-to-debugger` | A task-owned debugger observation is the cheapest direct discriminator between current competing hypotheses | Fresh reproduction, bounded failure surface, ranked hypothesis table, and safe process ownership | `sqw.recipes.debugger-assisted-diagnosis` | The discriminating debugger observation or explicit limitation is recorded |

## Stop
Stop at the supported-cause or `INCONCLUSIVE` artifact boundary. Router, not this card, selects bugfix transition.
