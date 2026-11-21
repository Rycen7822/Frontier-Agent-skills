# Clean Code Comments

Use [`clean-code-comments`](../clean-code-comments/SKILL.md) to audit or clean up comments in a named scope. For example: “Audit comments in `src/parser` without edits” or “Clean up comments in this diff and ratchet the linter.” This is a user-invoked skill; other skills do not route to it automatically.

- **Codex:** install the bundle and invoke `$frontier-engineering-plugin:clean-code-comments` followed by the task. A direct skill installation uses `$clean-code-comments`.
- **Pi:** include the new skill directory in the package's resolved skill paths and invoke `/skill:clean-code-comments` followed by the task.
- **Hermes:** install the canonical directory as a standalone plugin, not in `~/.hermes/skills` or any other automatically scanned skill root. Invoke `/clean-code-comments` followed by the task in a classic Hermes CLI session.
- **Qoder:** the [plugin manifest](../.qoder-plugin/plugin.json) includes the skill, but the repository does not establish that the Qoder loader keeps it out of model discovery.

For a local Hermes installation, link the source or extracted archive directory and enable the command:

```sh
mkdir -p ~/.hermes/plugins
ln -s /absolute/path/to/Frontier-Agent-skills/clean-code-comments ~/.hermes/plugins/clean-code-comments
hermes plugins enable clean-code-comments
```

Keep the linked directory available and reload the host catalog or start a fresh session after installation. No global instructions need to change.
