"""One vocabulary for "has this changed since a run recorded it".

The repository asks that question in three shapes, and each shape has one owner:

1. Which files a gate or suite should read, and what moved since upstream: `changes.py`, git only.
2. Whether a set of inputs is the same as when a run last passed: `fingerprint` and `tree_fingerprint` here,
   content only, so a rewrite that changes nothing does not buy a rerun.
3. How old a piece of evidence is: the age rule beside that evidence, because age is not content. The handoff
   brief owns it for the similarity screen.

A stamp is always a digest recorded next to the run it describes; `matched` is the one comparison, so a
caller never compares a timestamp to a digest and calls the result staleness.
"""

import hashlib
from collections.abc import Iterable
from pathlib import Path


def content_digest(path: Path) -> str:
    """SHA256 of one file's bytes: what a manifest stores per path."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(files: Iterable[Path], root: Path) -> str:
    """Digest of an explicit file list: its paths and contents, in sorted order."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            digest.update(b"missing")
        digest.update(b"\0")
    return digest.hexdigest()


def tree_fingerprint(
    roots: Iterable[str], root: Path, suffixes: frozenset[str], skip_parts: frozenset[str], extra: bytes = b""
) -> str:
    """Digest of every matching file under the given roots, plus anything the caller adds.

    `extra` carries facts a file walk cannot see, such as which models and frameworks are installed.
    """
    digest = hashlib.sha256()
    for relative in roots:
        base = root / relative
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in suffixes or skip_parts & set(path.parts):
                continue
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b"\0")
            try:
                digest.update(path.read_bytes())
            except OSError:
                # - a file removed between the walk and the read moved as surely as an edited one
                digest.update(b"missing")
    digest.update(b"\0")
    digest.update(extra)
    return digest.hexdigest()


def manifest(files: Iterable[Path], root: Path) -> dict[str, str]:
    """Content digest per file, keyed by path relative to `root`, for a later comparison."""
    return {path.relative_to(root).as_posix(): content_digest(path) for path in files}


def changed_since(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    """Paths whose content differs from a recorded manifest, that are new, or that are gone.

    A removed path changes the inputs as much as an edited one: a reader comparing the two manifests
    must see the deletion, or a report keeps describing a file the tree no longer has.
    """
    changed = {path for path, digest in current.items() if recorded.get(path) != digest}
    changed |= set(recorded) - set(current)
    return sorted(changed)


def matched(recorded: str | None, current: str) -> bool:
    """Whether a recorded stamp still describes the inputs it was taken from."""
    return bool(recorded) and recorded == current
