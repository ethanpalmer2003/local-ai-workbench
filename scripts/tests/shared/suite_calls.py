"""How many model requests each live target makes in one suite run, so its cost is a declared number.

One repeat is what `quick_validation.PROBES` asks for; a benchmark run defaults to two. A target whose
request count is not a fixed number is listed in `STREAMED` with the reason, because a streamed scenario
cannot be counted without instrumenting it.
"""

# - one warmup per arm is included: it pays the model load and is excluded from the timings
BACKEND_CALLS: dict[str, int] = {
    "parakeet": 4,
    "practice-whisper": 4,
    "practice-qwen": 2,
    "gemma": 6,
    "images": 1,
    "ming3-tts": 1,
}

LAUNCHER_CALLS: dict[str, int] = {"sdcpp": 1, "audiocpp": 1, "llamacpp": 1, "kobold": 1}

# - a streamed gateway pass posts one block per 4096 bytes and polls until the transcript closes
STREAMED: frozenset[str] = frozenset({"practice"})
