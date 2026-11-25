# Host installation and invocation

FAS uses each host's native loading mechanism. Installation and package checks do not guarantee automatic model selection. Start a fresh host process after installation when the host caches its catalog.

## Support at a glance

| Host | Installation surface | Verified boundary |
|---|---|---|
| Pi | One Git package with a native skill-discovery manifest | Package updates, model-prompt exclusion and explicit slash-command loading were checked with Pi 1.6.0. |
| Codex | An installable plugin marketplace | Package validation and isolated Codex CLI installation and removal are checked without model calls. |
| Hermes Agent | Native skill directories plus five standalone command plugins | Native catalog exclusion and command-message delivery are checked in an isolated Hermes home. |
| Qoder | The repository's `.qoder-plugin/plugin.json` manifest | Manifest generation and package shape are checked. Runtime discovery and invocation policy are unverified. |
| ZCode | The repository's `.zcode-plugin/plugin.json` manifest, installed through `marketplace.json` | ZCode CLI 0.16.9 was used to verify the installed skill and command catalogs. The desktop scanner's hidden-directory exclusion was checked in source. |

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

To update only FAS, use `pi update --extension git:github.com/Rycen7822/Frontier-Agent-skills`. The [`package.json`](../package.json) manifest registers the `skills` and `skills/.manual` directories. It adds no extension code, hooks or dependencies, and it does not rewrite personal settings.

Clean Code Comments, Codebase Improve, Improve Docs, Reframe and Sharpen declare `disable-model-invocation: true`. Pi excludes them from the default model prompt but keeps their `/skill:<name>` commands available. Other FAS skills remain eligible for model selection.

### Migrate individual Pi paths

Older installations may list each FAS skill directory in the `skills` array in `~/.pi/agent/settings.json`. Confirm that the Git package loads all required skills, then remove only the redundant FAS paths. Keep the Git package entry, unrelated skills and other settings. Use `pi config` to select a subset through package filters. Update package filters that name old repository-relative paths. For example, replace `improve-docs/SKILL.md` or `skills/improve-docs/SKILL.md` with `skills/.manual/improve-docs/SKILL.md`.

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

Keep the linked source directories available. Existing targets are not overwritten. When upgrading, replace only stale FAS symlinks and restart Hermes. Native skills now live at `<checkout>/skills/<name>`; the five standalone plugins live at `<checkout>/skills/.manual/<name>`. If you install a subset, preserve the sibling skills required by its relative links.

Do not put Clean Code Comments, Codebase Improve, Improve Docs, Reframe or Sharpen in `~/.hermes/skills` or another automatically scanned skill root. Hermes does not honor the Codex and Pi visibility flags in the inspected loader. Install each of these directories as a standalone plugin instead:

```sh
mkdir -p ~/.hermes/plugins
ln -s /absolute/path/to/Frontier-Agent-skills/skills/.manual/improve-docs ~/.hermes/plugins/improve-docs
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

Install the FAS plugin:

```sh
zcode plugins marketplace add Rycen7822/Frontier-Agent-skills
zcode plugins install frontier-engineering@frontier-skills
```

To update an existing installation:

```sh
zcode plugins marketplace update frontier-skills
zcode plugins update frontier-engineering
```

Start a new session after installing or updating. The marketplace uses the repository root, so a plugin previously installed from a local copy keeps the same name after adding the GitHub marketplace. The eleven discoverable skills use `frontier-engineering:<skill>` or the bare name.

Run `/clean-code-comments`, `/codebase-improve`, `/improve-docs`, `/reframe`, or `/sharpen` followed by your request. Use `/<name>`, not `/skill <name>`. These commands expand to prompt text without running scripts or calling the `Skill` tool.

Check that the five names appear in `zcode commands list` and are absent from `zcode skills list`. The plugin omits them from its skill manifest, and ZCode's desktop scanner skips their `skills/.manual/` directory. If a name still appears as a skill, check for and remove only old FAS copies in `~/.zcode/skills`, `~/.agents/skills`, or project skill directories.

## Verify the installed behavior

Check model visibility and explicit user loading separately. Inspect the host's native catalog or prompt, then invoke the command and confirm that it loads the installed instructions and preserves the request. A running session can retain an older catalog or body.

These checks establish delivery and loading. Measuring whether a model chooses the right skill or completes a task better requires separate execution evidence.
