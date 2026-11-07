# llama.cpp launchers

```powershell
C:/AI/bat/launch_llamacpp_pi_agent.bat
C:/AI/bat/browser/launch_test_llm.bat
```

- Client variants: Pi, LittleCoder, Oh My Pi and NanoCoder; DSH has its own desktop integration. `--client none` starts without a coding client.
- Backend-only module: `scripts.launchers.llamacpp.llamacpp`.
- Selection: `LLAMACPP_ACTIVE_BUILD`, `LLAMACPP_ACTIVE_CODING_AGENT_PROFILE`, `LLAMACPP_SERVICE` and `LLAMACPP_BUILDS`.
- Build IDs: `rocm-stock`, `rocm-lemonade` (default), `rocm-rdna`, `vulkan`, `hrx`. Native paths come from the component map; old selectors in historical results are not current aliases.
- Profiles supply model/context/speculation defaults over native INI. [Settings rationale](../../config/llamacpp/SETTINGS.md), [HRX](../../config/llamacpp/HRX.md).
- CLI overrides such as `--llama-cpp-build`, `--ini-profile`, client choice and startup options apply to a new server; existing matching proxy reuse retains its settings.
- `launch_test_llm.bat` opens the shared `/test/` page with only the LLM stage enabled.
- The API proxy module uses public/internal ports from `LLAMACPP_SERVICE`; health/model-list responses do not establish a loaded model.
- Existing service handling follows `LAUNCH.existing_service_policy` (`KILL` by default; `REUSE` or `ERROR` are alternatives).
- Shared readiness/restart/lifetime helpers handle owned children; launcher exit cleans up owned temporary resources.
- Coding clients use canonical `state/coding_agents/<client>/` homes. Pi settings/extensions originate in [config/coding_agents/pi](../../config/coding_agents/pi/README.md).
- Separate language practice: [ASR guide](../asr/README.md); shares installed runtimes/weights without changing the coding default.
- Benchmarks and live workflows remain opt-in; [test rules](../../tests/README.md).
