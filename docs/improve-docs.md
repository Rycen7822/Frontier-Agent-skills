# Improve Docs

[`improve-docs`](../improve-docs/SKILL.md) co-authors or improves documentation in a named scope. It requires explicit user invocation.

Example requests:

```text
Improve docs/install.md for a new contributor.
Review this RFC without editing it.
```

The single `SKILL.md` contains the document workflow, technical-writing standards, Unslop catalog and Humanizer checks. It has no `references` directory and does not require the source skills to be installed.

The workflow can gather context, refine sections and test the result with a fresh reader. Users can skip stages or work freeform. An audit-only request stays read-only. Reader testing checks interpretation, not factual correctness. The user retains final review.

## Invoke

| Host | Command |
|---|---|
| Codex plugin | `$frontier-engineering-plugin:improve-docs <request>` |
| Standalone Codex skill | `$improve-docs <request>` |
| Pi | `/skill:improve-docs <request>` |
| Classic Hermes CLI | `/improve-docs <request>` |

See [host installation](hosts.md) for setup. In Hermes, install the directory as a standalone plugin rather than a native skill. The Qoder manifest includes the skill, but its runtime visibility policy is unverified.

## Sources and licensing

The combined text preserves rules from [Anthropic's Doc Co-Authoring](https://github.com/anthropics/skills/blob/main/skills/doc-coauthoring/SKILL.md), [Blader's Humanizer](https://github.com/blader/humanizer), and Cursor pstack's [Technical Writing](https://github.com/cursor/plugins/blob/main/pstack/skills/technical-writing/SKILL.md) with its required Unslop catalog. See [LICENSE](../improve-docs/LICENSE) for the applicable notices.
