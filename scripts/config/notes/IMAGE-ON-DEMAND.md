# Images on demand

- Launch: `bat/browser/launch_kobold.bat --image-on-demand`.
- Owns its new servers; refuses occupied ports. Existing standalone launch policies stay unchanged.

| Phase | Kobold | TTS | Image model |
| --- | --- | --- | --- |
| Conversation | Loaded | Loaded | Unloaded |
| Image session | Loaded | Unloaded | Loaded |

- First image POST drains conversation work, unloads TTS and loads Nova; further images reuse it.
- First text/speech POST finishes image work, unloads Nova and loads TTS. Health/config/model-list requests do not trigger swaps.
- Native model APIs handle ordinary swaps; servers/proxies remain running. Only an unresponsive owned sd.cpp control API can require restart; busy work is not cancelled.
- Public/native ports: Kobold 5001/5002, AudioCpp 8888/8889, sd.cpp 1234/1235. Use the public endpoints for coordination; direct native calls bypass it.
- Model-management bodies pass through without remapping or schema changes. One in-process coordinator owns switching.
- Launcher exit stops owned servers. Preserve unrelated existing sessions.

## Configuration ownership

- Python coordinator/policy: [image_on_demand.py](../../launchers/runtime/image_on_demand.py), [configuration](../shared/image_on_demand.py); runtime defaults remain in `launcher_config.py`/native model configs.
- New coordination logs use the shared component log root; historical probe results remain unchanged.
- Prior functionality/timings apply to their recorded versions and models. Future model/driver/native API changes require explicit verification.
- [Test rules](../../tests/README.md), [pending checks](../../../notes/TODO.md).
