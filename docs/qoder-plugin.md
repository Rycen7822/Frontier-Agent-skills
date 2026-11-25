# Qoder plugin shell

The repository is an installable Qoder plugin. The manifest at [`.qoder-plugin/plugin.json`](../.qoder-plugin/plugin.json) declares `frontier-engineering`, the bundle version and the sixteen canonical skill directories. Each directory is under `skills/` and listed explicitly in the manifest.

For user installation and invocation boundaries, see [the host guide](hosts.md#qoder).

## Layout

```text
Frontier-Agent-skills/
  .qoder-plugin/plugin.json
  skills/<skill>/SKILL.md
  skills/.manual/<skill>/SKILL.md
  packaging/qoder-plugin/plugin.json.template
```

`scripts/build_qoder_plugin.py` reads the bundle version and skill paths from `bundle-manifest.json` and the display metadata from the template. It validates the skill order, paths, names and descriptions. The manifest adds no hooks, MCP servers, commands, agents, binaries, output styles, workflows, settings or dependencies.

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

Run `python3 scripts/build_qoder_plugin.py` after changing the bundle version, skill set, or template. Then check the generated manifest:

```sh
python3 scripts/build_qoder_plugin.py --check
python3 -m unittest tests/test_qoder_plugin.py -v
```

These model-free checks prove that the committed manifest equals the rendered manifest, its fields fit the documented schema, the declared skills match the canonical directories, and the shell contains no developer path or placeholder. They do not prove Qoder runtime discovery or invocation behavior. Run `qoder plugins validate` on the target installation and test the actual host separately.
