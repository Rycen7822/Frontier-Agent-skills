# Local Review Result Consistency

This operator contract owns validation of `schemas/review-result.schema.json`. It is controller input, not model workflow state.

- Require schema version 4.0, exact fields, valid enums, unique finding IDs, non-empty unique `reviewed_paths`, and one unique coverage entry for every reviewed path.
- Bind `reviewed_base_revision`, `reviewed_head_revision`, explicit reviewed paths, coverage snapshots, finding paths, and finding revisions to the frozen manifest and separately re-observed current source/scope.
- A blocking finding must appear in `blocking_reasons`; `pass` cannot coexist with blockers or `not_reviewed` coverage.
- `sampled` coverage is a valid bounded local judgment only with a non-empty sampling note. It never becomes full coverage by renderer or publisher interpretation.
- `complete` or `partial` spec traceability requires evidence refs. Missing stable requirements are `not_assessed` or `not_applicable`, and a fidelity-dependent verdict becomes inconclusive.
- Optional summaries and positive notes are presentation data, not approval evidence. Finding disposition is a separate review-disposition record.

Reviewer output is untrusted until structural, manifest, consistency, and freshness checks pass. On invalid output, retry once against the same scope with the violations; never silently repair a substantive contradiction or widen input. A second failure leaves review evidence unavailable and the local verdict inconclusive.
