"""The upstream copy of a change set, read in one git call for the whole set.

The change sets themselves live in `shared/file_sets.py` beside the other file sets; this module keeps
the upstream-copy reader the code-change judges ask for. `upstream_texts` answers every path from one
`git cat-file --batch` call, and `committed_paths` answers what `HEAD` touched for the post-commit
hook. A git command that fails raises `GitError`, because a broken read is not the same answer as an
empty one. The callers that deliberately read failure as no evidence use `git_text_or_none`, which
answers None.
"""

import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.file_sets import GitError, git_text_or_none


def committed_paths(root: Path | None = None) -> list[str]:
    """The paths HEAD's commit touched, which is what a post-commit hook has to judge."""
    lines = (git_text_or_none("show", "--name-only", "--pretty=format:", "HEAD", root=root) or "").splitlines()
    return sorted({line.strip() for line in lines if line.strip()})


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
