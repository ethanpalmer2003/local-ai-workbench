# Framework platform matrix

What each installed family targets, and what this machine actually ran. This workspace runs Windows x64
only, so `Windows` means the installed artifact is a Windows binary; `any` means the package itself is not
bound to an OS. A row marked `not established` is a claim nobody here tested: read the component guide
before relying on it.

| Family | Class | GPU / accelerator | Tested here |
| --- | --- | --- | --- |
| llama.cpp Vulkan | Windows, any GPU | A Vulkan 1.3 device with buffer device address | RX 7800 XT (gfx1102); b12363 is the last build that survives long prefill |
| llama.cpp ROCm (Lemonade) | Windows, AMD | AMD `gfx110X`; a visible Ryzen iGPU must be hidden | RX 7800 XT at 51-56 tok/s |
| llama.cpp RDNA build with rdna-boosts | Windows, AMD | RDNA3/RDNA4 compiled with ROCm and MSVC, `gfx1101` by default | Patch set v17 installed; no build from it yet |
| HRX (hrx-system, HRX llama.cpp fork, rocm-systems) | Windows, AMD | AMD, source trees compiled by hand | Deferred; see [upstream](../../../notes/UPSTREAM-INDEX.md) |
| sccache | Windows, CPU | none | Compiler cache for the RDNA build |
| AudioCpp Vulkan | Windows, any GPU | Vulkan 1.3 | Active speech runtime |
| AudioCpp ROCm | Windows, AMD | AMD `gfx1101` | Active speech runtime |
| eSpeak NG, MeCab | any, CPU | none | Text processing for speech |
| Sherpa ONNX, Piper | Windows, CPU | none | Parked comparison alternatives |
| Handy | Windows, CPU | Microphone input | Manual dictation validation pending |
| Parakeet CPU | Windows, CPU | none | Streaming passes |
| Parakeet Vulkan | Windows, any GPU | Vulkan | Streaming Vulkan crashes upstream |
| Whisper Vulkan (built) | Windows, any GPU | Vulkan | Source build in use; the prebuilt entry is parked |
| NeMo-Speech.cpp, speech.cpp, FunASR | Windows, any GPU | Vulkan | Candidate engines |
| Loom SDK, `loom-serve`, `amdf-info` | Windows and Linux, AMD or Vulkan | AMD through libamdf (`rdna`), or a Vulkan 1.3 device | v0.2.0 from its release: the SDK fetches and loads a 0.5B package, `amdf-info` activates `rdna://0`, and `loom-serve` finds no AMD endpoint at all |
| Strata | Windows app, AMD | RX 7000/9000 series or Ryzen AI Max | Serves the 27B benchmark arm on ROCm |
| KoboldCpp | Windows, CPU | none (the `nocuda` build) | Language practice |
| sd.cpp ROCm | Windows, AMD | AMD | Image generation |
| sd.cpp Vulkan | Windows, any GPU | Vulkan | Image generation |
| ComfyUI ROCm | Windows, AMD | AMD | Media generation |
| Avalon | Windows, NVIDIA | CUDA | Parked; the fork trails stable llama.cpp |
| Pi, Little Coder, Nanocoder | any, CPU | none | Coding clients over HTTP |
| oh-my-pi | Windows, CPU | none | Coding client over HTTP |
| DeepSeek Harness | Windows app, CPU | none | Coding client over HTTP |
| Benchmark harnesses, `club-rdna16` | any, CPU | none | Corpus and metrics only |

Two rules keep a row honest:

- `Class` names what the artifact requires, never what an upstream announcement claims: an engine with a
  Vulkan build is `any GPU` even where only one card was measured.
- A device or driver fact belongs in the component's own guide, which this table links through
  [component maintenance](UPDATES-COMPONENTS.md); the row records only the class and the one result here.
