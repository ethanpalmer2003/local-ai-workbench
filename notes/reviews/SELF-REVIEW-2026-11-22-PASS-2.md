# Self review pass 2 - 2026-11-22

Second pass over the same tree against [code rules](../../.agents/CODE.md) and [review questions](../../.agents/REVIEW.md);
the first pass is [self review](SELF-REVIEW-2026-11-22.md). Twenty commits, `56def33..7c5a2af`; every batch passed
the scoped gate and suite, and the closing full validation ran five stages in 316.6 s.

## Config and generated data

1. `catalog.render_ids` defaulted to the overlay-inclusive `MODELS`, so a caller omitting its argument would render
   private overlay labels into the tracked `ids.py`. The writer and `ids_match` already passed `overlay=False`, and
   `ids_match()` was true before the fix; the default is tracked-only now and a test pins it.
2. `_destination` accepted a `filename` that disagreed with its `destination`, so a download and an install path
   could name different files. Validation refuses the pair now; all 69 entries already matched.
3. `model_sync` read every captured config as strict UTF-8, so one undecodable config aborted the model audit; it
   decodes with replacement.

## Checks and documents

1. `expression` counted nesting below the root while describing operators, allowing one level more than the rule.
   It measures the documented three levels now; the one offender in `rename_path` names its predicate.
2. `docs` recognized untracked link targets only by folder name, so a link into the ignored `state/` tree passed.
   A link must reach a git-tracked file, or a folder holding tracked files; the one offender, the untracked
   guard-plugin path in [restrictions](../../.agents/RESTRICTIONS.md), is cited as plain text.
3. `line_length` counted accepted lines over the whole tree on a scoped run; one target list serves both now.
   `typography` and `spellings` carried the same corpus mask twice, owned once in `lists/text_files.py`.
4. `frontend_wiring` scraped injected settings keys with a regex a nested dict would cut short; it reads the tree
   now and has a test module. `annotations` skipped positional-only defaults.
5. `specspeed` silently dropped prompts written as bare strings and raised `StopIteration` when `PROMPTS` was
   absent; both shapes are read and a missing assignment names its cause.

## Benchmarks and proxies

1. `benchmark_backends` crashed its summary on an arm with no rows and wrote no report when a round failed. An
   unmeasured arm is null, pairs compare only when both sides measured, and a failed run writes `status: failed`.
2. `whisper_embedded_compare` aborted the whole table when one engine had no sample for a clip; the cell reads
   `unavailable`. The same guard stops a missing WER from being formatted as a percentage.
3. `tts_proxy` turned a mislabelled WAV into a proxy 500 and dropped non-speech relay failures; the duration is
   optional and the relay answers when its headers have not gone out.
4. The ASR gateway and live sessions kept two origin rules and refused `localhost` against a `127.0.0.1` host;
   one `proxy_util.same_workspace_origin` serves both. `build_frameworks` bounds a foreground build at an hour.

## Unguarded and deferred

Live-runner failure paths, the build bound, `model_sync` decoding and flag drift in documents have no automated
guard; the process failures this pass hit are rows in [failures](../../.agents/FAILURES.md). The first pass's
three deferrals stand: the two import rewriters, the profile runner lifecycle, and the typed speech labels.
