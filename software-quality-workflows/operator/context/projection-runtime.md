# Context Projection Recovery

The projection directory contains at most `workflow-context.md` and its fixed `workflow-context.md.tmp`. Both must be regular, single-link, owner-only files with a valid canonical header for this workflow and renderer. Any other entry, unsafe file, foreign workflow, foreign renderer, or malformed header blocks route, complete, render, and operator append without changing the conflicting bytes.

`workflow-context.md` is owner-disposable. A final from an earlier state of the same workflow and renderer may remain while semantic state advances; a fresh render receipt replaces it with the current deterministic projection. Removing the final does not affect workflow validity, state hashing, leases, events, or artifacts.

`route resume` removes only a `workflow-context.md.tmp` whose full header exactly matches the current workflow, state version/hash, frontier decision/card ID/card hash, and renderer hash. It syncs the projection directory after deletion and leaves a matching final in place. A stale or foreign temp is preserved and reported as a conflict. Projection cleanup never advances semantic state, publishes an artifact, changes a lease, appends an event, or grants another card.

Render uses the same fixed-temp atomic replacement sequence: write and sync the exact candidate temp, replace the final, then sync the projection directory. A retry after interruption converges to the same bytes. The state/locks bytes and modification times remain unchanged throughout rendering and projection recovery.
