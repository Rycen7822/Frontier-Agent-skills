# Improve Docs

Use [`improve-docs`](../improve-docs/SKILL.md) only through explicit invocation to co-author or improve a document in a named scope. For example: “Improve the setup guide in `docs/install.md` for a new contributor” or “Review this RFC without editing it.” Its single `SKILL.md` contains the combined document workflow, technical-writing standards, Unslop catalog and Humanizer checks. It has no `references` directory and does not require the source skills to be installed.

- **Codex:** install the bundle and invoke `$frontier-engineering-plugin:improve-docs` followed by the task. A direct skill installation uses `$improve-docs`.
- **Pi:** install or update the [Pi package](../README.md#pi-package), reload the catalog, and invoke `/skill:improve-docs` followed by the task.
- **Hermes:** install the canonical directory as a standalone plugin, not in `~/.hermes/skills` or any other automatically scanned skill root. Invoke `/improve-docs` followed by the task in a classic Hermes CLI session.
- **Qoder:** the [plugin manifest](../.qoder-plugin/plugin.json) includes the skill, but the repository does not establish that the Qoder loader keeps it out of model discovery.

The original workflow may ask for context, offer structured or freeform work, and test the result with a fresh reader. It preserves the user's ability to skip stages or work freeform. Reader testing establishes document interpretation, not factual correctness; the user retains final review.

## Sources and licensing

The combined text preserves the rules from [Anthropic's Doc Co-Authoring](https://github.com/anthropics/skills/blob/main/skills/doc-coauthoring/SKILL.md), [Blader's Humanizer](https://github.com/blader/humanizer), and Cursor pstack's [Technical Writing](https://github.com/cursor/plugins/blob/main/pstack/skills/technical-writing/SKILL.md) and its required Unslop catalog. The applicable license notices are in [LICENSE](../improve-docs/LICENSE).
