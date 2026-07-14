# Change Execution

> Owner: change-execution
> Authority: normative_owner
> Role: lifecycle
> Phases: DIRECT, PLANNING, SEARCHING, SIGNING_OFF
> Requires: test-driven-development, verification-discipline
> May load: delegated-development, evidence-delegation
> Does not own: autonomous closure phases, candidate promotion, sign-off verdicts

## Activation and exclusions

Use for an authorized change with a defined outcome and known owner seam. It owns M0 Direct and execution of the current frontier for standard M2/M3 plans. In autonomous closure it is only the candidate worker's implementation subprotocol. Unknown root cause, materially underdefined intent, read-only work, recovery, candidate selection, and terminal certification remain with their owning lifecycle.

## Inspect owner seam

Read the current implementation, nearest contracts, affected tests, and repository instructions. Record source revision, allowed writes, protected paths, dirty/concurrent work, side-effect ceiling, and the smallest coherent owner seam before editing.

## Establish behavioral distinction

Name the observable before/after distinction and the best available oracle. For a bugfix, first preserve a failing reproduction that fails for the intended reason. Candidate-added tests remain supplementary until `verifier-kernel` independently promotes them.

## Make smallest coherent change

Modify the owning seam rather than layering a parallel implementation. Preserve unrelated work and hard constraints. A candidate worker writes only its isolated worktree and never the incumbent, contract, verifier bundle, policy, protected tests, or controller artifacts.

## Verify focused and affected behavior

Run the cheapest discriminating gate first, then the affected owner/public/runtime/security gates triggered by the change. Preserve original exit status and classify baseline, product, harness, environment, and permission failures separately under `verification-discipline`.

## Inspect diff and protected surfaces

Inspect the actual diff, generated artifacts, write scope, dependency/lockfile movement, temporary files, and protected surfaces. Unexpected surface growth or kernel change invalidates local completion and returns control to the controller or plan owner.

## Review escalation

Use R0 self-diff inspection for routine Direct work, R1 for non-trivial/cross-owner changes, and R2 for public, security, release, or high-risk work. `requesting-code-review` owns reviewer independence, companion loading, and the review result.

## Plan escalation

Escalate to `writing-plans` when resume, migration, durable handoff, multi-owner dependencies, or recovery evidence cannot fit a Direct change card. Execution discoveries become source-bound plan-change proposals; a worker does not rewrite the canonical plan or frozen contract.

## Completion

Direct completion requires scoped diff inspection, focused distinction, proportional affected proof, and explicit not-run/baseline/blocked/residual-risk reporting. Planned/candidate completion emits bounded evidence and a proposal to its controller. This owner never promotes a candidate, closes autonomous workflow state, or publishes.
