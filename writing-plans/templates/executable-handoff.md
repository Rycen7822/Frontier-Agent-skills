# Executable Handoff: {{ goal }}

- Plan ID: {{ stable plan ID }}
- Profile: handoff
- Execution policy: standard
- Source revision: {{ revision or explicit-unversioned }}
- Scope hash: {{ sha256 }}
- Goal: {{ observable destination }}
- Non-goals: {{ excluded outcomes }}
- Global invariants: {{ stable IDs and statements }}
- Owner seams/contracts: {{ symbols, schemas, or interfaces }}
- Requirement anchors: {{ authoritative user/repository/source refs }}
- Required owner refs: {{ reachable reference paths only }}

## Ordered outcome slices

For each slice record: ID, outcome, dependencies, contract, read-first pointers, allowed writes, verifier, false-green risk, evidence, side effect, and unresolved fog.

## Current frontier

{{ ready slice IDs and why }}

## Gaps/fog

{{ unresolved facts that must not be invented }}

## Handoff envelope

{{ state ref/hash, source/scope hash, current frontier, required evidence, blockers, and fog }}
