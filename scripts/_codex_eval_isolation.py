"""Fail-closed process and filesystem isolation for model-evolution Codex calls."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import Iterator


ISOLATED_CODEX_HOME = "/run/frontier-codex-home"
ISOLATED_CODEX_BIN = "/run/frontier-codex-bin"
ISOLATED_HOME = "/run/frontier-home"
ISOLATED_OUTPUT = "/tmp/frontier-output"
ISOLATED_WORKSPACE = "/tmp/frontier-workspace"


class IsolationError(ValueError):
    """A required model-evolution isolation boundary is unavailable."""


@contextmanager
def request_codex_home(isolation_tool: Path | None) -> Iterator[Path | None]:
    if isolation_tool is None:
        yield None
        return
    shared_memory = Path("/dev/shm")
    if shared_memory.is_symlink() or not shared_memory.is_dir():
        raise IsolationError("private Codex home parent is unavailable")
    with tempfile.TemporaryDirectory(
        prefix="frontier-codex-home-",
        dir=shared_memory,
    ) as temp_dir:
        home = Path(temp_dir)
        home.chmod(0o700)
        yield home


def isolated_child_argv(
    *,
    isolation_tool: Path,
    sandbox: str,
    source_root: Path,
    codex: Path,
    argv: list[str],
    workspace: Path,
    codex_home: Path,
) -> list[str]:
    if sandbox != "read-only":
        raise IsolationError("model-evolution isolation requires read-only sandbox")
    if source_root.parent.name != ".worktrees":
        raise IsolationError(
            "source worktree is outside the in-repository worktree root"
        )
    user_home = Path.home().resolve(strict=True)
    global_codex_home = user_home / ".codex"
    auth = global_codex_home / "auth.json"
    model_cache = global_codex_home / "models_cache.json"
    for path, label in ((auth, "Codex auth"), (model_cache, "Codex model cache")):
        if path.is_symlink() or not path.is_file():
            raise IsolationError(f"{label} input is unavailable")

    rewritten = list(argv)
    if Path(rewritten[0]).resolve(strict=True) != codex:
        raise IsolationError("Codex child executable differs from the Host binding")
    rewritten[0] = f"{ISOLATED_CODEX_BIN}/{codex.name}"

    output_position = rewritten.index("--output-last-message") + 1
    output_path = Path(rewritten[output_position]).resolve(strict=False)
    output_dir = output_path.parent.resolve(strict=True)
    rewritten[output_position] = f"{ISOLATED_OUTPUT}/{output_path.name}"
    if "--output-schema" in rewritten:
        schema_position = rewritten.index("--output-schema") + 1
        schema_path = Path(rewritten[schema_position]).resolve(strict=True)
        if schema_path.parent != output_dir or schema_path.is_symlink():
            raise IsolationError("Codex output schema is outside the request output root")
        rewritten[schema_position] = f"{ISOLATED_OUTPUT}/{schema_path.name}"
    if "--cd" in rewritten:
        cwd_position = rewritten.index("--cd") + 1
        if Path(rewritten[cwd_position]).resolve(strict=True) != workspace:
            raise IsolationError(
                "Codex child workspace differs from the isolated workspace"
            )
        rewritten[cwd_position] = ISOLATED_WORKSPACE

    return [
        str(isolation_tool),
        "--ro-bind", "/", "/",
        "--tmpfs", "/tmp",
        "--dir", ISOLATED_WORKSPACE,
        "--ro-bind", str(workspace), ISOLATED_WORKSPACE,
        "--dir", ISOLATED_OUTPUT,
        "--bind", str(output_dir), ISOLATED_OUTPUT,
        "--tmpfs", "/run",
        "--dir", ISOLATED_CODEX_BIN,
        "--ro-bind", str(codex), rewritten[0],
        "--dir", ISOLATED_HOME,
        "--dir", ISOLATED_CODEX_HOME,
        "--bind", str(codex_home), ISOLATED_CODEX_HOME,
        "--ro-bind", str(auth), f"{ISOLATED_CODEX_HOME}/auth.json",
        "--ro-bind", str(model_cache), f"{ISOLATED_CODEX_HOME}/models_cache.json",
        "--tmpfs", str(user_home),
        "--dev", "/dev",
        "--proc", "/proc",
        "--unshare-pid",
        "--as-pid-1",
        "--die-with-parent",
        "--setenv", "CODEX_HOME", ISOLATED_CODEX_HOME,
        "--setenv", "HOME", ISOLATED_HOME,
        "--setenv", "PATH",
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--chdir", ISOLATED_WORKSPACE,
        "--",
        *rewritten,
    ]
