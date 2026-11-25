# Clean Code Comments

[`clean-code-comments`](../skills/.manual/clean-code-comments/SKILL.md) audits or cleans comments in a named scope. It requires explicit user invocation. Other skills do not route to it automatically.

Example requests:

```text
Audit comments in src/parser without edits.
Clean up comments in this diff and ratchet the linter.
```

The skill distinguishes repeated code narration, excuses for implementation debt, stale comments and decision records. It preserves license headers, required tooling directives, public API contracts and proven external constraints. An audit stays read-only. A cleanup can move decisions into ADRs, flag root-cause fixes and add a scoped lint baseline.

## Invoke

| Host | Command |
|---|---|
| Codex plugin | `$frontier-engineering-plugin:clean-code-comments <request>` |
| Standalone Codex skill | `$clean-code-comments <request>` |
| Pi | `/skill:clean-code-comments <request>` |
| Classic Hermes CLI | `/clean-code-comments <request>` |
| ZCode custom command | `/clean-code-comments <request>` |

See [host installation](hosts.md) before invoking the skill. In Hermes, install it as a standalone plugin rather than a native skill. The Qoder manifest includes the directory, but Qoder's runtime visibility policy is unverified.

Installation does not require changes to global instructions. After an authorized update, reload the host catalog or start a fresh session.
