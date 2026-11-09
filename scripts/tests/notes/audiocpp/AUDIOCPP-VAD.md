# Silero automatic Nemotron turns

2026-10-28. Native AudioCpp Silero CPU helper plus one Vulkan Nemotron/Kokoro
server. Model asset pinned and SHA-256 verified. Threshold 0.5, silence 700 ms,
controller pre-roll 300 ms; native streaming settings use session-option scope.

## Checks

| Input | Expected / observed |
| --- | --- |
| Pure silence | Zero ASR turns; passed |
| Saved English utterance, Kokoro active | One silence-ended turn; complete transcript; passed |
| Two utterances with 350 ms internal pause | One combined turn preserving both utterances; passed |

Final transcripts arrived **0.864 / 0.865 s after the native Silero speech-end
timestamp**, including silence detection, frame scheduling and ASR completion.
These are two samples, not percentiles. The marker is the detector's estimate,
not human-labelled speech end. No explicit client commit was used to end speech;
the controller closed the ASR upload only after the native VAD speech-end event.

Native report (../../output/audiocpp/vad_turns/unreviewed/1793238226107251600/artifacts/report.json).
The report preserves raw turn events, settings, generated server config and lifecycle
phases; stdout/stderr logs preserve native VAD event timing/sample indices.
Both server models remain reported loaded afterward. Task-owned processes cleaned up.
Approved token: AppContainer false, administrator false. No packages installed.

Earlier attempts exposed two fixed defects: request options did not control
streaming Silero's session defaults, and HTTPConnection's response handling could
close a duplex upload writer. Those failed artifacts remain intact. Regression
checks cover session scope, pre-roll preservation, silence/no-ASR behavior,
lost-pre-roll rejection and Connection-close duplex upload.

Usage and integration owner: [ASR VAD guide](../../../launchers/audiocpp/ASR-VAD.md).
The standalone launcher also passes a paced saved-file check and cleans up its
owned server/helper; launcher log in `scripts/state/logs/shared/audiocpp-silero-launcher.log`.
Final validation: **347 default non-live regressions pass**, including the five
new VAD/transport contracts; types, structure/docs and code-size checks pass.
Regression log in `scripts/state/logs/shared/silero-regressions-final.log`.
Browser/microphone, Gemma, acoustic echo cancellation and multilingual/learner
quality remain separate work. This is not a latency claim for those untested paths.
