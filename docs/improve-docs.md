# Improve Docs

[`improve-docs`](../skills/.manual/improve-docs/SKILL.md) 1.1.0 writes and improves technical documentation in a named scope. It requires explicit user invocation and defaults to direct editing without routine questions or section-by-section approval.

Example requests:

```text
Improve docs/install.md for a new contributor.
Write an API guide from the current parser implementation.
Review this RFC without editing it.
```

The agent gathers context from the request, repository and relevant source files. It edits in scope, checks technical claims and reviews the complete document. When facts are missing, it uses supported wording or reports the gap. Audit-only and read-only requests do not modify files.

The single `SKILL.md` contains the autonomous workflow, technical-writing standards, Unslop catalog and applicable Humanizer checks. It has no `references` directory and does not require the source skills to be installed.

When sub-agents are available, the skill tests the document with fresh readers and fixes identified gaps directly. Without sub-agents, it performs the checks itself and reports that independent reader testing was unavailable. It does not ask the user to conduct routine review steps.

## Invoke

| Host | Command |
|---|---|
| Codex plugin | `$frontier-engineering-plugin:improve-docs <request>` |
| Standalone Codex skill | `$improve-docs <request>` |
| Pi | `/skill:improve-docs <request>` |
| Classic Hermes CLI | `/improve-docs <request>` |
| ZCode custom command | `/improve-docs <request>` |

See [host installation](hosts.md) for setup. In Hermes, install the directory as a standalone plugin rather than a native skill. The Qoder manifest includes the skill, but its runtime visibility policy is unverified.

## Sources and licensing

The combined text adapts [Anthropic's Doc Co-Authoring](https://github.com/anthropics/skills/blob/main/skills/doc-coauthoring/SKILL.md), [Blader's Humanizer](https://github.com/blader/humanizer), and Cursor pstack's [Technical Writing](https://github.com/cursor/plugins/blob/main/pstack/skills/technical-writing/SKILL.md) with its required Unslop catalog for autonomous technical-document work. See [LICENSE](../skills/.manual/improve-docs/LICENSE) for the applicable notices.
