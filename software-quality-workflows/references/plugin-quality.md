# Plugin Quality

Use this reference when packaging, host registration, generated runtime assets, installed-copy behavior, dormant integration surfaces, or end-to-end plugin acceptance matters beyond ordinary application tests.

For request mode and installation or registration side effects, follow the [authority and scope owner](authority-and-scope.md). For the required proof set, follow [verification discipline](verification-discipline.md). Use [API and interface design](api-interface-design.md) for manifest, tool, command, event, or protocol contracts. This reference owns the plugin layer model; [plugin installed surface](plugin-installed-surface.md) is its narrow installed-runtime recipe.

## Quality model

Treat each layer as a distinct artifact and failure boundary:

| Layer | Required question |
|---|---|
| Source | Do source tests and static checks prove the intended behavior? |
| Built output | Does the generated entrypoint run with every required non-code asset and dependency? |
| Package | Does the distributable contain the intended files, metadata, permissions, and version? |
| Installed copy | Can the installed tree run without reaching into the source checkout? |
| Host registration | Does a fresh host process discover exactly the intended plugin and capabilities? |
| Public surface | Can a user invoke representative commands, tools, skills, hooks, or UI paths through the supported entrypoint? |

A green lower layer does not prove a higher one. Record each layer as passed, failed, not run, or not applicable rather than collapsing them into one result.

## Workflow

1. Inventory public surfaces, supported host/runtime versions, canonical build and packaging entrypoints, generated assets, and registration metadata.
2. Define the acceptance matrix by layer. Include at least one dormant surface that ordinary source tests do not load.
3. Prove source behavior and public schemas before packaging changes.
4. Build through every supported path that can produce a user-facing runtime. Inspect the resulting file tree and run a built entrypoint.
5. Inspect the distributable independently from the source tree. Confirm manifests, schemas, templates, migrations, static files, and runtime metadata are present where consumers resolve them.
6. When installed behavior is in scope and authorized, follow the installed-surface recipe from a neutral working directory and a fresh process.
7. Exercise representative public success and safe error paths through the same entrypoint users receive.
8. Report results per layer and classify any gap at the first failing boundary.

## Packaging rules

- Do not assume compilation copied runtime assets. Declare and verify every asset family.
- Keep package metadata, dependency strategy, module/runtime mode, and entrypoint layout deliberate and testable.
- If multiple build or packaging paths are supported, prove each one or remove the unsupported path from the contract.
- Ensure installed code resolves only declared package dependencies and assets, not incidental source-checkout layout.
- Keep generated output out of source control unless the repository explicitly treats it as a maintained artifact.
- Preserve provenance sufficient to distinguish source revision, build, package, and installed copy without exposing private machine details.

## Registration and public-surface proof

- Use a fresh process when discovery or capability lists are cached at startup.
- Assert both intended presence and intended absence; a disabled server, hook, command, or capability must remain absent.
- Detect duplicate registration and scan-visible backup copies.
- Exercise one read-only or isolated-state public operation when available instead of relying only on internal imports.
- Separate current-process staleness from an installed-copy defect.

## Failure classification

Classify a failure as source behavior, build, package contents, installed layout, registration, public contract, harness expectation, environment, permission, or stale process. Reproduce at the lowest failing layer before changing product behavior.

## Closeout checklist

- Every supported layer has an explicit status and evidence anchor.
- Built and packaged artifacts include all runtime assets.
- Installed proof, when required, runs outside the source checkout.
- Fresh-process discovery matches the intended capability surface without duplicates.
- Error-path checks use valid inputs and distinguish designed rejection from a defect.
- Temporary state and configuration created for acceptance are restored or accounted for.
