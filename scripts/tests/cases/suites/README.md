# Suite entry points

The modules behind the test commands that run work rather than assert a unit: the regression
runner, the native launcher and backend suites, the framework update check, and the shared
contracts both suites assert. They are not tests; the default suite imports the classes it
needs from here.

- [frameworks_smoke.py](frameworks_smoke.py) parses the suite flags and runs the default
  regressions; [live_frameworks.py](live_frameworks.py) drives the native launcher targets and
  their workers; [quick_validation.py](quick_validation.py) drives the backend probes.
- [framework_updates.py](framework_updates.py) checks for framework releases and is not run
  automatically; [shared_contracts.py](shared_contracts.py) holds the contracts the suites share.
- Supporting modules: `launcher_behaviors.py`, `gemma_runtime_screen.py`, `gpu_memory.py`,
  `native_image_session.py`, `framework_permissions.ps1`.
- Commands and levels: [test guide](../../README.md), [checks policy](../../../../.agents/CHECKS.md).
