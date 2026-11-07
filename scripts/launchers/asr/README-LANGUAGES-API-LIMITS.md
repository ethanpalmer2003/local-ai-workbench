# ASR language options, external API and limits

Reference detail for [ASR and language practice](README.md); the backend table and launch instructions stay there.

- Language options come from the selected ASR catalog and installed Kokoro voices/resources; full model lists remain visible. Missing frontends disable options with a reason. Voice/language follow the selection; no silent English fallback. Listed support is not pronunciation validation.
- External API: `/v1/audio/transcriptions` or `/api/extra/transcribe`; JSON/base64 and multipart supported. Live microphone routes are shared by both chat gateways; see [turn settings and limits](../audiocpp/ASR-VAD.md).
- Gemma audio: mono 16 kHz preparation, strict transcription prompt, maximum 30 seconds; over-limit input rejected, no silent truncation/streaming/timestamps.
- Occupied service ports follow `LAUNCH.existing_service_policy` (`KILL` by default; `REUSE` or `ERROR` are alternatives).
