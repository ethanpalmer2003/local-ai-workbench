"""Single browser-open boundary; live suites suppress UI windows with AI_NO_BROWSER."""

import os
import webbrowser


def open_browser(url: str) -> bool:
    """Open a URL unless the current process is a non-interactive test run."""
    if os.environ.get("AI_NO_BROWSER") == "1":
        return False
    if os.name == "nt":
        os.startfile(url)
    else:
        webbrowser.open(url)
    return True
