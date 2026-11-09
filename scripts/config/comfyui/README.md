# ComfyUI configuration

- Native install: `component("comfyui").framework_dir/rocm`; browser launcher: `bat/browser/comfyui/launch_comfyui.bat` and its shared bootstrap. Tuned settings and what stays unmeasured: [TUNING.md](TUNING.md).
- Known upstream conditions and their local responses: [upstream index](../../../notes/UPSTREAM.md).
- Models use typed directories under `data/videogen`, declared in [extra_model_paths.yaml](extra_model_paths.yaml) and the component map. Keep native node model fields/filenames unchanged.
- Editable workflows/node code stay here. `python -m scripts.config.sync_configs --only comfyui --apply` copies owned files into the installation; preview/apply ownership is recorded under state.
- Sync preserves replaced/removed managed files in trash, refuses missing source directories, and leaves unrelated nodes/user data intact. It does not install custom nodes or restart the server.
- Startup syncs the tracked workflow/node copies, then loads the installed node under ComfyUI's own interpreter and checks that every node type the workflows queue has its provider installed ([verify_node.py](verify_node.py)); a broken node stops the launch instead of failing mid-workflow. Native dependency/custom-node installation remains a separate fresh-machine task.

## Required custom nodes

The saved workflows name every node type they run, but a type does not name the package that provides it.
These are the providers the tracked graphs need:

| Node type | Provider |
| --- | --- |
| `UnetLoaderGGUFDynamicVRAM`, `CLIPLoaderGGUF`, `CLIPLoaderGGUFDynamicVRAM` | `molbal/ComfyUI-GGUF` |
| `LocalLTXCachedTextEncode` | this repository, synced from [ltx_prompt_cache.py](ltx_prompt_cache.py) |

The other installed nodes (`ComfyUI-Manager`, `ComfyUI-INT8-Fast-ROCM`, `comfyui-h3-sla-attention-rocm`,
`CFZ-Caching`, `CFZ-SwitchMenu`, `ComfyUI-HFRemoteVae`) do not appear in these workflows; the INT8 and H3
nodes serve weights whose workflows are not tracked here.

## LTX 2.5

- Saved workflows use model-specific text encoder, diffusion model, audio/video VAE and optional upscale/LoRA files. Exported graphs remain editable native JSON.
- Prompt caching keys on the actual encoder/request settings; cold/warm caches must be distinguished in measurements.
- Screen at square-equivalent 480, then validate useful settings at 640; longer clips, appearance/listening and autotune are separate checks.
- Tile/frame/conditioning changes alter the workload. Record decode plus total time, sampled memory and monitor overhead; do not infer scalable gains from one small sample.
- [Video benchmark and prior limits](../../benchmarks/personal/comfyui/README.md), [outcomes](../../tests/notes/OUTCOMES.md), [pending work](../../../notes/TODO.md).
- Saved variants (default, original, fast480, fast480_v3) live together in workflows/; select one with --workflow <path>. Historical benchmark results keep the paths they recorded; do not rewrite them as current defaults.
- Prompt text in save workflows is a generic LTX-2 placeholder. Personal `video.prompt` / `video.negative` (replace) or `video.prompt_append` / `video.negative_append` (extend) come from the input overlay and are applied to the installed copies during `--only comfyui --apply`, so one tracked workflow serves both.
