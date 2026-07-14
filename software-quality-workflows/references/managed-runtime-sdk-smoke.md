# Managed Runtime SDK Smoke

> Owner: managed-runtime-sdk-smoke
> Authority: companion
> Role: recipe
> Phases: BASELINING, SIGNING_OFF
> Requires: runtime-version-contracts, verification-discipline
> May load: plugin-installed-surface
> Does not own: supported-version policy, installation authority, release readiness

Run only against the contract's declared runtime/SDK/version matrix. Record exact runner provenance, clean environment, import/entrypoint exercised, exit status, and adjacent-version limitation. A smoke proves addressability, not full semantics.
