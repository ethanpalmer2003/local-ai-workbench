# Component maintenance

Per-component install and update specifics; commands, categories and the HRX note stay in [UPDATES.md](UPDATES.md), applied under the shared check/apply, verification and logging rules described there. What each family targets, and what this machine ran, is the [platform matrix](PLATFORMS.md).

| Component | Maintenance |
| --- | --- |
| Parakeet CPU/Vulkan | Official Windows releases; `--only asr/parakeetcpp`; [models/commands](../../launchers/asr/PARAKEET.md) |
| Whisper current Vulkan | `--only asr/whispercpp/vulkan-build`; source build with the normal check/apply plan; legacy prebuilt disabled |
| Handy | `--only asr/handy` downloads the installer and installs the portable app when missing; the app then uses its built-in updater; [portable setup](../../launchers/asr/HANDY.md) |
| llama.cpp Vulkan | Official assets; ASR and coding share one install. Build ids `vulkan`, `rocm-lemonade` and `rocm-rdna` update from their releases, while `vulkan-1.0.0` is a deliberate pin that no update replaces |
| rdna-boosts | The patch set comes from `patches.tar.gz` on the newest release of `stew675/llama-cpp-rdna-boosts`, tag recorded in its `release.json`, so [the build](../../download/frameworks/llamacpp/rdna_build.py) applies a named patch set instead of whatever `origin/main` held |
| Loom | `ROCm/hrx-system` releases: the release-profile `hrx-loom` wheel into `frameworks/loom/sdk` (instrumented `+debug`/`+tracy`/`+asan` wheels are not selected), plus the standalone `loom-serve` and `amdf-info` executables |
| AudioCpp | Vulkan and official ROCm active (`--only audiocpp/rocm`); legacy ROCm/build disabled. eSpeak/MeCab under `audiocpp/additions/` are manual; [Kokoro setup](../../launchers/audiocpp/README.md) |
| Sherpa/Piper | Official Windows CPU packages; `--only tts`; [launchers/models](../../launchers/audiocpp/RETAINED-TTS.md). Piper wheel and dependencies stay inside its framework directory |
| sd.cpp | ROCm/Vulkan updated; service selection remains in configuration |
| Pi | Single package manifest; applying may install/remove enabled packages/extensions |
| Strata | Check-only through the app's own updater: engine, control and app versions are reported, a newer part is a notice, and the update happens in the Strata app |
| Avalon | llama.cpp fork (`freriadoc/Avalon`) cloned and compiled by hand with cmake. One local commit carries the MSVC fix for `close()` in `ggml/src/ggml-cuda/moe-cache.cu`; `pull --rebase --autostash` replays it, so the update is never blocked and the change stays single. A dirty tree still reports a merge. A pulled commit is reported as still needing a build, which `bat/update_frameworks.bat` runs |
| DeepSeek Harness | Electron app tracking its nightly feed (`download.deepseek.com/dsh-desk`); compared by the executable's own version and installed silently when the app is closed |
| ComfyUI | Delegated updater, run attached so its exit code becomes this run's result; owned config sync is separate |
| Model servers | `frameworks/model_servers/` groups the engines that wrap other engines: KoboldCpp, Lemonade Server, LocalAI and Text generation WebUI. KoboldCpp installs from its GitHub release; the other three are parked until installed, because each ships its own launcher: LocalAI has no Windows binary, Text generation WebUI a portable zip, Lemonade a self-updating app |
