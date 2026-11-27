# llama.cpp launchers

```powershell
C:/AI/bat/launch_llamacpp_pi_agent.bat
C:/AI/bat/browser/launch_test.bat
```

- Client variants: Pi, LittleCoder, Oh My Pi and NanoCoder; DSH has its own desktop integration. `--client none` starts without a coding client.
- Backend-only module: `scripts.launchers.llamacpp.llamacpp`.
- Selection: `LLAMACPP_DEFAULT_BUILD`, `LLAMACPP_ACTIVE_CODING_AGENT_PROFILE`, `LLAMACPP_SERVICE` and `LLAMACPP_BUILDS`.
- One llama.cpp default serves every use: `LLAMACPP_DEFAULT_BUILD` (`vulkan`, the rolling build) is what coding, the embedding server and the Kobold no-model arm resolve through `llamacpp_build()`. `LLAMACPP_CODING_BUILD` and `LLAMACPP_EMBEDDINGS_BUILD` override it per use when one needs another build. `vulkan-1.0.0` stays installed as the fallback; `rocm-lemonade` and `hrx` stay selectable by name.
- Build IDs: `vulkan`, `vulkan-1.1.0`, `vulkan-1.0.0`, `rocm-lemonade`, `rocm-rdna`, `rdna-vulkan` and `hrx`; a name whose directory is missing refuses with a repair hint ([builds](../../config/llamacpp/BUILDS.md)). Unsloth's fork is retired: it existed for the repository-root Inkling layout and its DSpark drafter, and mainline now runs the `Mainline_Support` copy. Native paths come from the component map; old selectors in historical results are not current aliases.
- Profiles supply model/context/speculation defaults over native INI. [Settings rationale](../../config/llamacpp/TUNING.md), [HRX](../../config/llamacpp/HRX.md). The browser llama-ui with workspace speech: [llama-ui speech](SPEECH-UI.md).
- CLI overrides such as `--llama-cpp-build`, `--ini-profile`, client choice and startup options apply to a new server; existing matching proxy reuse retains its settings.
- `launch_test_llm.bat` opens the shared `/test/` page with only the LLM stage enabled.
- The API proxy module uses public/internal ports from `LLAMACPP_SERVICE`; health/model-list responses do not establish a loaded model.
- Existing service handling follows the [shared port policy](../shared/README.md).
- Shared readiness/restart/lifetime helpers handle owned children; launcher exit cleans up owned temporary resources.
- Coding clients use canonical `runs/state/coding_agents/<client>/` homes. Pi settings/extensions originate in [config/coding_agents/pi](../../config/coding_agents/pi/README.md).
- Separate language practice: [ASR guide](../asr/README.md); shares installed runtimes/weights without changing the coding default.
- Benchmarks and live workflows remain opt-in; [test rules](../../tests/README.md).
