# Qoder plugin shell

This repository is itself an installable Qoder plugin. The shell is the manifest at
[`.qoder-plugin/plugin.json`](../.qoder-plugin/plugin.json); the ten skill directories next to it are the payload, so the
skills are used exactly as they are shipped for Codex and Hermes Agent.

## Layout

```text
Frontier-Agent-skills/
  .qoder-plugin/plugin.json   portable Qoder manifest (name, version, description, declared skills)
  code-review/                ten skill roots, each with SKILL.md
  ...
  packaging/qoder-plugin/plugin.json.template
```

The ten skill roots sit at the repository top level, so the manifest declares them explicitly through its `skills`
field instead of relying on a single `skills/` directory. The declared list is the canonical skill set from
`bundle-manifest.json`; `scripts/build_qoder_plugin.py` renders the manifest from that source and fails when a path
is missing, unsorted, renamed or no longer carries a `SKILL.md` with matching `name` and a `description`.

## Install

```bash
qoder plugins validate /path/to/Frontier-Agent-skills
qoder plugins install  /path/to/Frontier-Agent-skills
```

Validating and installing a local checkout needs no marketplace. To publish the repository as a marketplace instead,
point Qoder at the clone or the repository URL and add a `marketplace.json` whose `plugins` entry names
`frontier-engineering` and sets `strict` to `false` only if the plugin folder lacks this manifest:

```bash
qoder plugins marketplace add https://github.com/Rycen7822/Frontier-Agent-skills.git
qoder plugins install frontier-engineering
```

A plugin is installed from a local directory only when Qoder finds at least one recognizable component, and the
manifest itself is optional for Qoder. It is declared here to pin the name, the release version, the human-readable
descriptions and the skill list.

## Boundaries

- The shell adds no `hooks`, `mcpServers`, `commands`, `agents`, `bin`, `outputStyles`, `workflows` or `settings`
  surface, and no dependency. Qoder receives the same read/write skill content as every other host.
- The Codex release artifact keeps its own `.codex-plugin/plugin.json`; the two manifests are generated from separate
  templates and never substitute for each other. The Qoder shell is not copied into the Codex plugin staging tree.
- `metadata.hosts` in each `SKILL.md` is declarative documentation. No code in this repository reads it, and Qoder does
  not either, so the list does not gate any host.
- The version comes from `bundle-manifest.json`. A release that changes the bundle version must re-render the shell.

## Verification

```bash
python3 scripts/build_qoder_plugin.py --check
python3 -m unittest tests/test_qoder_plugin.py -v
```

The check is model-free: it proves the committed manifest equals the rendered manifest, that its fields stay inside the
documented Qoder schema, that the declared skills are exactly the canonical directories, and that the shell contains no
developer path or placeholder. It does not prove how a Qoder build discovers or invokes the skills; run
`qoder plugins validate` on an installation to observe that.
