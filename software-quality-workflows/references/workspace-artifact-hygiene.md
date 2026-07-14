# Workspace Artifact Hygiene

Use this reference when task-owned scratch, copied fixtures, generated outputs, worknotes, snapshots, archives, or staged candidates need clear ownership and safe organization.

Do not use it to simplify source code or recover lost repository content; use [cleanup](cleanup.md) or [repository recovery](repository-recovery.md) for those distinct outcomes. Resolve moves, deletion, staging, and other writes through the [authority and scope owner](authority-and-scope.md), and close out with [verification discipline](verification-discipline.md).

## Ownership classes

| Class | Handling |
|---|---|
| Active source/config | Keep under its repository owner; do not reorganize as an artifact. |
| Task-owned scratch | Keep under one task-specific temporary root; remove only when no durable evidence depends on it. |
| Active fixture/runner | Keep discoverable from current tests or docs and separate from historical output. |
| Generated/derived state | Regenerate from an owner when possible; never treat it as the only source of truth. |
| Evidence/provenance | Preserve immutably or with a relocation record; do not rewrite historical paths casually. |
| Unknown or third-party material | Leave unchanged until ownership and retention are established. |

## Workflow

1. Bound the workspace and inventory relevant entries with type, size, owner, producer, consumer, lifecycle, and repository status.
2. Classify active inputs separately from task scratch, generated state, evidence, and unknown material.
3. Choose one task-specific temporary root for new scratch and verification artifacts when writes are authorized.
4. Before moving anything, inspect active configuration, tests, scripts, docs, ignore rules, and references for path consumers.
5. Plan each move in a relocation map with old path, new path, owner, consumer updates, and rollback.
6. Move only authorized entries. Update active consumers; preserve historical evidence without rewriting embedded paths unless normalization is explicitly requested.
7. Verify paths, consumers, repository status, ignore behavior, and the cheapest relevant runner or syntax check.
8. Remove only task-owned scratch whose retention condition is satisfied, then verify the exact target is gone and unrelated entries remain.

## Copied fixtures and snapshots

- Copy only the material needed for the test; exclude large caches, build outputs, credentials, repository metadata, and unrelated history at collection time.
- Reject links that escape the fixture boundary unless the fixture contract explicitly requires and isolates them.
- Record provenance without embedding private machine paths in reader-facing files.
- Keep active fixtures separate from historical run artifacts so broad searches and test discovery do not consume both.
- Preserve old absolute paths in immutable historical evidence as provenance; update only active pointers.

## Staged-candidate hygiene

- Inspect staged paths directly; working-tree status alone does not prove what a snapshot will publish.
- Check nested copies against ignore rules at their new path. An ignore rule for the original location may not match the copied layout.
- Reject unintended scratch, cache, local export, secret, credential, private identifier, and generated-state candidates before any publication step.
- Use a bounded secret scan on the actual candidate set and inspect matches; do not normalize generated sensitive output into source.
- Do not broaden the staged set as part of hygiene. Report unrelated candidates instead.

## Prototype and experiment artifacts

A prototype is a task-owned experiment, not an early production implementation. Before creating it, record one decision question, a falsifiable learning criterion or oracle, the cheapest artifact that can answer it, its isolation boundary, owner, expiry condition, and disposition choices.

Classify mode by the requested outcome, not the word “prototype.” A disposable, task-owned probe created only to gather diagnostic evidence may remain `diagnose` with explicitly authorized `LOCAL_REVERSIBLE` writes. A retained source/config artifact, product-facing experiment, or shipped-path change is `change`. A report-only request creates neither. In every mode, the Authority owner decides the actual side-effect ceiling.

- Keep the prototype outside production state and shipped paths unless the user explicitly authorized a production-facing experiment with its own risk controls.
- Instrument only what is needed to answer the question; prototype success establishes that learning criterion, not production readiness, maintainability, security, or scale.
- At expiry, retain the decision and a compact evidence pointer. Remove task-owned throwaway code when no durable consumer depends on it, or deliberately reclassify a retained harness as an active fixture.
- Promotion means re-expressing the learned behavior contract through normal architecture review, planning, TDD, security and compatibility analysis, and layered verification. Do not lift prototype code into production merely because the experiment passed.
- Branch creation, publication, deployment, and external collaboration remain separate authority decisions; the experiment contract never grants them implicitly.

## Compact before deletion

Before deleting task-owned scratch, reports, copied artifacts, or temporary benchmark candidates, identify every durable conclusion and active consumer. Move only the compact conclusion, provenance pointer, accepted manifest delta, or reusable verifier into its canonical owner; re-read that destination and verify consumers resolve there before removal. Candidate/rejected benchmark material remains outside the canonical fixture until the test-pattern owner accepts it. Unknown, externally owned, or concurrently changed material stays in place.

## Cleanup boundary

Do not use elevated helpers, broad recursive cleanup, or workspace-wide refresh to resolve an ownership problem. Narrow the target, exclude it from future generation, and leave anything unknown in place. If a protected or externally owned artifact prevents completion, report the exact path class and required authority rather than expanding scope.

## Closeout checklist

- Every moved or removed item had a known owner and lifecycle.
- Active consumers resolve to the new paths.
- Historical evidence remains traceable.
- Copied fixtures cannot reach outside their declared boundary unexpectedly.
- Staged candidates contain only intentional source, fixtures, docs, and approved metadata.
- Temporary artifacts outside the chosen task root are accounted for.
