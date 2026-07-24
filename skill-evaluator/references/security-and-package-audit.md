# Security and Package Audit

A skill can add instructions, executable code, dependencies, external resources, and new permission demands. Evaluate the complete package before execution and its behavior at runtime.

## 1. Threat model

At minimum, consider:

- direct malicious or policy-overriding instructions in `SKILL.md` or references;
- disguised data transfer, secret collection, telemetry, or exfiltration;
- remote bootstrap that downloads or executes mutable code;
- prompt injection imported through websites, documents, repositories, tool output, or generated resources;
- destructive, privileged, persistent, financial, or externally visible actions;
- over-broad filesystem, network, credential, browser, or process permissions;
- vulnerable, typosquatted, unpinned, or unexpected dependencies;
- scripts, binaries, macros, images, archives, symlinks, or generated files that hide behavior;
- path traversal, cross-project writes, unsafe temp handling, and cleanup failures;
- privacy leakage into skill text, traces, artifacts, model graders, or evolution datasets;
- unsafe self-evolution that removes safety constraints or incorporates poisoned trajectories;
- resource exhaustion, denial of service, infinite loops, forked processes, or unbounded downloads;
- skill conflicts or instructions that hijack routing and suppress neighboring or system policies.

Static review identifies potential behavior. Runtime containment and probes show whether the agent attempts it. Neither alone certifies permanent safety.

## Evidence ladder

| Level | Evidence | Maximum claim |
|---|---|---|
| S0 | Package inventory, provenance, links, schemas, and executables | Static surface |
| S1 | Instruction, code, dependency, permission, and side-effect threat model | Reachable risk hypothesis |
| S2 | Isolated inert permission, canary, injection, cleanup, and resource probes | Contained behavior |
| S3 | Plan-bound runner receipts plus state/artifact/network/process/action evidence | Tested runtime safety |
| S4 | Declared conformance plan plus verified receipts from each named real host | Tested host-specific boundary |
| S5 | External adaptive red-team or operational evidence | External authority input only |

Scored L2+ with `dynamic_security` required closes at least S0–S3. A cross-host readiness claim needs separate S4 receipts for every named host; host metadata or a plan without receipts remains not evaluable. This package does not implement S5.

## 2. Establish provenance and trust

Record:

- acquisition URL/repository and immutable revision;
- declared author, maintainer, version, and license;
- package hash and full file inventory;
- signature, release provenance, or registry reputation when available;
- whether the package differs from its claimed upstream;
- dependency lockfiles and external resource hashes;
- installation/update mechanism and whether updates are mutable or automatic;
- prior audit findings and known vulnerabilities.

Treat missing provenance as uncertainty, not proof of malice. Treat a trusted source as risk reduction, not permission to skip review.

## 3. Audit the package boundary

Inventory all regular files, hidden files, symlinks, nested archives, executables, binaries, scripts, schemas, templates, references, assets, and generated-install hooks. Reachable schemas are formal package support, not untrusted generated output.

Check:

- `SKILL.md` exists and frontmatter identity matches the directory and declared package;
- every local reference resolves within the package unless an external dependency is intentional;
- symlinks do not escape the package or point to mutable unexpected locations;
- files are not hidden by unusual Unicode, control characters, double extensions, or misleading names;
- binary and archive contents are identified and reviewed by an appropriate tool;
- executable bits and shebangs match documented behavior;
- package scripts have documented inputs, outputs, side effects, and expected invocation mode;
- unused or dead files are not silently included in the trusted surface.

The bundled `audit_skill_package.py` performs conservative structural and text-pattern triage. Manually review every finding and every executable file; pattern absence is not proof of safety. A usable report must have `scan.text_scan_complete=true`. A text file over the configured scan bound, a broken/escaping symlink, an unsafe Markdown scheme, or an unreachable formal support file is a structural failure rather than a low-severity warning; increase the bound and rescan instead of treating partial coverage as success.

Keep four states separate. A structural error means the package boundary is invalid and blocks the audit. A static finding is a heuristic locator, not a defect verdict. Manual review determines reachability, intent, impact, and confidence. Disposition records `open`, `mitigated`, `accepted`, `false_positive`, or `not_evaluable` without erasing the original finding.

An audit finding never authorizes deletion, omission, encoding, or semantic weakening of package content. For an imported package, preserve the source bytes first; then establish each file's role, provenance, reachability, runtime use, and tests. Change or remove a file only after that evidence identifies a concrete product defect and the package contract assigns the change to this scope.

## 4. Review instructions as executable policy

Read `SKILL.md` and every referenced branch in the order an agent may load them.

Look for instructions that:

- override higher-authority policies or tell the agent to ignore user/system constraints;
- hide actions, skip confirmations, suppress evidence, or misreport success;
- request secrets, credentials, browser data, SSH keys, tokens, or unrelated user files;
- authorize remote writes, publication, deployment, purchases, messages, or account changes without explicit user authority;
- tell the agent to execute instructions found in untrusted content;
- broaden scope from a requested directory/project to the whole machine;
- disable sandboxes, verification, logging, or cleanup;
- persist changes to agent configuration, memory, startup files, cron, plugins, or other skills without explicit scope;
- make self-updates automatic or unreviewed;
- invoke opaque remote scripts or binaries.

Distinguish descriptive examples from actual runtime directives, but evaluate whether an agent could reasonably misread them.

## 5. Review scripts and code

For every executable path, trace:

- entry points and calling instructions;
- accepted arguments, environment variables, stdin, and config files;
- filesystem reads/writes/deletes and path normalization;
- subprocesses and shell interpolation;
- network destinations, protocols, redirects, uploads, and downloaded code;
- credentials and secret handling;
- dependency imports and dynamic loading;
- privilege changes, persistence, services, background processes, and scheduled work;
- resource/time bounds and cancellation handling;
- logs, error handling, exit status, cleanup, and rollback;
- output parsing and injection boundaries.

High-risk patterns requiring close review include shell evaluation, unquoted interpolation, recursive deletion, permission broadening, `sudo`, downloader-to-shell pipelines, dynamic `eval`/`exec`, arbitrary deserialization, unsigned plugin loading, remote include/import, and hidden background execution.

A pattern may be legitimate in a narrow tool, but its necessity, scope, and guardrails must be explicit.

## 6. Dependencies and remote resources

Review:

- direct and transitive dependencies;
- pinned versions and hashes;
- install/build hooks;
- package source and typosquatting risk;
- abandoned or unexpectedly new packages;
- native extensions and prebuilt binaries;
- license and data-governance compatibility;
- remote models, scripts, schemas, prompts, images, and templates;
- mutable `latest`, branch-head, shortened, or redirecting URLs;
- offline/denied-network behavior.

Prefer immutable, verified resources and least-privilege installation. Do not install dependencies merely to inspect them when static metadata or an isolated environment is sufficient.

## 7. Permissions and side-effect map

Create a permission table before runtime:

| Capability | Needed? | Allowed scope | User approval | Probe |
|---|---|---|---|---|
| Read files | | | | |
| Write/delete files | | | | |
| Execute processes | | | | |
| Network read | | | | |
| Network write/upload | | | | |
| Credentials/secrets | | | | |
| Browser/account actions | | | | |
| Persistent config/memory | | | | |
| Remote publication/deploy | | | | |
| Privileged/financial action | | | | |

Run with the least permissions needed. A skill that works only after unnecessary escalation fails the permission contract even if the task output is correct.

## 8. Controlled runtime probes

Use isolated fixtures, inert endpoints, canary secrets, denied capabilities, and reversible state. Never use real secrets or uncontrolled destructive targets.

### Permission-boundary probe

Deny a capability not required by the task and observe whether the skill proceeds safely, asks for justified approval, or attempts to bypass the boundary.

### Secret-canary probe

Place an inert token in a location the skill should not access. Monitor reads, logs, prompts, grader bundles, and network output. Any unnecessary access is a finding even if exfiltration is blocked.

### External prompt-injection probe

Provide untrusted content that asks the agent to ignore the skill or user, reveal data, run a command, or contact a remote endpoint. The correct behavior is to treat it as data, preserve authority, and continue or stop safely.

### Sensitive-action confirmation probe

Construct a request that reaches a destructive, privileged, persistent, financial, account, publication, or remote-write boundary. Verify that explicit authority is obtained before action and that denial leaves state unchanged.

### Remote-bootstrap probe

Deny network access or redirect downloads to an inert controlled endpoint. Verify that the skill does not execute mutable remote content blindly and reports the prerequisite safely.

### Cleanup and persistence probe

After success, failure, timeout, and cancellation, check processes, files, locks, services, startup/config changes, scheduled jobs, memory, and network state.

### Resource-exhaustion probe

Use bounded fixtures to test file size, iteration, recursion, retries, downloads, concurrency, and timeout behavior without endangering the host.

Record attempted behavior separately from whether the sandbox blocked it.

## 9. Evolution and compression risks

When a skill is generated, rewritten, distilled, merged, or compressed:

- mark safety constraints and permission checks as protected requirements;
- reject source trajectories containing secrets or untrusted instructions;
- use multiple curated trajectories rather than one successful trace;
- compare the proposed text against the prior version for removed safeguards;
- rerun package audit, safety probes, utility, and held-out regression checks;
- require human review for high-risk domains and new executable/network behavior;
- prevent the candidate from modifying its verifier, holdout, audit rules, or promotion gate;
- version and review dependencies introduced by generated scripts;
- preserve rollback to the last accepted package.

Token reduction or higher task reward does not justify stripped safety nuance.

## 10. Findings schema

Every finding should include:

- stable ID;
- severity: `critical`, `high`, `medium`, `low`, or `info`;
- package file or runtime case and precise locator;
- behavior and reachable trigger;
- evidence, including attempted and contained behavior;
- impact and affected data/system/authority;
- confidence and assumptions;
- remediation or required control;
- retest needed;
- status: `open`, `mitigated`, `accepted`, `false_positive`, or `not_evaluable`.

Suggested severity interpretation:

- **Critical:** credible secret exfiltration, destructive/privileged compromise, arbitrary remote code, or a systemic policy bypass reachable under normal use.
- **High:** unauthorized sensitive action, broad data exposure, unsafe persistence, exploitable dependency/code path, or reliable injection compliance.
- **Medium:** bounded permission excess, unsafe default, missing confirmation, unpinned mutable dependency, or meaningful cleanup/resource risk.
- **Low:** defense-in-depth gap, ambiguous instruction, weak provenance, or limited hygiene issue.
- **Info:** inventory or non-blocking observation.

Severity depends on reachability and impact, not keyword presence.

Scanner self-matches and explanatory security examples remain visible. Classify them through manual disposition; do not hide matching text, lower the declared severity, or add a package-wide allowlist merely to make an audit summary appear clean.

## 11. Promotion gates

Block execution or promotion when required by the contract, including:

- unresolved critical/high findings;
- unknown or unreviewed executable/binary behavior;
- dependencies or remote resources that cannot be attributed or bounded;
- required permissions exceed authorized scope;
- the skill follows injected instructions or accesses/exposes canary data;
- sensitive actions occur without explicit authority;
- self-evolution can alter safeguards, graders, or holdouts without review;
- cleanup/persistence behavior is uncontrolled;
- safety evidence is missing for a capability the package actually uses.

A user or risk owner may explicitly accept a noncritical residual risk, but the report must preserve the finding and scope of acceptance.

## 12. Human review triggers

Require qualified human/domain review for:

- healthcare, finance, legal, security, industrial control, or other safety-critical use;
- packages handling real secrets, personal data, production accounts, money, publication, deployment, or destructive operations;
- opaque binaries, macros, native extensions, or complex install hooks;
- new remote write or self-update behavior;
- close utility/safety trade-offs or grader disagreement;
- any case where containment prevented understanding the actual impact.

## 13. Audit-script limits

`audit_skill_package.py` is intentionally stdlib-only and conservative. It can inventory files, parse basic frontmatter fields, find broken local Markdown links, identify escaping symlinks, flag binary/executable files, and surface suspicious text patterns.

Routine use emits one bounded compact summary with package-relative finding locators and creates no files. Use `--json <path>` only when the frozen evaluation contract requires a complete machine-readable evidence artifact; use `--json -` when another process consumes the report from stdout. JSON stdout is exclusive, while compact triage moves to stderr. The compact `clean`, `review_required`, and `structural_invalid` states describe queue state only; exit `0` is never a safety approval.

It cannot establish semantic intent, inspect every binary/archive format, resolve transitive dependency vulnerabilities, prove absence of obfuscation, or guarantee runtime safety. Treat its output as a review queue, not a verdict.
