# Merge Conflict Resolution

Use this reference to resolve conflicts in an already-started merge, rebase, cherry-pick, or revert. It owns conflict-state interpretation, intent reconstruction, resolution, and conflict-specific proof. It does not authorize starting, continuing, committing, aborting, or publishing a version-control operation.

Resolve mode, risk, scope, dirty-worktree ownership, and side effects through [Authority and Scope](authority-and-scope.md). Use [Verification Discipline](verification-discipline.md) for evidence gates and completion claims, [API and Interface Design](api-interface-design.md) when a conflict changes an external contract, and [Repository Recovery](repository-recovery.md) if content was accidentally lost or overwritten.

## Contents

- [Freeze the operation](#freeze-the-operation)
- [Interpret the three sides](#interpret-the-three-sides)
- [Recover intent](#recover-intent)
- [Classify each conflict](#classify-each-conflict)
- [Resolve authoritative sources first](#resolve-authoritative-sources-first)
- [Stage narrowly](#stage-narrowly)
- [Verify the integrated result](#verify-the-integrated-result)
- [Pause, abort, continue, or commit](#pause-abort-continue-or-commit)

## Freeze the operation

Before editing, capture a read-only conflict manifest:

```text
operation: merge | rebase | cherry-pick | revert
current_head: revision and branch or detached state
operation_source: merge head, upstream/new base, picked commit, or reverted commit
sequencer_step: current and remaining step when applicable
preexisting_index: paths already staged before this resolution pass
conflict_paths: exact unmerged paths and index stages
allowed_resolution_paths: explicit subset authorized for edits and staging
```

- Read the repository's actual operation state; do not infer it from a branch name or command history alone.
- Freeze the current conflict-path allowlist for this step. Do not switch branches, start another integration operation, clean, reset, restore, or stash to make the state look simpler.
- Preserve unrelated tracked, untracked, ignored, generated, and pre-staged work. A conflict does not make the rest of the worktree task-owned.
- If a later sequencer step exposes new conflicts, stop and create a new manifest and allowlist before editing them.

## Interpret the three sides

Read the unmerged index when available: stage 1 is the merge base, stage 2 is `ours`, and stage 3 is `theirs`. A side may be absent for add/delete or other tree-shape conflicts.

Map those labels to the active operation before choosing content:

| Operation | `ours` / stage 2 | `theirs` / stage 3 |
|---|---|---|
| Merge | The currently checked-out `HEAD` | The merged-in head |
| Rebase | The result already rebuilt on the upstream or new base | The branch commit currently being replayed |
| Cherry-pick | The current `HEAD` | The incoming side of the picked commit |
| Revert | The current `HEAD` | The sequencer's incoming reverse-change side, normally derived from the selected commit's parent |

During rebase, `ours` and `theirs` therefore feel reversed relative to the original topic branch: the rebased upstream result is `ours`, while the topic commit being replayed is `theirs`. Never resolve a rebase conflict by treating the labels as synonyms for “my branch” and “their branch.” For cherry-pick and revert, confirm the source commit, parent, and sequencer metadata rather than guessing from the labels.

## Recover intent

For every allowed conflict path:

1. Read the base, ours, and theirs versions that exist, plus the complete conflict hunk and owning context.
2. Read the commits and diffs that introduced each side. Use commit messages as evidence, not as the sole specification.
3. Locate the closest authoritative specification, accepted plan, test, schema, ADR, migration note, or documented invariant.
4. Trace affected callers, consumers, data flow, error behavior, and adjacent tests to determine what each side must preserve.
5. Record each side's behavior-level intent and constraints before selecting a resolution.
6. Prefer a resolution that preserves both compatible intents. Do not choose a side merely because it is newer, more extensive, or labeled `ours`.

If no authoritative source distinguishes incompatible behaviors, do not invent a third behavior or silently choose one. Mark the path `intent_inconclusive` and pause for direction.

## Classify each conflict

Classify semantics and tree shape separately when both apply.

| Class | Resolution question |
|---|---|
| `independent` | Do the changes affect separate declarations, sections, or behaviors that can both be retained without interaction? |
| `composable` | Can overlapping edits be integrated while preserving both sets of invariants and ordering requirements? |
| `semantic_incompatible` | Do the sides require mutually exclusive contracts, algorithms, defaults, or state transitions? |
| `rename_delete` | Was deletion intentional, was the rename authoritative, and which current path owns the surviving behavior? |
| `add_add` | Are the additions two implementations of one identity, or distinct artifacts that need explicit names and references? |
| `generated` | Which authoritative source and canonical generator own this file? |
| `lockfile` | Which reconciled manifest, package manager, version, and canonical lock procedure own dependency resolution? |

Do not reduce rename/delete or add/add conflicts to line selection. Reconstruct path identity, references, build inclusion, and deletion intent. Treat a semantic incompatibility as a design decision, not a text-editing problem.

## Resolve authoritative sources first

- Merge source code, manifests, schemas, templates, or other authoritative inputs before derived artifacts.
- Regenerate generated files with the repository's canonical generator and compatible tool version. Do not hand-splice generated output when deterministic regeneration is available.
- Reconcile dependency manifests before lockfiles, then regenerate the lockfile with the repository's declared package manager and lock procedure. Do not select arbitrary dependency versions just to eliminate textual conflict.
- Confirm that a generator or package manager will write only authorized paths. If it requires additional changes, expand scope through the authority owner or pause.
- If the canonical generator, toolchain, or dependency source is unavailable, preserve the unresolved status and report the evidence gap; a plausible hand edit is not equivalent proof.
- For public contracts, apply the compatibility and migration requirements in [API and Interface Design](api-interface-design.md). Do not use conflict resolution to smuggle in a breaking change.

## Stage narrowly

1. Edit only `allowed_resolution_paths` and inspect each resolved diff against the recovered intents.
2. Stage explicit allowlisted paths, including explicit removals or rename targets. Never use repository-wide, all-path, or current-directory staging pathspecs.
3. Re-read the staged path list and compare it with the frozen allowlist and preexisting index. Preserve unrelated pre-staged content without claiming it as this resolution.
4. Verify that no generator, formatter, merge tool, or hook changed an unlisted path. Treat any such drift as a scope event, not as incidental cleanup.

Staging marks a path resolved in the index; it does not prove semantic correctness and does not authorize the operation's next state transition.

## Verify the integrated result

Apply the evidence levels from [Verification Discipline](verification-discipline.md), then add conflict-specific proof:

- Confirm that the unmerged index and conflict-path query are empty for the current allowlist. Inspect possible conflict-marker matches contextually; marker absence alone is insufficient.
- Inspect the staged result as one integrated change, not only the formerly conflicted lines. Compare it with the base and both recovered intents.
- Run the smallest focused test or procedure for every reconciled behavior, then affected-area checks for coupled callers, schemas, generated artifacts, and dependency resolution.
- Exercise the public API, CLI, protocol, file format, or runtime path when the conflict touches one; private compilation alone does not prove the consumer contract.
- Run the repository's canonical semantic gate when required by project rules or blast radius. A clean index shape, successful parse, or marker scan is not semantic proof.
- Record unresolved paths, skipped gates, baseline failures, and evidence gaps separately. Return `inconclusive` when the intended integrated behavior cannot be proved.

After an authorized sequencer continuation, repeat the state capture and conflict checks for each newly exposed step. Do not generalize proof from one replayed commit to the remaining sequence.

## Pause, abort, continue, or commit

Pause with the operation intact when intent is ambiguous, compatible behavior cannot be preserved, scope expands beyond the allowlist, an authoritative generator is unavailable, concurrent work cannot be separated, or the next action exceeds current authority.

Abort is a legitimate option when the integration goal is wrong, intent remains irreducibly ambiguous, scope is uncontrolled, or safe completion lacks authority. Before aborting, inspect whether it would overwrite unrelated or newly created work and preserve task-owned evidence as authorized. Do not treat abort as failure, and do not run it blindly as cleanup.

Run `--continue`, create a merge commit, or make any other commit only when the user's request or an already authorized workflow includes that exact state transition. These actions may create commits and expose subsequent conflicts; resolving and staging paths alone does not imply permission. Never push, publish, approve, or alter remote state without separate authorization.
