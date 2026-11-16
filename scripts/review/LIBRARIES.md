# Libraries behind the gate

Which checks run through a maintained tool, which are this repository's own vocabulary, and the library each hand-rolled check was compared against.

## Delegated

| Job | Tool |
| --- | --- |
| Lint, formatting and the McCabe limit | ruff |
| Dead definitions and unreachable blocks | vulture |
| Type contracts | basedpyright |
| Misspellings | codespell |
| Declared versus imported dependencies | deptry, `packaging`, `importlib.metadata` |
| Installed-package advisories | pip-audit |
| Lock versus `pyproject.toml` | uv |
| The model-free suite | pytest |

`package_audit.py` wraps the dependency tools and `__main__.py` wraps the rest; nothing else runs a subprocess for a job a library already does.

## Policy

A library cannot know this repository's vocabulary, so these read the tree directly:

- `layout.py`, `docs.py`, `sources.py`, `text_files.py`: folder roles, document roles and budgets, pointer policy, the text suffixes.
- `spellings.py`: the American forms this repository writes, on top of codespell's typos.
- `network_timeouts.py`: a source rule over `urllib`, `requests` and `http.client` calls.
- `model_references.py`, `frontend_wiring.py`, `overlay_access.py`: catalog ids, DOM ids and settings keys, overlay path ownership.
- `comments.py`, `typography.py`: shapes no linter is configured for.

## Compared and declined

| Check | Library | Why the check stays |
| --- | --- | --- |
| a definition scan of its own | vulture | Replaced. A hand-rolled mention count reported 0 findings on 463 files, while vulture at 60% found the two that were real (`live.capable`, `SdcppProxyRequestLora`), flagged only because a comment or a docstring named them. What stays this repository's is the policy in `dead_code.py`: `unused function`, `unused class` and unreachable code are findings, and the other 177 lines are not, because protocol attributes (`close_connection`, `daemon_threads`, `LimitFlags`), method overrides (`do_GET`, `log_message`) and exported catalog constants are read by a library or another process rather than by a call this scan can see. |
| `comments.py` | eradicate | Measured: 0 findings on the 457 maintained files, because `comments.py` already rejects commented-out code. Nothing to adopt. |
| `public_audit.py` | detect-secrets, gitleaks | The terms come from the overlay, and the scan covers history; both tools read a baseline stored in the tree. |
| `docs.py` links | a Markdown parser | Resolving a link is about forty lines; the work is role, budget and pointer policy. |
| `similarity.py` | a text-difference library | The duplicate check compares embeddings from the local model, not strings. |
| a verbosity rule | vale 3.27 with `Voices`, `AiTells`, `Readability` | Measured: 3,551 alerts untuned, dominated by `Readability.Polysyllables` (2,033) and document scores on technical prose, plus `Voices.ColonReveal` (143) and `AiTells.FilePath` (138), which are this repository's deliberate style. Tuned to the style's own rules with a vocab for product names: 11 alerts over 141 documents, and 10 were wording that is literal here (`elevate` as privilege, `this page` in a sentence rather than a link). One real hit, `robust` in `leaderboards-2026-10-29/README.md`. Vale is a 10.6 MB binary outside uv and syncs styles from GitHub, so the check would need its own download path for a one-in-141 yield. |
| `comments.py` | vale `Comments` style | It checks owned TODOs and commented-out code across the languages Vale extracts comments from, which is the whole of `comments.py` rather than a third of it. |

An adoption is worth it when the library replaces policy, not when it replaces twenty lines beside it.
