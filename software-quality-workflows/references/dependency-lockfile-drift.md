# Dependency and Lockfile Drift

> Owner: dependency-lockfile-drift
> Authority: companion
> Role: recipe
> Phases: BASELINING, SEARCHING, SIGNING_OFF
> Requires: runtime-version-contracts, verification-discipline
> May load: security-hardening
> Does not own: dependency policy, upgrade authority, supply-chain verdict

Compare declared constraints, resolved lock data, installed runtime, provenance, and supported-version matrix. Classify intentional resolution, stale lock, transitive drift, platform marker, integrity mismatch, and unauthorized upgrade separately; never regenerate a lockfile merely to make a gate green.
