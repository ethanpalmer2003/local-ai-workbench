# Front-end wiring check

`scripts/review/frontend_wiring.py` runs in the [repository review](README.md). It is static and
literal-only; it never executes the pages.

- Asset paths: HTML `<script src>`/`<link href>` and JS `path.join`/`path.resolve` calls. A base variable
  derived from `__dirname`, and loop variables bound to a literal array, are resolved; computed or
  templated paths are skipped rather than guessed. Because the page is served at a shallow URL (`/test/`),
  an HTML reference also resolves once its leading `../` segments are stripped and matched under
  `scripts/`.
- DOM ids: ids an inline script reads via `getElementById`/`querySelector('#id')` must be defined in the
  same HTML; external scripts are not scanned.
- Settings keys: each row of `SETTINGS_CONTRACTS` pairs a launcher's injected `window.<object>` with its
  reader scripts and test fixture. Reads the launcher never emits, or (ignoring `||`/`??` fallbacks) the
  fixture never provides, are reported. Add a row per injected settings object.
