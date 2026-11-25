# Host installation and invocation

FAS uses each host's native loading mechanism. Installation and package checks do not guarantee automatic model selection. Start a fresh host process after installation when the host caches its catalog.

## Support at a glance

| Host | Installation surface | Verified boundary |
|---|---|---|
| Pi | One Git package with a native skill-discovery manifest | Package updates, model-prompt exclusion and explicit slash-command loading were checked with Pi 1.6.0. |
| Codex | An installable plugin marketplace | Package validation and isolated Codex CLI installation and removal are checked without model calls. |
| Hermes Agent | Native skill directories plus five standalone command plugins | Native catalog exclusion and command-message delivery are checked in an isolated Hermes home. |
| Qoder | The repository's `.qoder-plugin/plugin.json` manifest | Manifest generation and package shape are checked. Runtime discovery and invocation policy are unverified. |
| ZCode | The repository's `.zcode-plugin/plugin.json` manifest, installed through `marketplace.json` | Manifest validation, marketplace registration and installation were checked with ZCode CLI 0.18.0 for bundle 11.6.1. The current bundle's manifest is checked locally. Invocation policy is unverified. |

## Pi

Install the current source package:

```sh
pi install git:github.com/Rycen7822/Frontier-Agent-skills
```

Run `/reload` or start a new session. Invoke a skill directly with:

```text
/skill:code-review Review the current diff for actionable defects.
/skill:improve-docs Improve docs/install.md for a new contributor.
```

Update all installed Pi packages, then reload:

```sh
pi update --extensions
```

To update only FAS, use `pi update --extension git:github.com/Rycen7822/Frontier-Agent-skills`. The [`package.json`](../package.json) manifest discovers `skills/*/SKILL.md`. It adds no extension code, hooks or dependencies, and it does not rewrite personal settings.

Clean Code Comments, Codebase Improve, Improve Docs, Reframe and Sharpen declare `disable-model-invocation: true`. Pi excludes them from the default model prompt but keeps their `/skill:<name>` commands available. Other FAS skills remain eligible for model selection.

### Migrate individual Pi paths

Older installations may list each FAS skill directory in the `skills` array in `~/.pi/agent/settings.json`. Confirm that the Git package loads all required skills, then remove only the redundant FAS paths. Keep the Git package entry, unrelated skills and other settings. Use `pi config` to select a subset through package filters. For an existing filter that matches an old repository-relative path such as `improve-docs/SKILL.md`, change it to `skills/improve-docs/SKILL.md`.

## Codex

Install a published marketplace archive or build the current source with [the Codex packaging guide](development.md#build-a-codex-marketplace). After building the local marketplace, register it and install the plugin:

```sh
codex plugin marketplace add /absolute/path/to/marketplace
codex plugin add frontier-engineering-plugin@frontier-engineering-v8-release
```

The marketplace name above belongs to the current source builder. Start a new Codex session after installation or replacement so it reads the installed package from disk.

Invoke a packaged skill with:

```text
$frontier-engineering-plugin:code-review Review this diff.
$frontier-engineering-plugin:improve-docs Improve this RFC without changing its decision.
```

A direct standalone skill installation uses `$<skill>` instead. Clean Code Comments, Codebase Improve, Improve Docs, Reframe, Sharpen, Software Quality Workflows and Skill Evaluator set `allow_implicit_invocation: false`. The other nine skills are eligible for automatic local selection. All skills retain explicit invocation.

## Hermes Agent

Install the eleven model-visible FAS skills as native skill directories under `~/.hermes/skills`. Keep the five command-only skills out of this directory. From a source checkout, link the complete model-visible set:

```sh
FAS=/absolute/path/to/Frontier-Agent-skills
mkdir -p ~/.hermes/skills
for skill in code-review code-simplifier codebase-investigation debugging long-document-segmented-writing runtime-verification skill-evaluator software-design software-quality-workflows test-behavior writing-plans; do
  ln -s "$FAS/skills/$skill" "$HOME/.hermes/skills/$skill"
done
```

Keep the linked source directories available. Existing targets are not overwritten. When upgrading from the old layout, replace only FAS symlinks in `~/.hermes/skills` and `~/.hermes/plugins` that still point to `<checkout>/<name>`. Use `<checkout>/skills/<name>` for the replacement targets, then restart Hermes. If you install a subset, preserve the sibling skills required by its relative links.

Do not put Clean Code Comments, Codebase Improve, Improve Docs, Reframe or Sharpen in `~/.hermes/skills` or another automatically scanned skill root. Hermes does not honor the Codex and Pi visibility flags in the inspected loader. Install each of these directories as a standalone plugin instead:

```sh
mkdir -p ~/.hermes/plugins
ln -s /absolute/path/to/Frontier-Agent-skills/skills/improve-docs ~/.hermes/plugins/improve-docs
hermes plugins enable improve-docs
```

Replace `improve-docs` with `clean-code-comments`, `codebase-improve`, `reframe` or `sharpen` to install another command. Invoke the enabled command in a classic Hermes CLI session:

```text
/improve-docs Improve the setup guide for a new contributor.
```

The adapter registers only a user command. It registers no model tool, hook, skill or system-prompt section. On invocation, it reads the installed `SKILL.md` and queues the instructions and user request through `inject_message`. A queued request is not a completed task. The adapter does not inject into a gateway or another session.

FAS installation does not require changes to personal `AGENTS.md` or `SOUL.md` files.

## Qoder

Validate and install a local checkout:

```sh
qoder plugins validate /absolute/path/to/Frontier-Agent-skills
qoder plugins install /absolute/path/to/Frontier-Agent-skills
```

The manifest includes all sixteen skill directories. The repository does not establish that Qoder keeps explicit-only skills out of model discovery. See [Qoder packaging](qoder-plugin.md) for marketplace and maintainer details.

## ZCode

The repository is a ZCode plugin marketplace. Add it as a marketplace, then install the single plugin that carries all sixteen skills:

```sh
zcode plugins marketplace add Rycen7822/Frontier-Agent-skills
zcode plugins install frontier-engineering@frontier-skills
```

Update an existing installation and refresh the catalog:

```sh
zcode plugins marketplace update frontier-skills
zcode plugins update frontier-engineering
```

The marketplace entry points at the repository root, so a plugin name already installed from a directory source keeps working after the same name is added from GitHub. Skill identities are namespaced as `frontier-engineering:<skill>` with the bare skill name as an alias. ZCode reads `.zcode-plugin/plugin.json`, then falls back to `.claude-plugin/` and `.codex-plugin/`; the repository ships only the ZCode manifest so the plugin declares no duplicate component set.

Do not also copy individual skill directories into `~/.zcode/skills` or `~/.agents/skills`. Those locations are scanned before plugin roots, so a leftover copy shadows the plugin version and keeps serving stale content after an update.

## Verify the installed behavior

Check model visibility and explicit user loading separately. Inspect the host's native catalog or prompt, then invoke the command and confirm that it loads the installed instructions and preserves the request. A running session can retain an older catalog or body.

These checks establish delivery and loading. Measuring whether a model chooses the right skill or completes a task better requires separate execution evidence.
