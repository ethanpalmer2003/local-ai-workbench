# Libraries behind the gate

Which checks run through a maintained tool, which are this repository's own vocabulary, and the library each hand-rolled check was compared against.

## Delegated

| Job | Tool |
| --- | --- |
| Lint, formatting and the McCabe limit | ruff |
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
- `unused.py`, `comments.py`, `typography.py`: shapes no linter is configured for.

## Compared and declined

| Check | Library | Why the check stays |
| --- | --- | --- |
| `unused.py` | vulture | Vulture needs a whitelist that would grow with every `patch.object(..., "name")` reference; this check reads source text, so those count as references and the list stays empty. |
| `comments.py` | eradicate | Eradicate covers one of the three rules (commented-out code); markers and banner rules are policy. |
| `public_audit.py` | detect-secrets, gitleaks | The terms come from the overlay, and the scan covers history; both tools read a baseline stored in the tree. |
| `docs.py` links | a Markdown parser | Resolving a link is about forty lines; the work is role, budget and pointer policy. |
| `similarity.py` | a text-difference library | The duplicate check compares embeddings from the local model, not strings. |
| a verbosity rule | vale with the `Voices` or `AiTells` style; proselint and write-good alone | Proselint reads bullets as prose, but over 141 documents its 120 findings were 119 misreadings (TODO links, backtick paths, ISO dates) and its set has no `in order to` rule. Vale carries the rules as styles: `Voices` holds a hedging and puffery core plus Direct and Simple voices, `AiTells` names the tells of generated prose, `Readability` names the polysyllables behind a score. Vale has no fix mode either. |
| `comments.py` | vale `Comments` style | It checks owned TODOs and commented-out code across the languages Vale extracts comments from, which is the whole of `comments.py` rather than a third of it. |

An adoption is worth it when the library replaces policy, not when it replaces twenty lines beside it.
