# Program/Migration Map: {{ destination }}

- Plan ID: {{ stable plan ID }}
- Profile: program
- Execution policy: {{ standard or autonomous_closure }}
- State ref: {{ plan-state JSON path }}
- State hash: {{ canonical sha256 }}
- Source revision: {{ revision or explicit-unversioned }}
- Scope hash: {{ sha256 }}
- Closure contract: {{ absent for standard; immutable artifact ref for autonomous_closure }}
- Contract hash / epoch: {{ absent for standard; sha256 / integer for autonomous_closure }}
- Goal/non-goals: {{ destination and exclusions }}
- Global invariants: {{ stable IDs and statements }}
- Decisions: {{ compact D-* pointers }}

## Constraint coverage

| Plan slice | Hard constraints | Corners | Verifier requirements |
|---|---|---|---|
| {{ P-* }} | {{ HC-* }} | {{ CORNER-* }} | {{ VR-* }} |

## Strategy families

| ID | Core mechanism | Why distinct | Disproof oracle | Status |
|---|---|---|---|---|
| {{ D-* or derived alternative ID }} | {{ mechanism }} | {{ distinction }} | {{ oracle/evidence ref }} | {{ selected/rejected/open }} |

## Current frontier

{{ only nodes that are ready now }}

## Blocked nodes

{{ node IDs and deterministic blockers }}

## Fog / not yet specified

{{ known future work that current evidence cannot safely detail }}

## Rollout and rollback

{{ staged rollout, approvals, stop conditions, rollback/removal conditions }}

## Verification and closure

{{ required evidence, false-green risks, residual uncertainty, and epistemic status }}

Do not expand remote milestones into implementation snapshots before they enter the frontier.
