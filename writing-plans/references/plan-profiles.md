# Plan Profiles

This reference owns the output shape for Brief Change Card, Executable Handoff, Program/Migration Map, and the optional novice projection. Load it only after `SKILL.md` selects a plan profile and Execution policy.

## Brief Change Card

```markdown
# Change Card: <observable outcome>

- Outcome: <behavior or state change>
- Scope: <owner seam or symbols; paths only when useful>
- Invariants: <what must remain true>
- Approach: <smallest coherent change>
- Proof: <focused distinction and proportional affected gate>
- Risks/open facts: <material gaps only>
```

Brief uses `standard` Execution policy, creates no graph or Closure Contract, does not repeat source code, and assumes no VCS operation. Constraint coverage stays inline with the outcome, invariants, proof, and risks.

## Executable Handoff

Executable Handoff uses `standard` Execution policy. Include goal/non-goals; source and scope identity when freshness matters; global invariants and owner seams; requirement anchors and Constraint coverage; ordered outcome slices and dependencies; allowed writes and side-effect ceiling; verifier, expected distinction, false-green risk, and evidence per slice; current frontier, blocked facts, rollback, and fog.

## Program/Migration Map

Add coarse milestones plus a detailed current frontier; public compatibility and expand-migrate-contract order; rollout, approval, resource, retry/idempotency, and rollback boundaries; typed plan-state path/hash and lineage; invalidated/superseded nodes; and future fog intentionally left coarse. Program may use `standard` or `autonomous_closure` Execution policy. The closure form must bind the frozen `closure_contract_ref`, give explicit Constraint coverage, and keep actual execution state in SQW.

## Canonical slice

```markdown
### P-03: <observable result>

- Outcome: <one independently judgeable state change>
- Depends on: <stable IDs or none>
- Contract/invariants: <what must hold>
- Read first: <symbols, schemas, tests, or source-bound paths>
- Allowed writes: <owner seam or bounded paths>
- Proof: <oracle and before/after distinction>
- False-green risk: <how the proof could pass incorrectly>
- Side effect / rollback: <boundary when material>
- Evidence produced: <stable evidence IDs or artifact refs>
- Fog/non-goal: <what this slice must not decide>
```

## Optional novice projection

Exact code, line numbers, copied error text, and command output are render-time details, not canonical plan state. Include them only when they encode a stable public contract, a validated prototype, or an explicitly requested low-context/copy-paste handoff. Bind the projection to a source revision and content hash; regenerate it when freshness changes.

Commit, branch, push, PR, deploy, and publication behavior follows explicit user authority and repository/host policy. A plan may mark safe save points but never assumes VCS or external-write authority.
