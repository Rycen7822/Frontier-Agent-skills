# Qoder plugin shell

The repository is an installable Qoder plugin. The manifest at [`.qoder-plugin/plugin.json`](../.qoder-plugin/plugin.json) declares `frontier-engineering`, the bundle version and the fourteen canonical skill directories. The directories sit at the repository root rather than under one `skills/` directory.

For user installation and invocation boundaries, see [the host guide](hosts.md#qoder).

## Layout

```text
Frontier-Agent-skills/
  .qoder-plugin/plugin.json
  <skill>/SKILL.md
  packaging/qoder-plugin/plugin.json.template
```

`scripts/build_qoder_plugin.py` renders the manifest from `bundle-manifest.json`. It fails when a skill is missing, renamed, unsorted, undescribed or has frontmatter that does not match its declared name. The manifest adds no hooks, MCP servers, commands, agents, binaries, output styles, workflows, settings or dependencies.

The Codex package keeps its own `.codex-plugin/plugin.json`. The two manifests use separate templates and are not interchangeable. The Qoder shell is not copied into the Codex staging tree.

`metadata.hosts` in each `SKILL.md` is declarative documentation. No repository code reads it to gate a host.

## Install locally

```sh
qoder plugins validate /absolute/path/to/Frontier-Agent-skills
qoder plugins install /absolute/path/to/Frontier-Agent-skills
```

A local installation needs no marketplace. Qoder requires at least one recognizable component and does not require a manifest. FAS includes the manifest to pin the name, version, descriptions and skill list.

## Add a marketplace

To publish the repository as a marketplace, point Qoder at the clone or repository URL. Add a `marketplace.json` whose plugin entry names `frontier-engineering`. Set `strict` to `false` only if the plugin folder lacks `.qoder-plugin/plugin.json`.

```sh
qoder plugins marketplace add https://github.com/Rycen7822/Frontier-Agent-skills.git
qoder plugins install frontier-engineering
```

## Verify the package

The manifest version comes from `bundle-manifest.json`. Re-render it whenever the bundle version or skill set changes:

```sh
python3 scripts/build_qoder_plugin.py --check
python3 -m unittest tests/test_qoder_plugin.py -v
```

These model-free checks prove that the committed manifest equals the rendered manifest, its fields fit the documented schema, the declared skills match the canonical directories, and the shell contains no developer path or placeholder. They do not prove Qoder runtime discovery or invocation behavior. Run `qoder plugins validate` on the target installation and test the actual host separately.
