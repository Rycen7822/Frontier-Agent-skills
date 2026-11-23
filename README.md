# Frontier Agent Skills

Frontier Agent Skills (FAS) provides fourteen skills for software development, review, documentation, planning and evaluation. The current source bundle is `frontier-engineering/11.6.0`. FAS supports Codex, Pi and Hermes Agent through their native skill or plugin mechanisms. It also includes a Qoder plugin manifest, but Qoder runtime behavior remains unverified.

## Install on Pi

Install the current repository as one Pi package:

```sh
pi install git:github.com/Rycen7822/Frontier-Agent-skills
```

Start a new Pi session or run `/reload`. Try an explicitly invoked skill:

```text
/skill:improve-docs Improve README.md for new users.
```

Update the package and reload the catalog with:

```sh
pi update --extensions
```

Pi discovers added, renamed and removed skills from the package manifest. You do not need to edit `settings.json` when the skill set changes. For Codex, Hermes and Qoder installation, or migration from individual Pi skill paths, see [host installation and invocation](docs/hosts.md).

## Choose a skill

Describe the task in your normal prompt. Eligible skills can be selected from their descriptions. Invoke a skill directly when you want to require its workflow.

| Skill | Use for | Version |
|---|---|---|
| [software-quality-workflows](software-quality-workflows/SKILL.md) | Implement features, fix known problems and complete software changes with proportionate verification | 13.1.0 |
| [codebase-investigation](codebase-investigation/SKILL.md) | Explain implementation, cross-module behavior or design history | 1.1.2 |
| [debugging](debugging/SKILL.md) | Diagnose a failure, regression or performance problem whose cause is unknown | 1.1.2 |
| [software-design](software-design/SKILL.md) | Resolve consequential requirements, ownership, API, data-model or migration choices | 1.1.1 |
| [code-review](code-review/SKILL.md) | Find actionable defects and assess their realistic impact | 2.0.5 |
| [code-simplifier](code-simplifier/SKILL.md) | Simplify selected code while preserving behavior | 1.2.1 |
| [clean-code-comments](clean-code-comments/SKILL.md) | Audit comments, preserve real constraints and prevent unnecessary new comments | 1.0.0 |
| [codebase-improve](codebase-improve/SKILL.md) | Audit or improve architecture, responsibility and abstraction boundaries | 1.0.0 |
| [improve-docs](improve-docs/SKILL.md) | Co-author or improve documentation and test it with a fresh reader | 1.0.0 |
| [test-behavior](test-behavior/SKILL.md) | Decide when to write checks, what they should prove and how long to retain them | 1.0.0 |
| [runtime-verification](runtime-verification/SKILL.md) | Resolve evidence gaps by running the actual consumer or installation | 1.1.1 |
| [writing-plans](writing-plans/SKILL.md) | Turn settled decisions into an implementation plan | 9.1.2 |
| [long-document-segmented-writing](long-document-segmented-writing/SKILL.md) | Write long, source-grounded documents with recoverable progress | 3.1.0 |
| [skill-evaluator](skill-evaluator/SKILL.md) | Assess skill effectiveness from execution history or scoped evaluation evidence | 5.0.3 |

Start with one skill that owns the task. FAS does not require a fixed pipeline, model assignment, delegation strategy or external plugin.

## Understand invocation policies

Direct invocation syntax and automatic selection vary by host.

| Host | Direct invocation | Automatic-selection boundary |
|---|---|---|
| Codex | `$frontier-engineering-plugin:<skill>` | Nine skills are eligible. Clean Code Comments, Codebase Improve, Improve Docs, Software Quality Workflows and Skill Evaluator require explicit invocation. |
| Pi | `/skill:<skill>` | Eleven skills are eligible. Clean Code Comments, Codebase Improve and Improve Docs require explicit invocation. |
| Hermes | Native skill invocation, or `/clean-code-comments`, `/codebase-improve` and `/improve-docs` | The three command adapters stay out of the model-visible skill catalog. Other skills use the native catalog. |
| Qoder | Determined by Qoder | The package shape is checked. Model discovery and explicit-only behavior are not established. |

Eligibility does not guarantee selection. A source flag does not prove runtime behavior in another host. See [the host guide](docs/hosts.md) for setup and verification boundaries.

## Source and release status

Version 11.6.0 is prepared source. The [published 11.3.0 release](https://github.com/Rycen7822/Frontier-Agent-skills/releases/tag/frontier-engineering-v11.3.0) contains older artifacts. A source version change does not publish a release. Use [the release notes](RELEASE_NOTES.md) to distinguish source additions from published artifacts.

Repository tests, package checks and isolated host checks establish engineering behavior. They do not measure task success or model effectiveness.

## Maintain FAS

- [Build, test and release](docs/development.md) covers generated artifacts, source archives, verification and evaluation.
- [Qoder packaging](docs/qoder-plugin.md) explains the generated shell and its limits.
- [FAS 11 migration](docs/fas-v11-migration.md) covers retired review interfaces and compatibility obligations.
- [Codex skill reload supervisor](docs/codex-skill-reload-supervisor.md) documents an optional high-privilege development tool.
- [Code Simplifier 1.2.0](docs/code-simplifier-1.2.0.md) preserves the component's behavioral acceptance scenarios.

The bundle ships as one unit for packaged hosts. Adopted source terms travel with each skill. Pstack guidance is MIT licensed, and adapted Anthropic guidance is Apache-2.0 licensed.
