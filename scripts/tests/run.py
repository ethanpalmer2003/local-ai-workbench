"""Run the test classes the change reaches, or every class with `--all` and at the push stage."""

import sys

from scripts.shared.changes import GitError, NoUpstreamError, changed_since_head, changed_since_upstream
from scripts.shared.code_changes import python_code_changed
from scripts.shared.timing import timed
from scripts.tests.cases.suites import frameworks_smoke
from scripts.tests.registry import TEST_CLASSES
from scripts.tests.scoped_selection import select_test_classes

if __name__ == "__main__":
    pushing = "--push" in sys.argv[1:]
    committing = "--commit" in sys.argv[1:]
    # - the suite's own parser must not see the stage flag
    sys.argv = [sys.argv[0], *[argument for argument in sys.argv[1:] if argument not in ("--push", "--commit")]]
    arguments = sys.argv[1:]
    with timed("default regressions"):
        # - --push is the pre-push stage: every class when a code change is unpushed, none when only
        #   comments, docstrings or prose are, through the same filter the commit stage applies
        try:
            python_changed = python_code_changed(changed_since_upstream())
        except (GitError, NoUpstreamError):
            # No baseline is no evidence, so the push stage runs every class rather than none
            python_changed = True
        if pushing and not python_changed:
            print("[PUSH] no Python code change since upstream; the suite is unchanged", flush=True)
            raise SystemExit(0)
        # - the scope follows the change; --all and --push run every class, and run.py keeps it exhaustive
        try:
            change_set = changed_since_head() if committing else None
        except GitError as error:
            print(f"[FAIL] git could not report the change: {error}", flush=True)
            raise SystemExit(1)
        selection = select_test_classes(
            TEST_CLASSES, full="--all" in arguments or "--push" in arguments, change_set=change_set
        )
        print(f"[SCOPE] {len(selection.kept)} of {len(TEST_CLASSES)} test classes ({selection.reason})", flush=True)
        if not selection.kept:
            # - a change set with no Python module runs nothing; pytest with no node ids would collect all
            print("[SCOPE] nothing to run; pass --all for every class", flush=True)
            raise SystemExit(0)
        raise SystemExit(frameworks_smoke.main(extra_classes=selection.kept, reason=selection.reason))
