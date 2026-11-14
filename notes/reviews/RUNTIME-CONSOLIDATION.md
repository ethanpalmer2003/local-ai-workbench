# Shared runtime review status

Shared owners cover process readiness/cleanup, ASR command profiles, audio
preparation, multipart uploads and native-library binding. Caller adapters retain
reuse/isolation policy, model-specific options and native object destruction.
Production code must not import test fixtures or benchmark command definitions.

[Runtime guide](../../scripts/launchers/shared/README.md) owns usage.
[Test status](../../scripts/tests/notes/STATUS-INDEX.md) distinguishes contract checks
from live backend coverage; [TODO](../TODO.md) owns follow-up.
