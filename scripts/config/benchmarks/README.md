# Benchmark corpus manifest

`language_corpus.json` pins the clips a language run speaks and hears: the corpus revision, the split, and each selected clip's archive member and reference text.

- The revision and the member paths are pinned together, so a run compares the same audio after the upstream dataset moves. The fetcher extracts only the listed members: `python -m scripts.download.benchmarks.fleurs --download`.
- `manifest_sha256` is this file's own digest, recorded in run provenance. Editing any clip marks an earlier run's corpus stale instead of silently mixing audio.
- The selection rule and clip count are the file's own `selection` and `clips` fields. Reader: [fleurs.py](../../download/benchmarks/fleurs.py). Run side: [language_corpus.py](../../benchmarks/shared/language_corpus.py).
