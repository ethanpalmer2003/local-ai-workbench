# Regression review status

Shared process, HTTP, media and startup fixtures own reusable setup. Tests keep
scenario assertions local; independent encoders/parsers verify production protocols.
Default regressions guard unmarked process starts and framework DLL loads.
Intentional subprocess fixtures declare their scope; live inference is explicit.
The guard is not a security sandbox and is not inherited by child interpreters.

[Fixture guide](../../scripts/tests/shared/FIXTURES.md) owns usage;
[test status](../../scripts/tests/notes/STATUS.md) owns validation evidence.
