# Dependency and Lockfile Drift

## Purpose
Classify divergence among declared constraints, locked resolution, installed artifacts, and the supported runtime matrix before changing dependency state.

## Use when
- Dependency behavior, reproducibility, or CI/runtime disagreement may come from lockfile or installed-state drift.

## Do not use when
- No lock or reproducibility contract exists, or dependency regeneration/change lacks authority.

## Required inputs
- task context; direct constraints; lockfile and integrity metadata; installed package/runtime provenance; supported platform matrix; resolver/tool version; and change authority.

## Procedure
1. Compare direct constraints with the locked graph, then compare the locked graph with the actually installed/runtime graph and provenance.
2. Check source URLs, hashes, markers, optional groups, platform/runtime selectors, and resolver identity where they affect the supported matrix.
3. Classify each difference as intentional, stale direct resolution, transitive drift, platform-specific, integrity/provenance failure, or unauthorized/unknown.
4. Do not regenerate a lock merely because an unconstrained install is green. Establish intended constraints and regeneration authority first.
5. If change is authorized, regenerate with the declared tool/version in a clean environment, inspect the semantic diff, and reject unrelated churn.
6. Re-run the smallest affected supported-matrix proof and record unresolved or unaddressable combinations.

## Required result
- One `recipes-dependency-lockfile-drift` with constraint/lock/installed map, drift classification, provenance, matrix coverage, authorized action, semantic diff, and residual limitations.

## Stop
Stop before regeneration when intent, provenance, tool identity, or change authority is uncertain.
