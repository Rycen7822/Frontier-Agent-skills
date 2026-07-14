# Cleanup

Use this reference only when the user asks to simplify, remove duplication, reduce unnecessary complexity, or clean up a bounded code change. Cleanup is an authorized subtractive change, not an automatic post-edit ritual.

Use the [authority and scope owner](authority-and-scope.md) to distinguish report-only review from change mode. Use [verification discipline](verification-discipline.md) to prove preserved behavior. Do not use cleanup to recover deleted files or reorganize task artifacts; use [repository recovery](repository-recovery.md) or [workspace artifact hygiene](workspace-artifact-hygiene.md).

## Preconditions

- Identify the exact changed paths, diff or contract in scope.
- Record the behavior, API, data shape, performance boundary, and side effects that must remain unchanged.
- Inspect existing owners, call sites, utilities, tests, and local conventions before proposing removal or reuse.
- Keep bug fixes, feature changes, migrations, and speculative optimizations outside this pass unless separately planned.
- In report-only mode, return evidence-backed candidates without editing.

## Three lenses

### Reuse

Look for new logic that duplicates an existing, compatible owner: parsing, path handling, validation, constants, state derivation, or domain helpers. Name the existing owner and prove semantic compatibility before replacing local code.

### Quality

Look for redundant state, parameter sprawl, copy-with-variation, leaky boundaries, stringly-typed contracts, dead branches, unnecessary adapters, and abstractions with only one unsupported future use.

### Efficiency

Look for repeated computation, duplicate I/O, unnecessary data loading, unbounded growth, leaked resources, avoidable hot-path work, and independent operations serialized without a correctness reason. Require evidence before changing concurrency or caching.

## Workflow

1. Build a candidate list with path, current behavior, duplication or complexity evidence, proposed subtraction, and proof.
2. Discard style-only churn, scope expansion, and suggestions without an owning replacement.
3. Order candidates by correctness risk and dependency. Start with the smallest independently provable removal.
4. Apply one coherent slice while preserving the public contract and unrelated user changes.
5. Run the focused proof that would fail if the cleanup changed behavior.
6. Reinspect the diff for accidental movement, renamed behavior, new wrappers, or dead compatibility paths.
7. Run the proportional closeout gate and report applied, rejected, and deferred candidates.

## Acceptance rules

Apply a cleanup candidate only when:

- the replacement already exists or the subtraction removes an unnecessary seam;
- consumers and lifecycle behavior remain understood;
- the patch is smaller or conceptually simpler without hiding complexity elsewhere;
- a focused proof observes the preserved contract;
- rollback is local and unrelated code remains untouched.

Do not replace clear code with a generic abstraction merely to reduce line count. Do not add a cache, mode, dependency, compatibility layer, or configuration option under the label of simplification.

## Stop conditions

Stop when the requested scope is simpler and verified, the next candidate changes behavior or architecture, evidence is insufficient, or further edits would be cosmetic churn. Cleanup does not authorize repository-wide modernization.

## Closeout checklist

- The final diff is bounded to the requested cleanup seam.
- Reuse claims point to a real compatible owner.
- Behavior and public contracts remain proven.
- No unrelated generated files, staged candidates, or workspace artifacts were changed.
- Rejected or deferred candidates include a concise reason.
