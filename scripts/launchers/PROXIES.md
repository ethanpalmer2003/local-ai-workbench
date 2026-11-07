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
- Backends keep their own settings; the pair of ports lives on the owning `*_SERVICE` entry in [launcher_config.py](launcher_config.py).
