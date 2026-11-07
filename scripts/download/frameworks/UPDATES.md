# Framework updates

```powershell
C:/AI/bat/update_frameworks.bat --check-only
C:/AI/bat/update_frameworks.bat --category speech --check-only
C:/AI/bat/update_frameworks.bat --only asr
```

- Entry: [update_frameworks.py](update_frameworks.py); [update_config.py](update_config.py) composes catalogs and handlers. Shared download, verification and replacement logic lives in [update_shared.py](update_shared.py); [update_types.py](update_types.py) owns catalog types.
- Categories: `llamacpp` -> [llamacpp/updates.py](llamacpp/updates.py); `speech` (TTS/AudioCpp) -> [audiocpp/updates.py](audiocpp/updates.py) and [tts/updates.py](tts/updates.py); `other` -> [shared/other_updates.py](shared/other_updates.py). ASR entries live in [asr/updates.py](asr/updates.py). Keep component handlers in their folder; root modules compose catalogs and shared machinery. Component keys resolve install paths through `framework_install_dir()`.
- Check selected active entries first, print categories/status, then apply. `--category` and `--only KEY` combine; `--only` includes children. Disabled entries remain skipped. Omit `--check-only` to install/update.
- Output nests category, then update kind, then status. Kinds, ordered in [update_types.py](update_types.py): git fast-forward, github release, npm package, app installer, vendor script, git snapshot, pip wheel, local build, manual. A component spanning two kinds is expanded, not repeated. A current entry shows its version only, with no status suffix.
- Every GitHub API call goes through [github.py](github.py), which reads `GITHUB_TOKEN` from `scripts/.env`. Without it, checks share GitHub's anonymous 60 requests/hour limit and start failing as `rate limit exceeded`.
- Detailed logs: `scripts/state/logs/shared/framework_updates/`. Native/backend work requires the documented execution context.
- Verify advertised archive SHA256 before replacement; preserve previous installs in trash. Before applying, stop processes using selected update targets (including child processes); if shutdown fails, block all updates. Unrelated services are left running.
- Date-based packages track release timestamp and asset name. Installers run only where the entry declares it: Handy's portable setup (only while the app is missing), Strata's desktop app, and the Electron coding-agent apps, each installed silently and the resulting version re-read; a running app is stopped first.
- Source entries: `SOURCE UPDATE AVAILABLE; BUILD REQUIRED` (clean checkout, you recompile), `UPSTREAM CHANGED; MANUAL MERGE/REBUILD REQUIRED` (local patches first), or a replayed local commit where `rebase_local` is set.
- `C:/AI/bat/build_frameworks.bat` recompiles every entry that declares a build command; one new terminal per target unless `--foreground`, `--dry-run` prints the commands. Entries with `in_use=False` are ignored outright: never checked, never listed.

Per-component install and update specifics are in [UPDATES-COMPONENTS.md](UPDATES-COMPONENTS.md).

## HRX

All three HRX repositories are disabled in routine updates. Even `--only llamacpp/additions/hrx` skips them; re-enable their `in_use` fields in `llamacpp/updates.py` before requesting source updates. Existing checkouts and manual builds remain available.

```powershell
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.download.frameworks.llamacpp.hrx.build --merge --install
```

- Source update: clean checkouts fast-forward; dirty/local commits require review/merge. Preserve patches under `state/llamacpp/hrx/source-patches/`.
- Build: merge/build/validate/install with rollback; omit `--install` for staged candidate. `--validate-only` reuses build output. Runtime checks are live work, not ordinary static verification.
- Restore checkpoints with `scripts.download.frameworks.llamacpp.hrx.prepare`; [evidence/limits](../../config/llamacpp/HRX.md).
- AMD ROCm nightly index: https://nightly.repo.amd.com/rocm/core/tarball/ ; no automatic SDK install.
- Windows access failures -> check token/integrity before retrying outside sandbox; earlier approval does not relax later runs.

ASR-only catalog: [asr/updates.py](asr/updates.py), selected with `--category asr` or `--only asr`. NeMo-Speech.cpp, speech.cpp, CrispASR and FunASR use official stable Windows Vulkan releases under `frameworks/asr/<runtime>/vulkan/`. Shared AudioCpp/Sherpa installations retain one owner instead of duplicate ASR installs. [Installed versions and limits](../../../notes/asr/ASR-DOWNLOADS.md).
