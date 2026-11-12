# Backend proxies

- Principle: a proxy owns the public port, and the backend it fronts moves to the next one. Clients keep using the public port whether or not a proxy is running, so a URL never changes because a proxy was added.
- The proxy is a stand-in, not a new endpoint: same routes, same JSON, same streaming shape as the vendor server. Anything the proxy adds is additive.

| Proxy | Public | Backend | Why it exists |
| --- | ---: | ---: | --- |
| [AudioCpp](audiocpp/audiocpp_proxy.py) | 8888 | 8889 | `/test/` and `/practice` pages, tone/text cleanup, TTS page cloning and streaming, backend switching, restart control |
| [sd.cpp](sdcpp/proxy.py) | 1234 | 1235 | Single UI/API door for the sd.cpp server plus backend lifecycle and restart control |
| [KoboldCpp Lite](koboldcpp/kobold_lite.py) | 5001 | 5002 | Serves the installed Lite page patched at request time: streaming audio, tone tags, external transcription and the no-model endpoint seed |
| [llama.cpp](llamacpp/llamacpp_proxy.py) | 9931 | 9932 | Lazy model: answers `/health` and `/v1/models` from configuration, loads on the first real request, unloads after idle so the VRAM comes back |

- llama.cpp needs a proxy only for that lazy load/unload lifecycle and for answering discovery before a model exists. Its native API already streams, so there is no preprocessing reason to stand one in front; run the server directly when the model should stay resident.
- A client points at the public port, never the backend. KoboldCpp's Text to Speech panel, with OpenAI-compatible API server chosen, takes `http://127.0.0.1:8888/v1/audio/speech`, plain HTTP like every local port. That address serves a standalone AudioCpp server and the proxy alike, and through the proxy an unknown `model` or `voice` is replaced with the configured pair instead of failing.
- Two ports serve a page someone opens, and every origin keeps its own browser storage: the patched Lite page on 5001 and KoboldCpp's own page on 5002, times each host spelling (`localhost`, `127.0.0.1`, a LAN address, since the UI binds `0.0.0.0`). Lite keeps its settings and its saved story in one IndexedDB database named `e_kaihordewebui_` per origin, so the same stack opened through a different URL starts with defaults and no history. Use the address the launcher opens, which is `http://localhost:5001`.
- KoboldCpp is the one exception to the port order: its server always serves its own page on the port it listens on, so the proxy takes the port above it instead of moving the backend up. The page on 5002 is therefore API-only in practice: bound to `127.0.0.1`, unpatched, and holding its own storage, while the launcher opens the patched page on 5001.
- Backends keep their own settings; the pair of ports lives on the owning `*_SERVICE` entry in [launcher_config.py](launcher_config.py).
