# Optional Plugin Runtime Gate

No plugin runtime is implemented or enabled by this skill revision. Activation status is `empirical_validation_required`.

The [local-filesystem](local-filesystem.md) adapter is the safe P1 fallback. Use it unless measured M2/M3 workloads show that transaction, lock, resume, event, or remote-worker limitations are an actual bottleneck and the local adapter is insufficient.

A future on-demand plugin must pass all of these gates before canary activation:

- P1 shows positive net success/context/recovery benefit on preregistered workloads;
- source/scope/plan CAS, event transaction, lock lease, retry, approval, invalidation, resume, and closure fault injection passes;
- sensitive classification, redaction/encryption, retention, cleanup, and audit export have an engineering owner;
- the tool namespace remains seven high-level calls or fewer and is not a default always-loaded burden;
- plugin unavailable/corrupt state falls back to local-filesystem or reports an explicit blocked state;
- canary rollback removes plugin activation without invalidating canonical plan/workflow artifacts.

Do not create, install, publish, register, or enable a plugin from this adapter document. Those actions require separate authority and the P2 evidence gates.
