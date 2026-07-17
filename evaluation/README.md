# Deterministic Replay and External L2 Evidence

`offline-route-replay.json` is the only tracked evaluation report in this directory. It is a content-bound `deterministic_diagnostic`, not a usefulness, pilot, or publication result.

The report executes the live 5.0/6.0 routers against:

- all 62 active decision cards;
- 16 entry cases;
- 62 near-miss selectors;
- 10 protected negative cases;
- five outcome-linked terminal paths.

It binds both router files, decision maps, card manifests, selector fixtures, sequence fixtures, the generated bundle identity, and the frozen baseline archive. The report is byte-deterministic and independent of Git HEAD. Changing a bound map, card identity, fixture, router, or generated bundle makes `--check` fail.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 scripts/evaluate_offline_route_replay.py --check
```

The required deterministic gates are exact 62-card coverage; entry accuracy, decision precision, decision recall, terminal-path completion, and protected-negative pass rate of 1.0; zero unnecessary card loads; and at most 8,192 active bytes per step. Sequence total bytes are reported only as a distribution and are not an external context-budget measurement.

Scored L2 work does not write into the candidate. A revision-bound external run root freezes the agent, model revision, reasoning effort, harness, system/tool/skill catalogs, sampling, environment, credentials class, timeout, treatment hashes, deterministic graders, blinded rubric grader, fixtures, and sealed holdout before execution. Its scored report and the separate activation decision remain external evidence.

Missing or failed deterministic or L2 gates leave activation at `shadow`. A release-mode plugin additionally requires external `release-evidence/2.0` bound to a clean signed source revision, deterministic report hash, scored L2 report hash, and activation-decision hash.
