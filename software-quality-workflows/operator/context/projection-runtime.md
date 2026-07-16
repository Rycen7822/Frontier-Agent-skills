# Context Projection Runtime

Host-native plans, todos, active-card leases, and context traces are disposable projections over controller truth.

- A host UI may display a supplied node-status mapping and report missing, orphaned, or drifted rows.
- Resume regenerates projections from validated workflow and artifact state.
- Deleting a context trace or expiring a card lease never changes workflow validity or canonical state hash.
- A model receives only the current primary card, at most one approved neighbor, and bounded artifact/invariant/evidence projections for the current decision.
- Mandatory authority, safety, hard-constraint, verifier-identity, and freshness fields are never truncated. An over-budget mandatory projection returns a typed blocker.

Projection code must preserve bundle, source, scope, policy, artifact, and card identity. It never selects product design, grants authority, accepts a workflow transition, or treats a host UI row as canonical state.
