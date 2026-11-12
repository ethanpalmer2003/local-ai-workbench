# Kobold Lite audio streaming patches

| Variant | Generated patch | Controls |
| --- | --- | --- |
| PR | [lite-oai-audio-streaming.diff](lite-oai-audio-streaming.diff) | One Media **Stream audio** checkbox, off by default; native text grouping |
| Local | [kobold-lite-audio-streaming.diff](kobold-lite-audio-streaming.diff) | Detailed top-menu panel, text grouping, tone tags and backend tuning |

Both use identical `pcm_audio.js` and `kobold_audio.js` sources from `launchers/`.
The standalone audio test page loads that same PCM player directly. Generated
diffs contain copies for distribution; edit the canonical JavaScript, then
regenerate both patches. The Python serving proxy is local tooling, not in the PR.
The proxy patches Lite HTML at request time; exported diffs are separate patch artifacts, so no compiled UI directory is needed.
See the [audio delivery guide](../../audiocpp/TTS-DELIVERY.md) for transport support,
defaults and limitations.

From `C:/AI`, regenerate the minimal patch:

```powershell
python -m scripts.launchers.koboldcpp.kobold_lite --variant pr --export-diff C:/AI/scripts/launchers/koboldcpp/patches/lite-oai-audio-streaming.diff
```

Use `--variant local` with
`C:/AI/scripts/launchers/koboldcpp/patches/kobold-lite-audio-streaming.diff` for the detailed
patch. If Kobold is stopped, append `--source-file` with an unmodified Lite page. Serving without
`--export-diff` defaults to the local variant; `--variant pr` serves the minimal UI.

The current export base is installed KoboldCpp 1.123.1 Lite v349, including
embedded-server differences. Verify/rebase against the intended upstream revision
before submitting; these are reviewable patches, not a submitted pull request.
Use `git apply --check` in a matching checkout.

## PR behavior

OpenAI-compatible speech can start playing before the response finishes. Raw
HTTP PCM/WAV and SSE events share one playback pipeline. The checkbox defaults
off; enabling it uses fixed playback defaults without exposing tuning controls.
Downloads/embeds retain audio after completion. Abort and new-game actions cancel
pending requests and queued playback. Other TTS providers keep their native paths.

Validation uses mocked Web Audio/HTTP readers for split samples, WAV headers,
SSE framing, stereo, underruns, cancellation races and recordings; Lite patch
contracts preserve native text behavior. Model inference and external-backend
compatibility require separate live checks.

For a self-contained visual preview, use `--export-html <path.html>` instead of
`--export-diff`. The selected streaming controls open automatically. These previews
show the installed Lite UI; a working backend is still needed for generation.
