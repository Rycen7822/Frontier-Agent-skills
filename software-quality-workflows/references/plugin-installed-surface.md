# Plugin Installed Surface

Use this narrow recipe when the user-facing runtime is an installed or copied plugin and source tests cannot prove its actual layout, provenance, discovery, or public entrypoint.

This recipe does not authorize an installation, host configuration change, or profile mutation. Resolve mode, scope, and side effects through the [authority and scope owner](authority-and-scope.md), and record evidence according to [verification discipline](verification-discipline.md). Use [plugin quality](plugin-quality.md) for the complete layer model.

## Preconditions

- Identify the repository's canonical build, package, and install/sync entrypoints from current source or documentation.
- Capture source revision and working-tree state with read-only inspection so installed provenance can be compared later.
- Identify the host's discovery root, selected profile, cache/reload behavior, and supported neutral working directory without exposing machine-specific paths in reports.
- Prefer isolated configuration and disposable state for lifecycle or error-path probes.
- Define the exact public capability and safe error path that will serve as the smoke proof.

## Installed-surface sequence

1. Complete source and built-output proof before changing an installed surface.
2. Inspect the package or staging tree for entrypoints, manifests, dependency metadata, schemas, templates, migrations, and other declared assets.
3. Run a built-artifact smoke from the generated tree so missing assets or module layout fail before installation.
4. If installation is authorized, use the repository or host's canonical installer rather than an undocumented hand copy.
5. Inspect the installed tree and provenance independently from the source checkout. Confirm that no runtime path depends on incidental source files.
6. Start a fresh host process or supported loader probe from a neutral working directory and inspect discovered plugin identity and capabilities.
7. Invoke one representative read-only or isolated-state public operation and one designed rejection where safe.
8. Compare installed provenance with the intended source/build state and identify whether the current already-running process requires a documented reload.
9. Restore temporary configuration and remove only task-owned scratch or isolated state.

## Asset and dependency parity

For every runtime asset family, verify the complete path:

```text
source declaration -> build output -> package/staging tree -> installed tree -> runtime read
```

Check all supported variants rather than one representative file. If runtime code resolves assets relative to its installed entrypoint, exercise that exact resolution path.

Verify that the installed runtime has a deliberate dependency strategy. A source checkout may hide missing package metadata or dependencies that a copied runtime cannot resolve.

## Safe state handling

- Keep backups outside discovery roots unless the plugin manager explicitly guarantees that backup entries are ignored.
- Do not test destructive lifecycle behavior against a user's real data or primary profile.
- Do not treat configuration restoration as complete until the restored value or absence is verified.
- Do not clean unrelated caches, profiles, plugins, or source outputs to make discovery pass.
- Treat current-process results as stale when discovery happens only at process startup.

## Failure localization

| Observation | First boundary to inspect |
|---|---|
| Built entrypoint fails | Build output, asset copier, module mode, dependency layout. |
| Package works but installed copy fails | Installer selection, copy rules, installed metadata, dependency resolution. |
| Installed entrypoint works but capability is absent | Host discovery, registration, profile selection, startup cache. |
| Internal call works but public command/tool fails | Public schema, argument parsing, wrapper, error propagation. |
| Existing process differs from fresh process | Reload semantics or stale capability cache. |

## Closeout checklist

- The installed proof used a neutral working directory and did not import from source accidentally.
- Provenance, runtime assets, dependencies, and registration all match the intended build.
- Public smoke evidence came from a fresh process where startup discovery matters.
- Any installation or configuration side effect stayed within authorized scope and was accounted for.
- Failures are assigned to a specific layer rather than hidden by a reinstall loop.
