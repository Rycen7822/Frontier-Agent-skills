# Source and local modifications

The visual design companion derives from the MIT-licensed `skills/brainstorming` package in <https://github.com/obra/superpowers>. The bundled terms are preserved in [design-discovery-upstream-license.txt](design-discovery-upstream-license.txt).

This repository keeps one active runtime copy under `software-quality-workflows/operator/design-discovery/`. The local runtime is restricted to loopback, binds shutdown to a nonce-backed owner marker, limits frame and connection sizes, runs in a host-tracked foreground lifecycle, and performs bounded validated shutdown. No runtime copy remains under a separate Brainstorming skill.
