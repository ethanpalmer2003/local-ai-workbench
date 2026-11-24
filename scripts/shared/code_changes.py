"""Which changed paths carry a code change, answered from source rather than from text.

The commit-stage selector and the pre-push stage both ask this, so it lives here instead of inside either
caller. A `.py` edit that only touches comments, docstrings or layout is not a code change: `ast.parse`
drops comments and `_dump_without_docstrings` drops docstrings, so matching dumps mean no test can observe
the edit.
"""

import ast
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.changes import GitError, upstream_texts
from scripts.shared.import_graph import ast_parse_text_or_file


def python_code_changed(paths: list[str], root: Path | None = None) -> bool:
    """Whether any changed Python file carries a code change; a document or config path never counts.

    The pre-push stage asks this, so a push that only edits Markdown, a batch file or configuration runs
    nothing, as it always did, and a `.py` edit that only touches prose stays cheap as well.
    """
    # Filter first, so a prose-only push never pays for a git read.
    return bool(paths_with_code_changes([path for path in paths if path.endswith(".py")], root))


def paths_with_code_changes(paths: list[str], root: Path | None = None) -> list[str]:
    """The changed paths that carry a code change; a Python prose-only edit is left out.

    The pre-push stage asks this same question, so a push that only edits comments or docstrings stays
    fast instead of running the full suite for a file whose behavior did not change.
    """
    # Only `.py` paths can match upstream, so every other path stays for the caller to judge.
    if not paths:
        return []
    base = root or project_cfg.BASE_DIR
    # A path that is gone from the tree is left out of the read: it is a change by definition, and git has
    # nothing to show for it, which `_code_changed_since_upstream` already answers.
    readable = [path for path in paths if path.endswith(".py") and (base / path).is_file()]
    # The upstream copies come from one git call for the whole set. A read that fails is no evidence, so
    # every path counts as a change then, which is the same answer a missing copy gives.
    try:
        previous = upstream_texts(readable, root)
    except GitError:
        previous = {}
    # One comparison per path; `previous.get(path)` is None for a path git had nothing to show for.
    return [path for path in paths if _code_changed_since_upstream(path, previous.get(path), root)]


# The single pair of trees behind the answer: the committed copy against the working copy.
def _code_changed_since_upstream(path: str, previous_source: str | None, root: Path | None = None) -> bool:
    """Return whether a file's code differs from `previous_source`, comments, docstrings and layout aside.

    True means a test can see the difference, which is how the selector reads it. Anything that is not
    Python source answers True, and so does a file whose upstream copy is missing or empty: those count as
    real changes rather than invisible ones.
    """
    # Only Python source can be compared as a tree; every other file is a real change by default.
    if not path.endswith(".py"):
        return True
    # `root` exists so a test can point this at a temporary repository; production passes nothing.
    current = (root or project_cfg.BASE_DIR) / path
    # A path that is no longer on disk cannot be compared, so it counts as a real change.
    if not current.is_file():
        return True
    # Nothing to compare against: None when git answered nothing, "" when the committed file is empty.
    if not previous_source:
        return True
    # The committed copy as a tree: source text from git, or None when it is empty or unparsable.
    committed = ast_parse_text_or_file(previous_source)
    # The working copy as a tree, parsed the same way, so the comparison is tree against tree.
    working = ast_parse_text_or_file(current)
    # A copy that will not parse is a real change as well, since nothing can be ruled out.
    if committed is None or working is None:
        return True
    # `ast.parse` drops comments and `_dump_without_docstrings` drops docstrings, so the two dumps hold only
    # code, and different dumps mean a test can observe the edit.
    return _dump_without_docstrings(committed) != _dump_without_docstrings(working)


def _dump_without_docstrings(tree: ast.Module) -> str:
    """Return the AST dump of `tree` with its docstrings removed, mutating `tree` in place."""
    # The four node kinds that can own a docstring: the module, a class, a def and an async def.
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    # `ast.walk` yields every node, including the ones nested inside functions and classes.
    for node in ast.walk(tree):
        # Skip other node kinds, and skip an empty body, which cannot begin with a string.
        if not isinstance(node, scopes) or not node.body:
            continue
        # A docstring is always the first statement of its body, never the second.
        if _is_docstring(node.body[0]):
            # Substitute `pass` when it was the only statement, so a docstring-only body compares equal to one
            # holding `pass`.
            node.body = node.body[1:] or [ast.Pass()]
    # `ast.dump` leaves out line and column numbers, which is why moving or reformatting code compares equal.
    return ast.dump(tree)


def _is_docstring(statement: ast.stmt) -> bool:
    """Whether a statement is a bare string, which is how a docstring is stored."""
    # A docstring is an expression statement whose value is a constant...
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Constant):
        return False
    # ...and that constant is a string, not a number or `None`.
    return isinstance(statement.value.value, str)
