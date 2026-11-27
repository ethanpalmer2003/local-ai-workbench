# Local overlay

Files this repository reads from outside git. Code stays here; the files it consumes live in the
overlay. One module owns every path: [local_overlay.py](../local_overlay.py), imported as `overlay`.
Nothing else reads `AI_INPUT_DIR`, `AI_VOICES_DIR` or `data/input` directly, so `grep -rn local_overlay`
lists every consumer.

| Group | Functions |
| --- | --- |
| Roots and paths | `input_dir`, `voices_dir`, `voice_dir`, `kobold_dir`, `prompts_dir`, `voice_sources_path`, `overrides_path`, `model_overlay_path`, `private_audit_script` |
| Voice manifest | `voice_ids`, `superseded_voices`, `default_voice` |
| Text assets | `character_cards`, `tone_prompt` |
| Defaults | `overrides`, `setting` |

- Location: `data/input/` by default, or the path in `AI_INPUT_DIR`.
- Layout: `voice_sources.yaml` (voice ids and download sources), `defaults.yaml` `chat.tts.voice` (the default voice), `kobold/` (character cards and saved scenarios), `prompts/` (tone instructions).
- Clips are assets, not overlay config: `data/voices/<id>/` by default, or `AI_VOICES_DIR`; like weights they are downloaded, so a backup of the overlay stays small.
- Absent overlay: voice cloning reports nothing available, the voice pipeline has no entries, and launchers still start. No code change is needed to take the inputs out or put them back.
- Voice pipeline: `python -m scripts.download.input.get_tts_voices --characters <id> ...` reads its sources from the manifest; nothing is hard-coded per character. The manifest shape is [voice_sources.example.yaml](../voice_sources.example.yaml), placeholders only: copy it into the overlay and fill in real ids.
- `models.overlay.yaml` holds extra model catalog entries and merges into the catalog when present. The tracked `catalog.json` and generated `ids.py` never carry them.
- `tools/private_audit.py` is the overlay's scan of this repository: the gate runs it on every change, and `python -m scripts.review --scrub` runs it over the tree and the history before a publish. `tools/scrub.py` writes the rewrite rules and drives a history rewrite from the same vocabulary. Both live here, so the public tree names none of their categories or terms; without the overlay the gate reports the section as skipped.
- `defaults.yaml` is where personal selection happens: `chat.llm`, `chat.tts.model`, `chat.tts.voice`, `chat.tts.instruction`, `chat.sampler`, `image.prompt`, `image.loras`, and the `video.*` pair: `video.prompt`/`video.negative` replace the workflow text, `video.prompt_append`/`video.negative_append` add to it. Chat keys belong to the chat stack that is always started; `image.*` only affects the optional image proxy. A missing key, wrong type or malformed file keeps the repository default; comments are ordinary YAML.
- `chat.sampler` maps a catalog label to llama-server sampler flags (`temperature`, `top_p`, `repeat_penalty`, `presence_penalty`, `frequency_penalty`) for the no-model arm, merged over the repository defaults; an explicit Lite UI slider still wins.
- Flags exist for one-off runs and automation (`--model`, `--with-image`, `--config`); they override one launch and never become the configuration. Service policy, ports and paths stay code-owned in both cases.
- Never add these files to git; `data/` is ignored.

## Voice ids

- Ids are the manifest keys; the default is its `default` field, else the first id. A superseded id sorts last in the id list, so a picker opens on a current voice and a superseded one never becomes the positional default.
- Per-voice fields: `url` and `count` fetch and cap the clips; `selection` and `fallback` name the pick order (`longestText`, `longestAudio`, `alphabetical*`, `random`, `pinned`). `selected` lists clip ids that must be used and `exclude` bans clip ids, both applied when clips are prepared into `generated/selected/`; a missing id or one in both lists fails the run. `pinned` takes exactly the `selected` list and ignores `count`. `superseded_by` names the id that replaced this one: the clips stay usable and the pipeline prints the replacement instead of hiding it, so an older take can still be prepared for comparison. Demotion only: a superseded id sorts last and is never rejected.
- `AUDIOCPP_PROXY_CLONE_VOICES` and `DEFAULT_AUDIOCPP_PROXY_VOICE` read the overlay once at import, so restart a launcher after changing it.
