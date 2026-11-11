# Regression fixtures

Share setup and protocols; keep each test's expected results and assertions local.
Extend these helpers before adding another copy. Production helpers belong in
`scripts/launchers/shared/`; test fixtures must not become production dependencies.

- `process_fixtures.py`: explicit running/exited processes, finite wait timeouts,
  real exit-code transitions and inspectable mock calls. No spawning. Use these
  for Popen objects, not psutil objects or unrelated SDK/context-manager mocks.
  Override deliberate failure/interrupt behavior explicitly in the test.
- `http_fixtures.py`: canned requests/urllib responses with bytes, status, headers,
  chunks and JSON. Context exit closes the response and never swallows exceptions.
  These are canned payloads, not a full socket/stream simulator.
- `http_server.py`: temporary loopback server and HTTP client for integration
  fixtures. Requires a context that permits loopback; record the token before
  running outside the sandbox. Servers use ephemeral ports and are shut down.
- `media_fixtures.py`: configurable PCM WAV generation and small PNG/speech
  fixtures. Encoders are independent of production audio code so regressions
  cannot pass merely because fixture and implementation share the same bug.
- `backend_fixtures.py`: adapter startup setup with temporary assets/configuration
  and mocked lifecycle operations. Shared ASR contract tests cover reuse, mismatch,
  occupied ports, startup failure and owned cleanup. Isolated servers have their
  own refusal contract; model flags/prompts/limits remain adapter-specific tests.
- `paths.py`: use `CasePaths.temporary_directory()` for owned test workspaces.

Fixture behavior is covered by `test_regression_fixtures.py`. Shared startup
contracts and fixture checks are registered in the default model-free suite.
`model_free.py` guards that suite against actual subprocess starts and framework
DLL loads, including fixture threads; mocks and temporary loopback remain allowed.
Intentional Python/Node/Git integration tests declare `@fixture_processes()`;
review their commands and descendants, since child interpreters do not inherit the guard.
Explicit live entry points run outside that boundary. This is not a security sandbox.
Test counts may fall when duplicated tests become a matrix; retain every distinct
contract and use labeled subtests to identify the adapter/scenario that failed.
