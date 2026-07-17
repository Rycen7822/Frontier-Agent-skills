# Shadow, Offline Replay, and Paired Evaluation

This directory implements the fail-closed effect and activation boundary for P8. The retained `p5-*` artifact names are the existing release-tool interface; they do not mean static evidence can satisfy P8. Nothing here publishes, enables autonomous closure, or expands remote-write authority. Real work continues through Direct/standard execution while real paired records are gathered outside the evaluated task surface.

`offline-route-replay.json` is a deterministic replay of 25 semantically aligned v4/v3 and vNext curated route cases. It binds the frozen baseline source-archive hash plus the live-validated generated bundle build ID and manifest-content hash; Git revisions belong only in external run attestations and never in tracked replay bytes. It currently proves 100% curated exact-primary routing, one-card limits, zero mandatory truncation in the replay, an M0 median/p95 of 3,404/4,044 active reference bytes, and an 88.2% median reference-byte reduction. It explicitly records that hidden routing, natural model behavior, outcome quality, and publication readiness remain untested.

`corpus/p5-shadow-corpus.json` is an honest seed inventory: one synthetic or safety-trap case for each of the 18 required task families. It deliberately contains no claimed historical case and does not meet the 50/50/30/20 minimums. `fixtures/no-live-runs.jsonl` is empty because no live paired cohort has been completed in this bundle.

Each real cohort must freeze model, reasoning effort, request, repository revision and dirty state, tools, permissions, network, budgets, verifier/holdout, publication ceiling, timeout, and external dependency snapshot into `fixed_variables_hash`. Changing the model, CLI, bundle, controller, or those variables starts a new cohort. Hidden oracles and human labels remain restricted pointers.

Run the deterministic evaluator from the bundle root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_shadow.py \
  --corpus evaluation/corpus/p5-shadow-corpus.json \
  --runs evaluation/fixtures/no-live-runs.jsonl \
  --controls evaluation/p5-control-evidence.json \
  --output evaluation/p5-shadow-report.json
```

Exit 0 means every P5 gate passed and the maximum next activation is explicit-only canary. Exit 2 means `remain_shadow`; it is an expected, non-success promotion decision rather than a crashed evaluator. Exit 1 means the input or output operation itself failed. A report is immutable and cannot be overwritten.

The paired evaluator requires complete fixed-variable cohorts, at least 150 cases across the four strata, at least one-third honest historical provenance, zero scope/authority/protected escapes, bounded Direct regression, admission precision, verifier and terminal/certificate gates, a paired closure benefit, and an adaptive-vs-always-on tax benefit. Control evidence covers all 127 vNext policy owners plus the nine required ablations: policy graph, card navigation, exact transport, context lease, artifact-boundary reroute, controller/context separation, immutable verifier, local invalidation, and one-card limit. The checked-in control file truthfully marks all controls `not_run`.

The ordered activation sequence is shadow → same-snapshot offline replay → real Sol `max` paired cohort → explicit local pilot → implicit M0 canary → M2/M3 local-write canary. Failure or missing evidence at any step leaves the bundle in `shadow`. Remote write, merge, release, and deploy always retain independent authority gates.
