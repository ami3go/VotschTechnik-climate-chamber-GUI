"""W02 disconnected release archive verifier: freeze as a separately trusted EXE.

This executable never launches the GUI, installs dependencies, operates hardware
or trusts publisher keys obtained from the release archive.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import stat
import zipfile

from scripts.w02_release import validate_entries, verify
from scripts.windows_manifest import unsafe_reparse

MAX_FILES = 200_000
MAX_TOTAL_BYTES = 10 * 1024 ** 3
MAX_SINGLE_FILE = 2 * 1024 ** 3
MAX_COMPRESSION_RATIO = 2_000


def archive_entries(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    """Validate all members before extracting a single byte.

    W01 Compress-Archive produces one top-level bundle folder. A directory
    with a different name is not trusted; its content is still signature-
    checked before being staged under the operator-chosen installation path.
    """
    infos = archive.infolist()
    if not infos or len(infos) > MAX_FILES:
        raise ValueError("Empty or oversized release archive")
    regular: dict[str, str] = {}
    entries: list[tuple[zipfile.ZipInfo, str]] = []
    roots: set[str] = set()
    dirs: dict[str, str] = {}
    total = 0
    for info in infos:
        name = info.filename
        if not name or "\\" in name or name.startswith("/") or ":" in name:
            raise ValueError("Unsafe archive member path")
        is_dir = info.is_dir()
        segments = name[:-1].split("/") if is_dir else name.split("/")
        if any(segment in {"", ".", ".."} for segment in segments):
            raise ValueError("Unsafe archive member path")
        if len(segments) < 2:
            if is_dir and len(segments) == 1:
                roots.add(segments[0])
                continue
            raise ValueError("Archive must contain one top-level bundle directory")
        roots.add(segments[0])
        # Validate the top-level folder and every path segment using the
        # same NTFS restrictions applied to signed inventory entries.
        validate_entries({"/".join(segments): "0" * 64})
        relative = "/".join(segments[1:])
        # ZIP names include the two signature sidecars; signed *inventory* does not.
        validate_entries({"_archive_root_/" + relative: "0" * 64})
        folded = relative.casefold()
        for i in range(1, len(segments)):
            directory = "/".join(segments[1:i])
            if not directory:
                continue
            previous = dirs.setdefault(directory.casefold(), directory)
            if previous != directory:
                raise ValueError("Case-insensitive directory alias in archive")
        if is_dir:
            previous = dirs.setdefault(folded, relative)
            if previous != relative:
                raise ValueError("Case-insensitive directory collision")
        else:
            if folded in regular:
                raise ValueError("Duplicate/case-insensitive archive path collision")
            regular[folded] = "0" * 64
        if info.flag_bits & 1:
            raise ValueError("Encrypted release ZIP is not supported")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError("Archive contains symbolic link")
        if not is_dir:
            if info.file_size > MAX_SINGLE_FILE or info.file_size < 0:
                raise ValueError("Archive file exceeds limit")
            if info.compress_size == 0 and info.file_size:
                raise ValueError("Archive compression size invalid")
            if info.file_size > max(1, info.compress_size) * MAX_COMPRESSION_RATIO:
                raise ValueError("Archive compression ratio is unsafe")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Archive extracted size exceeds limit")
        entries.append((info, relative))
    if len(roots) != 1:
        raise ValueError("Archive contains multiple top-level directories")
    validate_entries({name: digest for name, digest in regular.items()
                      if name not in {"w02-release.json", "w02-release.sig"}})
    if set(regular) & set(dirs):
        raise ValueError("Archive file/directory collision")
    if "w02-release.json" not in regular or "w02-release.sig" not in regular:
        raise ValueError("Archive is not a signed W02 release")
    return entries


def verify_archive(archive_path: Path, destination: Path, trusted_key: Path,
                   *, minimum_version: str) -> dict:
    """Quarantine-extract, verify signature and every file, then stage atomically.

    A trusted operator must select a protected local staging destination;
    independently distribute the frozen verifier, trusted publisher key and
    minimum accepted version before executing this function.
    """
    if not minimum_version:
        raise ValueError("Externally pinned minimum version is required")
    archive_path = archive_path.resolve(strict=True)
    trusted_key = trusted_key.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists():
        raise ValueError("Installation destination already exists")
    if not destination.parent.is_dir() or unsafe_reparse(destination.parent):
        raise ValueError("Installation parent must be a safe existing directory")
    if archive_path == destination or archive_path in destination.parents:
        raise ValueError("Archive and install paths must not overlap")
    if trusted_key == archive_path:
        raise ValueError("Publisher key cannot be the release archive")
    pending = destination.with_name(destination.name + ".pending")
    if pending.exists():
        raise ValueError("Interrupted install staging detected: inspect manually")
    with zipfile.ZipFile(archive_path, "r") as release_zip:
        members = archive_entries(release_zip)
        pending.mkdir()
        try:
            for info, relative in members:
                path = pending.joinpath(*relative.split("/"))
                if info.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # "xb" prevents duplicate paths silently overwriting files.
                    with release_zip.open(info, "r") as source, path.open("xb") as target:
                        remaining = info.file_size
                        while remaining:
                            chunk = source.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ValueError("Truncated archive member")
                            target.write(chunk)
                            remaining -= len(chunk)
                        if source.read(1):
                            raise ValueError("Oversized archive member")
            payload = verify(pending, trusted_key, minimum_version=minimum_version)
            if destination.exists():
                raise ValueError("Destination was created during verification")
            pending.rename(destination)
            return payload
        except BaseException:
            shutil.rmtree(pending, ignore_errors=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline signed Windows archive verifier")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--min-version", required=True)
    args = parser.parse_args()
    payload = verify_archive(args.archive, args.install_dir, args.public_key,
                             minimum_version=args.min_version)
    print("Verified and staged signed W02 simulation-only release:", payload["version"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
