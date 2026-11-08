# Local inputs

Personal audio and prompt inputs live outside the repository. Code stays here; the files it consumes live in the overlay.

- Location: `data/input/` by default, or the path in `AI_INPUT_DIR`. Loader: [inputs.py](../overlay_inputs.py).
- Layout: `voice_sources.json` (voice ids, chosen default, download sources), `kobold/` (character cards and saved scenarios), `prompts/` (tone instructions), `.commandcode/` (personal Command Code settings and taste profiles).
- Clips are assets, not overlay config: `data/voices/<id>/` by default, or `AI_VOICES_DIR`; like weights they are downloaded, so a backup of the overlay stays small.
- Absent overlay: voice cloning reports nothing available, the voice pipeline has no entries, and launchers still start. No code change is needed to take the inputs out or put them back.
- Voice pipeline: `python -m scripts.download.input.get_tts_voices --characters <id> ...` reads its sources from the manifest; nothing is hard-coded per character. The manifest shape is [voice_sources.example.json](../voice_sources.example.json), placeholders only: copy it into the overlay and fill in real ids.
- `models.private.json` holds extra model catalog entries (character LoRAs, private checkpoints) and merges into the catalog when present. The tracked `catalog.json` and generated `ids.py` never carry them.
- `python -m scripts.config.sync_configs --only commandcode --apply` points the ignored `.commandcode/` at the overlay folder with a directory junction, so one physical copy exists. A real folder in the way is archived first; without `--apply` it only reports.
- `defaults.json` is where personal selection happens: `chat.llm`, `chat.tts.model`, `chat.tts.voice`, `chat.tts.instruction`, `image.prompt`, `image.loras`, and the `video.*` pair: `video.prompt`/`video.negative` replace the workflow text, `video.prompt_append`/`video.negative_append` add to it. Chat keys belong to the chat stack that is always started; `image.*` only affects the optional image proxy. A missing key, wrong type or malformed file keeps the repository default; `//` comments are allowed.
- Flags exist for one-off runs and automation (`--model`, `--with-image`, `--config`); they override one launch and never become the configuration. Service policy, ports and paths stay code-owned in both cases.
- Never add these files to git. `data/` is ignored, so the overlay can live directly in the working tree.

## Voice ids

- Ids are the manifest keys; the default is its `default` field, else the first id.
- `AUDIOCPP_PROXY_CLONE_VOICES` and `DEFAULT_AUDIOCPP_PROXY_VOICE` read the overlay once at import, so restart a launcher after changing it.
