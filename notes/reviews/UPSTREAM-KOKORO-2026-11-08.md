# Upstream drafts: Kokoro speech in Lemonade and KoboldCpp

Written 2026-11-08 from the four-arm comparison run on this machine, an RX 7800 XT under Windows.
Both were filed on 2026-11-08: [Lemonade #4111](https://github.com/lemonade-sdk/lemonade/issues/4111), [KoboldCpp #2591](https://github.com/LostRuins/koboldcpp/issues/2591). Neither text names personal data.

## Lemonade: Kokoro speaks the wrong language

Title: Kokoro TTS ignores the requested language, so French and Japanese come out wrong

- Request: `POST /v1/audio/speech` with `model: kokoro-v1`, `voice: ff_siwis` and `options.language: fr-fr`
  for a 74-character French sentence; the same call with `voice: jf_alpha`, `options.language: ja` and a
  Japanese sentence.
- Result: French returned 0.50 s of audio for a sentence that needs several seconds; Japanese returned
  13.25 s, a plausible length in English phonemes rather than Japanese.
- The bundled backend at `.cache/lemonade/bin/kokoro/cpu/koko.exe` defaults to `-l en-us` and the styles
  `af_sarah.4+af_nicole.6`, and its `espeak-ng-data` does contain `fr_dict`, `ja_dict`, `es_dict` and the
  other dictionaries. The G2P data is present, so the language and style given in the request are not
  reaching the backend.
- Ask: forward the request language to `-l` and the requested voice to `-s`, or reject a language the
  selected voice cannot speak. Expected behaviour for the calls above is French speech through
  `ff_siwis` and Japanese through `jf_alpha`.

## KoboldCpp: Kokoro is English-only

Title: Kokoro TTS returns an empty WAV for Japanese and falls back to English elsewhere

- Request: Kokoro speech through KoboldCpp's own server for the same multilingual sentences.
- Result: Japanese returned a WAV with no samples; Spanish and French were spoken with an English voice.
- The build embeds `embd_res/kokoro_ipa.embd`, an English word-to-IPA table, and no other Kokoro
  phonemizer data, so no non-English language has a grapheme-to-phoneme path. The English fallback is
  the expected consequence.
- Ask: either document Kokoro as English-only and reject other languages, or add the missing
  phonemizers. The reference behaviour is AudioCpp's Kokoro, which speaks French and Spanish correctly
  with the same weights.

## Evidence

- Run artifacts: `scripts/benchmarks/output/shared/framework_compare/unreviewed/1794123067862277200/`.
- Harness: [framework_compare.py](../../scripts/benchmarks/shared/framework_compare.py); the table records
  each row's voice, audio length and real-time factor, marking implausible speech instead of ranking it.
