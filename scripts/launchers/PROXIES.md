# Backend proxies

- Principle: a proxy owns the public port and its backend moves to the next one, so a client URL never changes when a proxy is added.
- A proxy is a stand-in: same routes, JSON and streaming shape as the vendor server; what it adds is additive.

| Proxy | Public | Backend | Why it exists |
| --- | ---: | ---: | --- |
| [AudioCpp](audiocpp/audiocpp_proxy.py) | 8888 | 8889 | Tone/text cleanup, voice cloning and streaming, backend switching, restart control |
| [sd.cpp](sdcpp/proxy.py) | 1234 | 1235 | Single UI/API door for the sd.cpp server plus backend lifecycle and restart control |
| [KoboldCpp Lite](koboldcpp/kobold_lite.py) | 5001 | 5002 | Serves the installed Lite page patched at request time: streaming audio, tone tags, external transcription and the no-model endpoint seed |
| [llama.cpp](llamacpp/llamacpp_proxy.py) | 9931 | 9932 | Lazy model: answers `/health` and `/v1/models` from configuration, loads on the first real request, unloads after idle so the VRAM comes back |

- llama.cpp needs a proxy only for that lazy lifecycle and for answering discovery before a model exists; its native API already streams, so run the server directly when the model should stay resident.
- A client points at the public port, never the backend. KoboldCpp's Text to Speech panel, with the OpenAI-compatible server chosen, takes `http://127.0.0.1:8888/v1/audio/speech`; that address serves a standalone AudioCpp server and the proxy alike, and through the proxy an unknown `model` or `voice` becomes the configured pair.
- Remote and mobile clients never point at 8888: a phone resolving loopback points at itself. Open the patched Lite page at `http://<lan-ip>:5001`, its speech requests post to the same origin, and the Lite server relays them to `127.0.0.1:8888`. The phone needs the same LAN and a firewall rule for the Lite port, never for 8888.
- Every origin keeps its own browser storage: the patched page on 5001 and KoboldCpp's own page on 5002, times each host spelling (`localhost`, `127.0.0.1`, a LAN address, since the UI binds `0.0.0.0`). Lite keeps its settings and saved story in one IndexedDB database per origin, so another URL starts with defaults; use the address the launcher opens, `http://localhost:5001`.
- KoboldCpp is the exception to the port order: its server always serves its own page on the port it listens on, so the proxy takes the port above. The page on 5002 is API-only in practice: bound to `127.0.0.1`, unpatched, with its own storage.
- Backends keep their own settings; the pair of ports lives on the owning `*_SERVICE` entry in [launcher_config.py](launcher_config.py).
- A stack launcher (`python -m scripts.launchers.<stack>`) supervises until stopped: its process running is the healthy state, and its exit means the stack went down. Start it in the background, then read readiness from the ports, the health endpoint and `/v1/models`; never wait on the job, and never behind a filter that buffers output. No gate can check this, so the rule is the guard.
- Start and stop the stack only through that entry point: it clears or refuses an occupied port and owns every child, while an ad-hoc `launch_module` bypasses the port policy and leaves duplicates nobody tears down. Leaving the session: close the launcher's window, or run `python -m scripts.launchers.kill_all_services`.
