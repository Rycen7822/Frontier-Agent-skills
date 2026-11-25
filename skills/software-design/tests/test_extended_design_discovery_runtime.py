from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "operator" / "design-discovery"
START = RUNTIME / "start-server.sh"
STOP = RUNTIME / "stop-server.sh"
SERVER = RUNTIME / "server.cjs"
NONCE_A = "a" * 64


class DesignDiscoveryRuntimeTests(unittest.TestCase):
    """Task 2 adversarial contract for the local visual companion runtime."""

    def setUp(self) -> None:
        self.processes: list[subprocess.Popen[str]] = []
        self.session_roots: set[Path] = set()
        self.tempdirs: list[tempfile.TemporaryDirectory[str]] = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if process.stdout is not None:
                process.stdout.close()
        for session_root in sorted(self.session_roots, key=lambda path: len(path.parts), reverse=True):
            if session_root.exists() and not session_root.is_symlink():
                shutil.rmtree(session_root)
        for directory in self.tempdirs:
            directory.cleanup()

    def _temporary_directory(self) -> Path:
        directory = tempfile.TemporaryDirectory(prefix="design-discovery-test-")
        self.tempdirs.append(directory)
        return Path(directory.name)

    def _track_process(self, args: list[str], **kwargs: object) -> subprocess.Popen[str]:
        process = subprocess.Popen(args, text=True, **kwargs)
        self.processes.append(process)
        return process

    def _read_startup(self, process: subprocess.Popen[str]) -> dict[str, object]:
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    self.fail(f"server exited before startup: {remaining}")
                if not selector.select(timeout=0.1):
                    continue
                line = process.stdout.readline()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "server-started":
                    return event
        finally:
            selector.close()
        self.fail("server did not emit server-started within 5 seconds")

    def _start_server(
        self,
        *,
        project_dir: Path | None = None,
        extra_args: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> tuple[subprocess.Popen[str], dict[str, object]]:
        args = [str(START)]
        if project_dir is not None:
            args.extend(["--project-dir", str(project_dir)])
        args.extend(extra_args or [])
        environment = os.environ.copy()
        environment.update(extra_env or {})
        process = self._track_process(
            args,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        startup = self._read_startup(process)
        session_root = Path(str(startup["state_dir"])).parent
        self.session_roots.add(session_root)
        return process, startup

    def _stop_server(self, session_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(STOP), str(session_root)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )

    def _sacrificial_process(self) -> subprocess.Popen[str]:
        return self._track_process(["sleep", "30"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _fake_session(
        self,
        process: subprocess.Popen[str],
        *,
        nonce: str = NONCE_A,
    ) -> tuple[Path, Path]:
        parent = self._temporary_directory()
        session_root = parent / "session"
        state_dir = session_root / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "owner.json").write_text(
            json.dumps(
                {
                    "schema": "design-discovery-owner/1",
                    "session_root": str(session_root.resolve()),
                    "session_class": "project-local",
                    "nonce": nonce,
                    "server_pid": process.pid,
                    "server_script": str(SERVER.resolve()),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (state_dir / "server.pid").write_text(f"{process.pid}\n", encoding="utf-8")
        (state_dir / "server.log").write_text("", encoding="utf-8")
        return session_root, state_dir

    @staticmethod
    def _masked_frame(payload: bytes, *, opcode: int = 0x1, final: bool = True) -> bytes:
        first = (0x80 if final else 0) | opcode
        length = len(payload)
        if length < 126:
            header = bytes([first, 0x80 | length])
        elif length < 65536:
            header = bytes([first, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([first, 0x80 | 127]) + struct.pack("!Q", length)
        mask = b"\x01\x02\x03\x04"
        encoded = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return header + mask + encoded

    @staticmethod
    def _read_frame(sock: socket.socket) -> tuple[int | None, bytes]:
        try:
            header = sock.recv(2)
            if len(header) < 2:
                return None, b""
            length = header[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", sock.recv(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", sock.recv(8))[0]
            payload = b""
            while len(payload) < length:
                chunk = sock.recv(length - len(payload))
                if not chunk:
                    break
                payload += chunk
            return header[0] & 0x0F, payload
        except (OSError, socket.timeout):
            return None, b""

    def _websocket(self, startup: dict[str, object]) -> socket.socket:
        sock = socket.create_connection(("127.0.0.1", int(startup["port"])), timeout=2)
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        self.assertIn(b"101 Switching Protocols", response)
        sock.settimeout(2)
        return sock

    def test_start_creates_private_canonical_owner_identity(self) -> None:
        process, startup = self._start_server()
        session_root = Path(str(startup["state_dir"])).parent
        state_dir = session_root / "state"
        content_dir = session_root / "content"
        owner_path = state_dir / "owner.json"
        pid_path = state_dir / "server.pid"
        log_path = state_dir / "server.log"

        self.assertTrue(owner_path.is_file())
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "schema",
                "session_root",
                "session_class",
                "nonce",
                "server_pid",
                "server_script",
            },
            set(owner),
        )
        self.assertEqual(str(session_root.resolve()), owner["session_root"])
        self.assertEqual("temporary", owner["session_class"])
        self.assertRegex(owner["nonce"], r"^[0-9a-f]{64}$")
        self.assertEqual(process.pid, owner["server_pid"])
        self.assertEqual(str(SERVER.resolve()), owner["server_script"])
        self.assertEqual(0o700, stat.S_IMODE(session_root.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(state_dir.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(content_dir.stat().st_mode))
        for path in (owner_path, pid_path, log_path):
            self.assertFalse(path.is_symlink())
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        command_line = (Path("/proc") / str(process.pid) / "cmdline").read_bytes().split(b"\0")
        self.assertIn(str(SERVER.resolve()).encode(), command_line)
        self.assertIn(owner["nonce"].encode(), command_line)

    def test_non_loopback_bind_is_rejected_without_starting_server(self) -> None:
        process = self._track_process(
            [str(START), "--host", "0.0.0.0"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        timed_out = False
        try:
            output, _ = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            output, _ = process.communicate(timeout=2)
        self.assertFalse(timed_out, f"non-loopback server remained live: {output}")
        self.assertNotEqual(0, process.returncode)
        self.assertIn("loopback", output.lower())

    def test_project_session_parent_symlink_is_rejected_without_escape(self) -> None:
        project = self._temporary_directory()
        external = self._temporary_directory()
        (project / ".agent-design-discovery").symlink_to(external, target_is_directory=True)
        process = self._track_process(
            [str(START), "--project-dir", str(project)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        timed_out = False
        try:
            output, _ = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            output, _ = process.communicate(timeout=2)
        self.assertFalse(timed_out, f"symlinked project state escaped and started: {output}")
        self.assertNotEqual(0, process.returncode)
        self.assertEqual([], list(external.iterdir()))

    def test_stop_rejects_symlinked_owner_pid_and_log_without_signaling(self) -> None:
        for field in ("owner.json", "server.pid", "server.log"):
            with self.subTest(field=field):
                process = self._sacrificial_process()
                session_root, state_dir = self._fake_session(process)
                original = state_dir / field
                external = self._temporary_directory() / field
                external.write_bytes(original.read_bytes())
                original.unlink()
                original.symlink_to(external)

                completed = self._stop_server(session_root)
                self.assertNotEqual(0, completed.returncode)
                self.assertIsNone(process.poll(), f"symlinked {field} caused a signal")

    def test_stop_rejects_missing_malformed_stale_and_wrong_command_identity(self) -> None:
        cases = ("missing-owner", "missing-nonce", "malformed-pid", "stale-pid", "wrong-command")
        for case in cases:
            with self.subTest(case=case):
                process = self._sacrificial_process()
                session_root, state_dir = self._fake_session(process)
                if case == "missing-owner":
                    (state_dir / "owner.json").unlink()
                elif case == "missing-nonce":
                    owner = json.loads((state_dir / "owner.json").read_text(encoding="utf-8"))
                    owner.pop("nonce")
                    (state_dir / "owner.json").write_text(json.dumps(owner) + "\n", encoding="utf-8")
                elif case == "malformed-pid":
                    (state_dir / "server.pid").write_text("not-a-pid\n", encoding="utf-8")
                elif case == "stale-pid":
                    (state_dir / "server.pid").write_text("2147483647\n", encoding="utf-8")
                    owner = json.loads((state_dir / "owner.json").read_text(encoding="utf-8"))
                    owner["server_pid"] = 2147483647
                    (state_dir / "owner.json").write_text(json.dumps(owner) + "\n", encoding="utf-8")

                completed = self._stop_server(session_root)
                self.assertNotEqual(0, completed.returncode)
                self.assertIsNone(process.poll(), f"{case} signaled an unrelated process")
                self.assertTrue(session_root.exists())

    def test_session_symlink_and_project_local_prefix_confusion_are_safe(self) -> None:
        process = self._sacrificial_process()
        session_root, _ = self._fake_session(process)
        alias = self._temporary_directory() / "session-alias"
        alias.symlink_to(session_root, target_is_directory=True)
        alias_result = self._stop_server(alias)
        self.assertNotEqual(0, alias_result.returncode)
        self.assertIsNone(process.poll(), "session symlink caused a signal")
        self.assertTrue(session_root.is_dir())

        prefix_root = Path(tempfile.mkdtemp(prefix="agent-design-discovery-", dir="/tmp"))
        self.session_roots.add(prefix_root)
        prefix_state = prefix_root / "state"
        (prefix_root / "content").mkdir()
        prefix_state.mkdir()
        prefix_nonce = "c" * 64
        environment = os.environ.copy()
        environment.update(
            {
                "BRAINSTORM_DIR": str(prefix_root),
                "BRAINSTORM_HOST": "127.0.0.1",
                "BRAINSTORM_URL_HOST": "localhost",
                "BRAINSTORM_OWNER_PID": str(os.getpid()),
            }
        )
        prefix_process = self._track_process(
            ["node", str(SERVER), "--session-nonce", prefix_nonce],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        self._read_startup(prefix_process)
        owner = {
            "schema": "design-discovery-owner/1",
            "session_root": str(prefix_root.resolve()),
            "session_class": "project-local",
            "nonce": prefix_nonce,
            "server_pid": prefix_process.pid,
            "server_script": str(SERVER.resolve()),
        }
        (prefix_state / "owner.json").write_text(json.dumps(owner) + "\n", encoding="utf-8")
        (prefix_state / "server.pid").write_text(f"{prefix_process.pid}\n", encoding="utf-8")
        (prefix_state / "server.log").write_text("", encoding="utf-8")
        prefix_result = self._stop_server(prefix_root)
        self.assertEqual(0, prefix_result.returncode, prefix_result.stdout + prefix_result.stderr)
        prefix_process.wait(timeout=2)
        self.assertTrue(prefix_root.is_dir(), "temporary-looking prefix was recursively deleted")

    def test_stop_rejects_mismatched_pid_nonce_and_session_without_signaling(self) -> None:
        process, startup = self._start_server()
        session_root = Path(str(startup["state_dir"])).parent
        state_dir = session_root / "state"
        owner_path = state_dir / "owner.json"

        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        original_nonce = owner["nonce"]
        owner["nonce"] = "b" * 64
        owner_path.write_text(json.dumps(owner) + "\n", encoding="utf-8")
        (state_dir / "server.log").touch()
        nonce_result = self._stop_server(session_root)
        self.assertNotEqual(0, nonce_result.returncode)
        self.assertIsNone(process.poll(), "forged nonce signaled the server")

        owner["nonce"] = original_nonce
        owner["session_root"] = str(session_root.parent.resolve())
        owner_path.write_text(json.dumps(owner) + "\n", encoding="utf-8")
        escape_result = self._stop_server(session_root)
        self.assertNotEqual(0, escape_result.returncode)
        self.assertIsNone(process.poll(), "escaping owner root signaled the server")

        other_process, other_startup = self._start_server()
        other_root = Path(str(other_startup["state_dir"])).parent
        other_state = other_root / "state"
        copied_parent = self._temporary_directory()
        copied_root = copied_parent / "copied-session"
        shutil.copytree(other_root, copied_root)
        self.session_roots.add(copied_root)
        session_result = self._stop_server(copied_root)
        self.assertNotEqual(0, session_result.returncode)
        self.assertIsNone(other_process.poll(), "wrong session root signaled the server")

        sacrificial = self._sacrificial_process()
        (other_state / "server.pid").write_text(f"{sacrificial.pid}\n", encoding="utf-8")
        mismatch_result = self._stop_server(other_root)
        self.assertNotEqual(0, mismatch_result.returncode)
        self.assertIsNone(other_process.poll(), "mismatched PID signaled the real server")
        self.assertIsNone(sacrificial.poll(), "mismatched PID signaled the substituted process")

    def test_valid_stop_removes_exact_temporary_root_and_preserves_project_root(self) -> None:
        temporary_process, temporary_startup = self._start_server()
        temporary_root = Path(str(temporary_startup["state_dir"])).parent
        temporary_result = self._stop_server(temporary_root)
        self.assertEqual(0, temporary_result.returncode, temporary_result.stdout + temporary_result.stderr)
        temporary_process.wait(timeout=2)
        self.assertFalse(temporary_root.exists())
        self.session_roots.discard(temporary_root)

        project = self._temporary_directory()
        project_process, project_startup = self._start_server(project_dir=project)
        project_root = Path(str(project_startup["state_dir"])).parent
        project_result = self._stop_server(project_root)
        self.assertEqual(0, project_result.returncode, project_result.stdout + project_result.stderr)
        project_process.wait(timeout=2)
        self.assertTrue(project_root.is_dir())
        self.assertTrue((project_root / "content").is_dir())

    def test_oversized_single_and_fragmented_messages_close_1009(self) -> None:
        for case in ("single", "fragmented"):
            with self.subTest(case=case):
                _, startup = self._start_server()
                sock = self._websocket(startup)
                try:
                    if case == "single":
                        sock.sendall(self._masked_frame(b"x" * 65537))
                    elif case == "fragmented":
                        sock.sendall(self._masked_frame(b"x" * 40000, final=False))
                        sock.sendall(self._masked_frame(b"y" * 30000, opcode=0x0))
                    opcode, payload = self._read_frame(sock)
                    self.assertEqual(0x8, opcode)
                    self.assertGreaterEqual(len(payload), 2)
                    self.assertEqual(1009, struct.unpack("!H", payload[:2])[0])
                finally:
                    sock.close()

    def test_connection_buffer_bound_is_enforced_before_concatenation(self) -> None:
        probe = (
            "const runtime = require(process.argv[1]);"
            "try { runtime.appendConnectionChunk(Buffer.alloc(0), Buffer.alloc(131073));"
            "process.exit(2); } catch (error) {"
            "console.log(JSON.stringify({code: error.closeCode, limit: runtime.LIMITS.connectionBuffer})); }"
        )
        completed = subprocess.run(
            ["node", "-e", probe, str(SERVER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual({"code": 1009, "limit": 131072}, json.loads(completed.stdout))

    def test_idle_shutdown_closes_connections_and_leaves_no_process(self) -> None:
        process, startup = self._start_server(
            extra_env={
                "BRAINSTORM_IDLE_TIMEOUT_MS": "100",
                "BRAINSTORM_LIFECYCLE_INTERVAL_MS": "20",
            }
        )
        sock = self._websocket(startup)
        timed_out = False
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            process.wait(timeout=2)
        try:
            self.assertFalse(timed_out, "idle shutdown left the server process running")
            self.assertEqual(b"", sock.recv(1))
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
