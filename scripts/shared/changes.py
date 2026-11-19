"""What this checkout has changed, in the two sets the two stages need.

One owner for the answer, because the review gate, the formatter and the test scope all narrow their work
to it. Two functions, one per stage:

- `changed_since_head()` is the commit stage: the working tree and index against `HEAD`, so earlier
  unpushed commits do not run again.
- `changed_since_upstream()` is the push stage and a bare run: those paths plus the commits the upstream
  branch lacks, since anything unreviewed is in scope there.

A git command that fails raises `GitError`, because a broken read is not the same answer as an empty one.
The callers that deliberately read failure as no evidence use `git_text_or_none`, which answers None.
"""

import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg


class GitError(RuntimeError):
    """A git command failed, so there is no answer rather than an empty one."""


def git_text(*args: str, root: Path | None = None) -> str:
    """The command's stdout, raising `GitError` when git fails.

    The bytes are decoded as UTF-8 here rather than by the locale, because `git show` returns file
    content: a source file with an accented name or letter is not decodable by every console codec, and
    a reader thread that raises leaves the caller with None instead of text.
    """
    base = project_cfg.BASE_DIR if root is None else root
    result = subprocess.run(["git", "-C", str(base), *args], capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip() or f"exit {result.returncode}"
        raise GitError(f"git {' '.join(args)}: {detail}")
    return result.stdout.decode("utf-8", errors="replace")


def git_text_or_none(*args: str, root: Path | None = None) -> str | None:
    """The command's stdout, or None when git fails; callers read that as no evidence."""
    try:
        return git_text(*args, root=root)
    except GitError:
        return None


def committed_paths(root: Path | None = None) -> list[str]:
    """The paths HEAD's commit touched, which is what a post-commit hook has to judge."""
    lines = (git_text_or_none("show", "--name-only", "--pretty=format:", "HEAD", root=root) or "").splitlines()
    return sorted({line.strip() for line in lines if line.strip()})


class NoUpstreamError(RuntimeError):
    """This branch has no upstream ref, so there is nothing to compare against."""


def upstream_known(root: Path | None = None) -> bool:
    """Whether this branch has an upstream ref, which an empty change set cannot tell you."""
    return bool((git_text_or_none("rev-parse", "--abbrev-ref", "@{upstream}", root=root) or "").strip())


def changed_since_head(root: Path | None = None) -> list[str]:
    """Every path the working tree or the index has changed against `HEAD`; a rename gives both sides."""
    paths: list[str] = []
    for line in git_text("status", "--porcelain", root=root).splitlines():
        body = line[3:].strip().strip('"')
        if body:
            paths.extend(part.strip().strip('"') for part in body.split(" -> "))
    return sorted(set(paths))


def changed_since_upstream(root: Path | None = None) -> list[str]:
    """Every unreviewed path: the working tree against `HEAD`, plus commits the upstream lacks.

    Raises NoUpstreamError when the branch has none, which is a different answer from an empty list.
    """
    if not upstream_known(root):
        raise NoUpstreamError
    paths = changed_since_head(root)
    paths.extend(
        path for path in git_text("diff", "--name-only", "@{upstream}...HEAD", root=root).splitlines() if path.strip()
    )
    return sorted(set(paths))


def upstream_texts(paths: list[str], root: Path | None = None) -> dict[str, str]:
    """The upstream copy of each path's text, from one `git cat-file --batch` call.

    One process answers the whole change set: a `git show` per path costs about 56 ms on this machine,
    which is 28 s over a 500-path rebase. A path git cannot answer for is absent from the result, so a
    caller reads a missing key as a real change; the command's own failure raises `GitError` instead, so
    a broken read is not mistaken for five hundred edits.
    """
    if not paths:
        return {}
    base = project_cfg.BASE_DIR if root is None else root
    request = "".join(f"@{{upstream}}:{path}\n" for path in paths).encode()
    result = subprocess.run(
        ["git", "-C", str(base), "cat-file", "--batch"], input=request, capture_output=True, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip() or f"exit {result.returncode}"
        raise GitError(f"git cat-file --batch: {detail}")
    return split_batch(result.stdout, paths)


def split_batch(payload: bytes, paths: list[str]) -> dict[str, str]:
    """Decode `cat-file --batch` output, one header line per path followed by that many bytes.

    A found object's header is `<oid> <type> <size>`; a path git cannot answer for gets its own spec back
    with ` missing` appended, which is how a deleted or untracked path arrives.
    """
    texts: dict[str, str] = {}
    position = 0
    for path in paths:
        end = payload.index(b"\n", position)
        header = payload[position:end].split()
        position = end + 1
        if header[-1] == b"missing":
            continue
        size = int(header[-1])
        texts[path] = payload[position : position + size].decode("utf-8", errors="replace")
        position += size + 1
    return texts
