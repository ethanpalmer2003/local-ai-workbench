# Delivery and transport outcomes

Delivery, mode and transport outcomes for [Experiment outcomes](OUTCOMES.md); classification, decisions and backend screens stay there.

## Ming initial listening impressions (unreviewed)

- User found Ming 0.5B poor on longer texts; Ming Audio Tiny sounded unusually fast. The cause and whether "fast" means speech pace or generation latency are unknown; these are listening impressions, not measured results.
- With Advanced TTS overrides blank, comparison requests share the selected text and clone reference, force complete WAV output, and use each model's configured defaults. Defaults live in [AudioCpp server config](../../config/audiocpp/server.json); model-specific proxy options are in [launcher config](../../launchers/launcher_config.py). This is not a controlled latency benchmark.

## Sequential Rocinante to Breeze delivery

- Saved reply was reused after LLM generation finished; identical five-part splits did not separate narration/sentence policies. One-second buffering helped the saved sample, not a universal guarantee.
- [Delivery evidence](../output/probes/kobold_audiocpp_modes/).

## Gemma and Rocinante to Breeze 2 Q4

- Each model completed one reply, then reused it across all three modes. Gemma generation took 0.87 s. Its narration/sentence/whole TTS times were 10.02/9.88/8.61 s; RTF 0.44/0.43/0.35. Rocinante took 2.41 s to generate; TTS times were 16.18/16.10/15.35 s; RTF 0.41/0.41/0.35.
- Whole-reply mode produced audio sooner overall; sentence modes delivered first audio about 0.1 s sooner but used five requests. Replies differed in length (399 vs 725 characters). Sampled LLM process GPU allocation peaked at 3.2 GiB for Gemma and 9.3 GiB for Rocinante; peaks are approximate.
- [Gemma mode comparison](../output/llamacpp/gemma_breeze/unreviewed/1793568210170472700/artifacts/summary.md), [Rocinante mode comparison](../output/koboldcpp/kobold_audiocpp_modes/unreviewed/1793567892804776000/artifacts/summary.md).

## SSE versus raw PCM transport

- Four matched pairs produced identical PCM hashes without generated LLM load; transport timing cannot predict loaded playback. [Evidence](../output/probes/audiocpp_transport/).
