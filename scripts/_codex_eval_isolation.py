"""Fail-closed process and filesystem isolation for model-evolution Codex calls."""

from __future__ import annotations

from contextlib import contextmanager
import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlsplit


ISOLATED_CODEX_HOME = "/run/frontier-codex-home"
ISOLATED_MODEL_CATALOG = "/run/frontier-model-catalog/models_cache.json"
ISOLATED_CODEX_BIN = "/run/frontier-codex-bin"
ISOLATED_HOME = "/run/frontier-home"
ISOLATED_OUTPUT = "/tmp/frontier-output"
ISOLATED_WORKSPACE = "/tmp/frontier-workspace"
LEGACY_ISOLATED_SANDBOX_POLICY_IDS = {
    "read-only": "frontier-read-only-v1",
    "workspace-write": "frontier-isolated-workspace-write-v1",
}
ISOLATED_SANDBOX_POLICY_IDS = {
    "read-only": "frontier-read-only-credential-isolated-v1",
    "workspace-write": "frontier-workspace-write-credential-isolated-v1",
}
ISOLATED_PERMISSION_PROFILES = {
    "read-only": "frontier-read-only-credential-isolated",
    "workspace-write": "frontier-workspace-write-credential-isolated",
}
PROTECTED_WORKSPACE_ROOTS = (".agents", ".git")


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
        profile = """default_permissions = "frontier-read-only-credential-isolated"

[permissions.frontier-read-only-credential-isolated]
extends = ":read-only"

[permissions.frontier-read-only-credential-isolated.filesystem]
"/run/frontier-codex-home" = "deny"

[permissions.frontier-workspace-write-credential-isolated]
extends = ":workspace"

[permissions.frontier-workspace-write-credential-isolated.filesystem]
"/run/frontier-codex-home" = "deny"
"""
        config = home / "config.toml"
        config.write_text(profile, encoding="utf-8")
        config.chmod(0o600)
        yield home


def command_permission_argv(sandbox: str) -> list[str]:
    """Select the least-privilege command profile bound to one Host sandbox."""
    try:
        profile = ISOLATED_PERMISSION_PROFILES[sandbox]
    except KeyError as exc:
        raise IsolationError("model-evolution isolation sandbox is unsupported") from exc
    return ["--config", "default_permissions=" + json.dumps(profile)]


def proxy_environment_projection(
    env_allowlist: list[str], environment: dict[str, str]
) -> list[dict[str, Any]]:
    """Return credential-shape booleans without retaining environment values."""
    rows = []
    for name in env_allowlist:
        value = environment.get(name)
        parsed = urlsplit(value) if value is not None else None
        userinfo = bool(parsed and (parsed.username is not None or parsed.password is not None))
        query_credential = bool(
            parsed
            and any(
                token in key.lower()
                for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
                for token in ("token", "secret", "password", "key", "authorization")
            )
        )
        rows.append(
            {
                "name": name,
                "present": value is not None,
                "url_userinfo": userinfo,
                "credential_like_component": userinfo
                or query_credential
                or any(token in name.lower() for token in ("token", "secret", "password", "key", "authorization")),
            }
        )
    return rows


def credential_reachability_check(
    *,
    isolation_tool: Path,
    sandbox: str,
    source_root: Path,
    product_root: Path,
    codex: Path,
    code_mode_host: Path,
    workspace: Path,
    plugin_probe: Path,
    model_catalog_snapshot: Path,
    model_catalog_sha256: str,
    environment: dict[str, str],
    env_allowlist: list[str],
) -> dict[str, Any]:
    """Prove parent auth access and command-level credential unreachability."""
    shared_memory = Path("/dev/shm")
    if shared_memory.is_symlink() or not shared_memory.is_dir():
        raise IsolationError("credential proof temporary parent is unavailable")
    canary = b'{"auth_mode":"synthetic-canary","token":"D45-NONSECRET-CANARY"}\n'
    canary_digest = sha256(canary).hexdigest()
    with (
        tempfile.TemporaryDirectory(prefix="frontier-auth-proof-", dir=shared_memory) as auth_dir,
        tempfile.TemporaryDirectory(prefix="frontier-output-proof-", dir=shared_memory) as output_dir,
        request_codex_home(isolation_tool) as codex_home,
    ):
        assert codex_home is not None
        auth = Path(auth_dir) / "auth.json"
        auth.write_bytes(canary)
        auth.chmod(0o600)
        output = Path(output_dir)
        last_message = output / "last-message.txt"
        dummy_argv = [
            str(codex),
            *command_permission_argv(sandbox),
            "exec",
            "--json",
            "--strict-config",
            "--color",
            "never",
            "--model",
            "gpt-5.6-sol",
            "--cd",
            str(workspace),
            "--config",
            'model_reasoning_effort="xhigh"',
            "--config",
            "model_catalog_json=" + json.dumps(str(model_catalog_snapshot)),
            "--output-last-message",
            str(last_message),
            "-",
        ]
        outer = isolated_child_argv(
            isolation_tool=isolation_tool,
            sandbox=sandbox,
            source_root=source_root,
            codex=codex,
            code_mode_host=code_mode_host,
            argv=dummy_argv,
            workspace=workspace,
            codex_home=codex_home,
            model_catalog_snapshot=model_catalog_snapshot,
            model_catalog_sha256=model_catalog_sha256,
            auth_input=auth,
        )
        separator = outer.index("--")
        fixture = workspace / "d45-fixture.canary"
        fixture.write_text("fixture-safe\n", encoding="utf-8")
        targets = {
            "isolated_auth": {
                "path": f"{ISOLATED_CODEX_HOME}/auth.json",
                "digest": canary_digest,
            },
            "isolated_codex_home": {"path": ISOLATED_CODEX_HOME},
            "global_user_home": {"path": str(Path.home().resolve(strict=True))},
            "controller_root": {"path": str(source_root)},
            "product_root": {"path": str(product_root)},
            "fixture": {
                "path": f"{ISOLATED_WORKSPACE}/{fixture.name}",
                "digest": sha256(fixture.read_bytes()).hexdigest(),
            },
            "plugin": {
                "path": f"{ISOLATED_WORKSPACE}/{plugin_probe.relative_to(workspace).as_posix()}",
                "digest": sha256(plugin_probe.read_bytes()).hexdigest(),
            },
            "runtime": {
                "path": f"{ISOLATED_CODEX_BIN}/{codex.name}",
                "digest": sha256(codex.read_bytes()).hexdigest(),
            },
            "catalog": {
                "path": ISOLATED_MODEL_CATALOG,
                "digest": sha256(model_catalog_snapshot.read_bytes()).hexdigest(),
            },
        }
        probe = """import errno,hashlib,json,os
from pathlib import Path
targets=json.loads(os.environ['FRONTIER_CREDENTIAL_PROOF_TARGETS']); out={}
for name,spec in targets.items():
 p=Path(spec['path']); row={}
 try: p.stat(); row['stat']=True; row['stat_errno']='none'
 except OSError as exc: row['stat']=False; row['stat_errno']=errno.errorcode.get(exc.errno,'other')
 try: list(p.iterdir()); row['list']=True; row['list_errno']='none'
 except OSError as exc: row['list']=False; row['list_errno']=errno.errorcode.get(exc.errno,'other')
 try:
  content=p.read_bytes(); row['read']=True; row['read_errno']='none'; row['digest_match']=hashlib.sha256(content).hexdigest()==spec.get('digest') if spec.get('digest') else None
 except OSError as exc: row['read']=False; row['read_errno']=errno.errorcode.get(exc.errno,'other'); row['digest_match']=None
 out[name]=row
print(json.dumps(out,sort_keys=True,separators=(',',':')))
"""
        child_env = dict(environment)
        child_env["FRONTIER_CREDENTIAL_PROOF_TARGETS"] = json.dumps(
            targets, sort_keys=True, separators=(",", ":")
        )
        parent = subprocess.run(
            outer[: separator + 1] + ["python3", "-c", probe],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        command = subprocess.run(
            outer[: separator + 1]
            + [
                f"{ISOLATED_CODEX_BIN}/{codex.name}",
                "sandbox",
                *command_permission_argv(sandbox),
                "--",
                "python3",
                "-c",
                probe,
            ],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        try:
            parent_result = json.loads(parent.stdout)
            command_result = json.loads(command.stdout)
        except json.JSONDecodeError as exc:
            raise IsolationError("credential proof output is invalid") from exc
        required_command_reads = {"fixture", "plugin", "runtime", "catalog"}
        if (
            parent.returncode != 0
            or command.returncode != 0
            or parent_result["isolated_auth"] != {
                "digest_match": True,
                "list": False,
                "list_errno": "ENOTDIR",
                "read": True,
                "read_errno": "none",
                "stat": True,
                "stat_errno": "none",
            }
            or command_result["isolated_auth"]["stat"]
            or command_result["isolated_auth"]["list"]
            or command_result["isolated_auth"]["read"]
            or command_result["isolated_codex_home"]["list"]
            or command_result["isolated_codex_home"]["read"]
            or command_result["controller_root"]["stat"]
            or command_result["product_root"]["stat"]
            or any(
                not command_result[name]["read"]
                or command_result[name]["digest_match"] is not True
                for name in required_command_reads
            )
        ):
            raise IsolationError("credential reachability proof did not close")
    environment_shape = proxy_environment_projection(env_allowlist, environment)
    if any(row["credential_like_component"] for row in environment_shape):
        raise IsolationError("credential-bearing Host environment is not isolated")
    return {
        "schema_version": "model-evolution-credential-reachability/1",
        "provider_calls": 0,
        "credentials_exposed": False,
        "parent_auth_readable": True,
        "command_auth_stat": False,
        "command_auth_list": False,
        "command_auth_read": False,
        "command_fixture_readable": True,
        "command_plugin_readable": True,
        "command_runtime_readable": True,
        "command_catalog_readable": True,
        "controller_root_accessible": False,
        "product_root_accessible": False,
        "environment": environment_shape,
    }


def isolated_child_argv(
    *,
    isolation_tool: Path,
    sandbox: str,
    source_root: Path,
    codex: Path,
    code_mode_host: Path,
    argv: list[str],
    workspace: Path,
    codex_home: Path,
    model_catalog_snapshot: Path | None = None,
    model_catalog_sha256: str | None = None,
    auth_input: Path | None = None,
) -> list[str]:
    if sandbox not in ISOLATED_SANDBOX_POLICY_IDS:
        raise IsolationError("model-evolution isolation sandbox is unsupported")
    if source_root.parent.name != ".worktrees":
        raise IsolationError(
            "source worktree is outside the in-repository worktree root"
        )
    if (
        code_mode_host.name != "codex-code-mode-host"
        or code_mode_host.parent != codex.parent
    ):
        raise IsolationError("Codex code-mode Host is not the bound runtime sibling")
    user_home = Path.home().resolve(strict=True)
    global_codex_home = user_home / ".codex"
    auth = auth_input if auth_input is not None else global_codex_home / "auth.json"
    model_cache = global_codex_home / "models_cache.json"
    for path, label in ((auth, "Codex auth"),):
        if path.is_symlink() or not path.is_file():
            raise IsolationError(f"{label} input is unavailable")
    if model_catalog_snapshot is not None:
        if (
            model_catalog_snapshot.is_symlink()
            or not model_catalog_snapshot.is_file()
            or not isinstance(model_catalog_sha256, str)
            or "sha256:" + sha256(model_catalog_snapshot.read_bytes()).hexdigest()
            != model_catalog_sha256
        ):
            raise IsolationError("bound model catalog snapshot is invalid")
    elif model_cache.is_symlink() or not model_cache.is_file():
        raise IsolationError("Codex model cache input is unavailable")

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
    catalog_options = [
        index
        for index, value in enumerate(rewritten)
        if value.startswith("model_catalog_json=")
    ]
    if model_catalog_snapshot is not None:
        if len(catalog_options) != 1:
            raise IsolationError("child argv must bind one model catalog snapshot")
        option = catalog_options[0]
        try:
            bound_catalog = json.loads(rewritten[option].split("=", 1)[1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise IsolationError("child model catalog binding is invalid") from exc
        if (
            not isinstance(bound_catalog, str)
            or Path(bound_catalog).resolve(strict=False)
            != model_catalog_snapshot.resolve(strict=True)
        ):
            raise IsolationError("child model catalog differs from the Host binding")
        rewritten[option] = "model_catalog_json=" + json.dumps(
            ISOLATED_MODEL_CATALOG,
            ensure_ascii=False,
        )
    elif catalog_options:
        raise IsolationError("legacy child unexpectedly binds a model catalog")

    workspace_mount = "--ro-bind" if sandbox == "read-only" else "--bind"
    workspace_mounts = [workspace_mount, str(workspace), ISOLATED_WORKSPACE]
    if sandbox == "workspace-write":
        for name in PROTECTED_WORKSPACE_ROOTS:
            protected = workspace / name
            if not protected.exists():
                continue
            if protected.is_symlink() or not protected.is_dir():
                raise IsolationError(f"workspace infrastructure is invalid: {name}")
            workspace_mounts.extend([
                "--ro-bind",
                str(protected),
                f"{ISOLATED_WORKSPACE}/{name}",
            ])

    return [
        str(isolation_tool),
        "--ro-bind", "/", "/",
        "--tmpfs", "/tmp",
        "--dir", ISOLATED_WORKSPACE,
        *workspace_mounts,
        "--dir", ISOLATED_OUTPUT,
        "--bind", str(output_dir), ISOLATED_OUTPUT,
        "--tmpfs", "/run",
        "--dir", ISOLATED_CODEX_BIN,
        "--ro-bind", str(codex), rewritten[0],
        "--ro-bind", str(code_mode_host), f"{ISOLATED_CODEX_BIN}/codex-code-mode-host",
        "--dir", ISOLATED_HOME,
        "--dir", ISOLATED_CODEX_HOME,
        "--bind", str(codex_home), ISOLATED_CODEX_HOME,
        "--ro-bind", str(auth), f"{ISOLATED_CODEX_HOME}/auth.json",
        *(
            [
                "--dir", "/run/frontier-model-catalog",
                "--ro-bind", str(model_catalog_snapshot), ISOLATED_MODEL_CATALOG,
            ]
            if model_catalog_snapshot is not None
            else [
                "--ro-bind", str(model_cache), f"{ISOLATED_CODEX_HOME}/models_cache.json",
            ]
        ),
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
