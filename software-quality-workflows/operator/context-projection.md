# Context projection runtime

`scripts/card_cycle.py render` is the only model-facing context-render entry. It is available only for an established M2/M3 owner and accepts the previous receipt plus a 1,024–8,192 byte budget. The command does not accept a state path, card list, projection ID, artifact path, metadata output path, or sibling scan request.

Under the existing `.adapter.lock`, render validates the owner locator, bundle and manifest hashes, receipt `state_version` and `state_hash`, current source identity, active frontier, and projection directory. It then calls the pure renderer in `scripts/project_context.py` with exactly the active card already bound by state.

The only output file is `projections/workflow-context.md`; its only transient sibling is `projections/workflow-context.md.tmp`. The first-line canonical header binds the workflow ID, state version/hash, frontier decision/card ID/card hash, and renderer hash. The body preserves mandatory workflow, source, scope, authority, invariant, objective, verifier, and card bindings within the requested budget. Credential-shaped or sensitive content is reduced to a controlled pointer; optional sections are omitted whole rather than partially copied.

Render never changes `state.json`, `locks.json`, artifacts, or the optional event stream. The projection is absent from canonical state and receipts expose only its content locator. Replaying the same request against the same state returns the identical bytes without replacing the file. Deleting the final is valid and the same state rebuilds it byte-for-byte. Once state advances, the old receipt is stale and cannot render the new state.
