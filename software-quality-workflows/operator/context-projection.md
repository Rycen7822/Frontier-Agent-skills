# Context projection runtime

`scripts/project_context.py` renders disposable current-frontier context; it never mutates controller state. Inputs bind one to three exact live-manifest card IDs/hashes and explicit artifact projection IDs. Bundle or card drift fails closed.

The effective envelope is at most 8,192 bytes. Workflow/source/scope identity, authority, applicable invariants, current objective/effects, verifier requirements, and selected-card bindings are mandatory. Mandatory overflow is a blocker; optional evidence is omitted whole and reported by ID. Sensitive or credential-shaped content renders only a controlled pointer.

`context_trace_ref` is deletable and excluded from canonical workflow hashing. Rebuilding the same projection against the same state, cards, and artifact projections must reproduce its projection hash without changing workflow state.
