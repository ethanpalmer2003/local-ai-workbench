# AudioCpp TTS delivery and text processing

Streaming trade-offs and tone/text handling for the AudioCpp TTS runtime. Setup, install and the shared page contract live in [README.md](README.md).

## Text requests versus audio streaming

- Smaller text requests can improve first speech but add overhead and disrupt prosody. Playback buffering changes delay/underrun tolerance, not synthesis throughput.
- `tts_stream=false` favors complete replies and steadier prosody at higher time to first audio; `voice_end_delay` sets flush timing. Persistent gaps point at the frontend chunker, not synthesis.
- Match voice/model, text grouping, transport, native emission policy, seeds and actual LLM load before timing.
- [KoboldCpp Lite audio patch details](../koboldcpp/patches/README.md).

## Tone instructions and text processing

- `[Tone: cheerful] Hello!` sends spoken `Hello!` plus instruction metadata. Untagged segments inherit tone; queued changes begin new requests.
- [tts_text_processing.py](tts_text_processing.py) owns tone/vocal-event handling. Explicit client instructions take precedence.
- The supported vocal events are the vendor's own spellings from the [Breeze audio-tag table](https://docs.breezeblue.ai/guides/audio-tags), recorded with their source and retrieval date in [breeze-tts-events.json](../../config/audiocpp/breeze-tts-events.json); `scripts.config.audiocpp.tts_events` is the only reader.
- Breeze parentheticals default to unwrapped words; supported events can be normalized. Disabling this filter does not disable other proxy/Lite cleanup or guarantee a rendered vocal effect.
- Drama 3 currently uses 40 CPU expert layers and 2048 context. Its options do not transfer automatically to Breeze.
