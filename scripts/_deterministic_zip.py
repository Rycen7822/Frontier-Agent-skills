"""Deterministic ZIP encoding shared by source and marketplace builders."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile


ZipMember = tuple[str, Path, int]
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _validate_members(members: Sequence[ZipMember]) -> None:
    names: set[str] = set()
    for name, _, mode in members:
        member = PurePosixPath(name)
        if (
            not name
            or name in names
            or member.is_absolute()
            or ".." in member.parts
            or "\\" in name
            or name.endswith("/")
        ):
            raise ValueError(f"unsafe or duplicate ZIP member: {name}")
        if mode not in (0o644, 0o755):
            raise ValueError(f"unsupported ZIP member mode: {name}")
        names.add(name)


def _regular_bytes(path: Path, expected_mode: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        mode = 0o755 if info.st_mode & stat.S_IXUSR else 0o644
        if not stat.S_ISREG(info.st_mode) or mode != expected_mode:
            raise ValueError(f"ZIP member bytes or mode changed: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def write_deterministic_zip(path: Path, members: Sequence[ZipMember]) -> None:
    _validate_members(members)
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name, source, mode in members:
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.flag_bits |= 0x800
            archive.writestr(
                info,
                _regular_bytes(source, mode),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def verify_deterministic_zip(path: Path, members: Sequence[ZipMember]) -> None:
    _validate_members(members)
    with zipfile.ZipFile(path, mode="r") as archive:
        if archive.namelist() != [name for name, _, _ in members]:
            raise ValueError("ZIP member order or identity differs from its inventory")
        for (name, source, mode), info in zip(members, archive.infolist(), strict=True):
            archived_mode = (info.external_attr >> 16) & 0o777
            if (
                info.filename != name
                or info.is_dir()
                or info.date_time != ZIP_TIMESTAMP
                or info.compress_type != zipfile.ZIP_DEFLATED
                or info.create_system != 3
                or archived_mode != mode
                or archive.read(info) != _regular_bytes(source, mode)
            ):
                raise ValueError(f"ZIP member differs from its inventory: {name}")
