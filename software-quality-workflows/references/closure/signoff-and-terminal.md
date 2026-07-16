---
{
  "card_id": "sqw.closure.signoff-and-terminal",
  "card_version": 1,
  "kind": "phase",
  "consumes": [
    "signoff_phase_projection",
    "incumbent_projection",
    "freshness_projection",
    "four_axis_evidence_projection",
    "publication_state_projection"
  ],
  "produces": [
    "signoff_and_terminal_proposal"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Sign-off and Terminal

## Decision this card owns
Assemble a fresh four-axis sign-off and propose the one truthful terminal certificate without executing publication or changing controller state.

## Use when
- Controller projects `SIGNING_OFF` with one promoted incumbent and complete required evaluation artifacts.

## Do not use when
- No incumbent is promoted, a required cascade remains incomplete, or any contract/verifier/baseline/candidate identity is stale.

## Required inputs
- Frozen contract/plan/policy/authority/source/scope/environment identities, verifier and baseline hashes, incumbent/evaluation/comparator refs, required gate evidence, independent requirements and engineering review results, verifier-integrity evidence, authority/side-effect evidence, residual risks, locks/background work, and separate publication state.

## Procedure
1. Revalidate all immutable identities, protected surfaces, required corners, candidate-test authority, required gates, and evidence freshness.
2. Require independent pass results for requirements/spec traceability, engineering quality, verifier integrity, and authority/side effects; workers and fixers cannot approve their own output.
3. Keep local technical closure distinct from publication readiness and execution. Push, comment, CI rerun, approval, merge, release, deploy, and publish require their own validated authority and action.
4. Confirm no unfinished node, active lock, pending background work, known blocker, stale proposal, or unreconciled artifact/worktree remains.
5. For `CLOSED`, bind promoted incumbent, sign-off, gate, residual-risk, publication-state, recovery-artifact, and freshness refs.
6. Otherwise select the fixed typed terminal status and include blockers, evidence, preserved artifacts, consumed budget/attempts where applicable, and a safe next action.
7. Propose exactly one immutable terminal certificate. Do not accept the terminal, alter phase, or rewrite a failed result.

## Output contract
- `signoff_and_terminal_proposal`: four axes and hashes, freshness, required gates, blockers/residual risks, publication state ref, terminal status, evidence bundle, preserved recovery artifacts, safe next action, and certificate hash.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop on any stale identity, incomplete axis, pending work/lock, missing publication-state record, or unresolved blocker; never infer `CLOSED` from tests alone.
