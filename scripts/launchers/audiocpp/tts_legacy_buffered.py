"""Retired TTS pipeline; not imported by active launchers or tests.

Preserved in this file for usefulness review before removal.

- Text batching: OFF, LIMIT (word/character limits), or STOP (sentence boundaries);
  withheld fragments return no audio until a batch is ready.
- Quote-only filtering: optional state across text chunks, idle reset, test-prefix
  bypass, and a configurable pause between narration and dialogue. Off by default.
- WAV silence trimming: leading/trailing RMS-based trimming with optional padding;
  requires the complete WAV. Not used on PCM streams.
- Playback pacing: delays complete-WAV responses using their durations and a
  configurable inter-clip margin. The streaming browser schedules its own audio.
- PlaybackQueue: former request ordering and duration-based response pacing.
- RMS/wave helpers support the retired silence-processing code.

Complete-WAV requests now use the active HTTP relay without this pipeline. Shared text cleanup and
Breeze 2 tone/vocal-event processing live in tts_text_processing.py, not this legacy pipeline.
"""

from __future__ import annotations

import contextlib
import re
import threading
import time
import traceback
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from threading import Condition, Lock

from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import tts_text_processing

SILENCE_CHUNK_SECONDS = 0.02
SILENCE_RMS_THRESHOLD = 300


# --- legacy buffered-only: quote selection/state; bypassed by audio streaming ---
# - When enabled, only text inside "double quotes" is spoken (narration is
#   dropped)
# - Quote state is tracked across streamed chunks
@dataclass
class AudiocppQuoteSettings:
    enabled: bool = False

    # - Pause (s) before a dialogue line that follows narration
    # - Generation time counts toward it, so slow generation can make it a no-op
    # - See QuoteState below
    # - NOTE: at nonzero values it seemed to compound over long sessions;
    #   0.0 disables it.
    dialogue_end_pause: float = 0.0

    # - Requests starting with these skip quote filtering (for testing) and the
    #   chunk buffer
    always_play_prefixes: list[str] = field(default_factory=lambda: ["Hello there, this is a test."])

    # - Quote state resets after this many idle seconds
    reset_timeout: float = 5.0


AUDIOCPP_PROXY_QUOTES = AudiocppQuoteSettings()


# --- legacy buffered-only: proxy text batching; streaming client owns text requests ---
# - holds streamed chunks (answered 204) until enough text piles up, then one
#   combined request to audio.cpp
# - kobold narration streaming splits where a punctuation run (. ? ! ... ?!) is
#   followed DIRECTLY by whitespace; confirmed in OFF-mode tests with a fixed
#   paragraph
#   - splits: "huh? bravo", "Wait... echo", "Wait?! golf", "nodded. It"
#   - never splits when a closing quote sits between the punctuation and the
#     space, for every punctuation type: '?" alpha', '!" charlie', '..." delta',
#     '." foxtrot' all stay in one chunk with the words after them
#   - never splits mid-token: "3.5", "amazon.com"
#   - no other exceptions: abbreviations ("mr. "), ellipses ("hello... "), and
#     newlines all split; "?" and "..." behave exactly like "."
#   - markdown asterisks are gone before the proxy sees the text ("*Sighs.*"
#     arrives as "Sighs."), so that splits like a plain sentence
#   - STOP mode reassembles those fragments and re-splits per the rules below
# modes:
#   OFF   - every chunk is its own request
#   LIMIT - fire at max_words or max_chars
#   STOP  - fire at a sentence ending, up to the last one (rest stays
#           buffered); ending only counts once text before it meets
#           stop_min_words/stop_min_chars, else max_words/max_chars fire it
#           anyway
# - limits checked between chunks; words are never cut
class AudiocppBufferMode(str, Enum):
    OFF = "off"
    LIMIT = "limit"
    STOP = "stop"


@dataclass
class AudiocppBufferSettings:
    # checks run per chunk in field order below
    # - stop tokens checked FIRST and WIN: a valid ending fires immediately,
    #   even past max_words/max_chars (6-word sentence, max_words=5 -> plays
    #   whole)
    # - size limits are the backstop for text with no valid ending
    # - requires properly punctuated text (. ? !):
    #   max_words=0 -> no backstop at all; max_words>1 -> ending-less text held
    #   until backstop/stop token; either way text without punctuation can
    #   stay buffered until more text arrives (never dropped)
    #   max_words=1 -> fires every chunk unconditionally
    mode: AudiocppBufferMode = AudiocppBufferMode.OFF

    # characters that end a sentence (STOP mode); checked first, wins over
    # size limits
    stop_tokens: list[str] = field(default_factory=lambda: [".", "?", "!"])
    # case-insensitive regexes
    # - a stop overlapping a match is ignored (not a sentence ending)
    # - delete an entry to make that case a stop again
    stop_exceptions: list[str] = field(
        default_factory=lambda: [
            r"\.{2,}",  # ellipsis "..." (also "?...")
            r"\u2026",  # unicode ellipsis (only matters if added to stop_tokens)
            r"\d\.\d",  # decimals: 3.5, v1.2
            r"[a-z]\.[a-z]",  # mid-word dots: site.com, file.txt
            r"\b(?:[a-z]\.){2,}",  # e.g. / i.e. / U.S.A.
            r"\b(?:mr|mrs|ms|dr|prof|sr|jr|st|vs)\.",  # titles/abbreviations
        ]
    )

    # size backstop (0 disables); only reached when no valid ending above
    # - at the limit the whole buffer fires (never cut mid-chunk to fit)
    max_words: int = 10  # main limit
    max_chars: int = 0  # loose backstop
    # STOP-only minimum for a sentence ending to fire
    # - ending on shorter text is ignored (stays buffered until more arrives)
    # - never cuts text
    stop_min_words: int = 4
    stop_min_chars: int = 0

    # inserted between chunks (not before punctuation-only chunks)
    # - " " suits word/sentence chunks; "" suits raw sub-word tokens
    joiner: str = " "
    # buffered text idle this long is only logged as stale on the next request;
    # it is never dropped - the tail is spoken ahead of the new text
    stale_seconds: float = 15.0


AUDIOCPP_PROXY_BUFFER = AudiocppBufferSettings()


# --- legacy buffered-only: WAV trimming and duration pacing; streaming player owns buffering ---
@dataclass
class AudiocppPlaybackSettings:
    # - Hold responses back to match audio duration so clips never overlap
    pace: bool = True
    margin: float = 0.0  # extra seconds between clips (-0.2 = slight overlap)

    # - Crop dead air off returned clips
    # - Leading trim is off by default (it can clip the start of the first word)
    trim_leading_silence: bool = False
    trim_trailing_silence: bool = True

    # - Seconds of quiet kept on each side when trimming, so a cut isn't abrupt
    silence_pad_seconds: float = 0.1


AUDIOCPP_PROXY_PLAYBACK = AudiocppPlaybackSettings()


class QuoteState:
    def __init__(self):
        self._lock = threading.Lock()
        self.in_quotes = False
        self.pending_pause = False
        self.last_activity_time = 0.0
        self.busy_until = 0.0

    def extend_busy(self, seconds: float) -> None:
        with self._lock:
            self.busy_until = max(self.busy_until, time.monotonic() + seconds)

    def checkpoint(self) -> tuple[bool, bool, float, float]:
        with self._lock:
            return self.in_quotes, self.pending_pause, self.last_activity_time, self.busy_until

    def restore(self, state: tuple[bool, bool, float, float]) -> None:
        with self._lock:
            self.in_quotes, self.pending_pause, self.last_activity_time, self.busy_until = state

    def process(self, text: str) -> tuple[str, float]:
        if not AUDIOCPP_PROXY_QUOTES.enabled:
            # - Normal mode leaves quote handling disabled
            # - Character stripping still runs afterward in _transform
            return text, 0.0
        return self._process_quotes(text)

    def _process_quotes(self, text: str) -> tuple[str, float]:
        with self._lock:
            now = time.monotonic()
            last_state_time = max(self.last_activity_time, self.busy_until)
            if now - last_state_time > AUDIOCPP_PROXY_QUOTES.reset_timeout:
                self.in_quotes = False
                self.pending_pause = False
            self.last_activity_time = now

            pause_to_apply = AUDIOCPP_PROXY_QUOTES.dialogue_end_pause if self.pending_pause else 0.0
            self.pending_pause = False

            stripped_input = text.strip()
            if any(stripped_input.startswith(prefix) for prefix in AUDIOCPP_PROXY_QUOTES.always_play_prefixes):
                return text, pause_to_apply

            final_output = []
            for char in text:
                if char == '"':
                    if not self.in_quotes:
                        self.in_quotes = True
                    else:
                        self.in_quotes = False
                        self.pending_pause = True
                    continue

                if self.in_quotes:
                    final_output.append(char)

            cleaned = "".join(final_output)
            return cleaned, pause_to_apply


quote_state = QuoteState()


class ChunkBuffer:
    """
    - Accumulates streamed text chunks until a limit or sentence ending is hit
    - add() returns the text to speak now, or None to keep waiting
    - Called from the ordered transform stage, so chunks arrive in order
    - All tuning lives in AUDIOCPP_PROXY_BUFFER
    """

    def __init__(self, settings: AudiocppBufferSettings | None = None):
        self.settings = settings or AUDIOCPP_PROXY_BUFFER
        self._lock = threading.Lock()
        self.text = ""
        self.last_update = 0.0

    @staticmethod
    def _words(text: str) -> int:
        # - Punctuation-only tokens ("...", "-") aren't words
        return sum(1 for t in text.split() if any(c.isalnum() for c in t))

    @staticmethod
    def _is_punct_only(text: str) -> bool:
        return bool(text.strip()) and not any(c.isalnum() for c in text)

    def _stop_regex(self) -> re.Pattern[str] | None:
        # - A run of stop chars ("?!") is ONE candidate ending
        # - Trailing closers like  ." *  stay with their sentence
        if not self.settings.stop_tokens:
            return None
        chars = "".join(re.escape(t) for t in self.settings.stop_tokens)
        return re.compile(rf"(?P<run>[{chars}]+)[\"'\u201d\u2019)\]*_]*")

    def _stop_ends(self) -> list[int]:
        """
        - End offsets of every usable sentence ending in the buffer
        """
        regex = self._stop_regex()
        if regex is None:
            return []
        blocked = [
            m.span()
            for pattern in self.settings.stop_exceptions
            for m in re.finditer(pattern, self.text, re.IGNORECASE)
        ]
        ends = []
        for m in regex.finditer(self.text):
            start, end = m.span("run")
            if any(b_start < end and start < b_end for b_start, b_end in blocked):
                continue
            ends.append(m.end())
        return ends

    def _over_max(self) -> bool:
        s = self.settings
        return bool(
            (s.max_words and self._words(self.text) >= s.max_words) or (s.max_chars and len(self.text) >= s.max_chars)
        )

    def _take_until_last_stop(self) -> str | None:
        ends = self._stop_ends()
        if not ends:
            return None
        end = ends[-1]
        head = self.text[:end]
        # - Earlier endings only have smaller prefixes, so checking the last is enough
        if self._words(head) < self.settings.stop_min_words or len(head) < self.settings.stop_min_chars:
            return None
        self.text = self.text[end:].lstrip()
        return head

    def _take_all(self) -> str:
        out, self.text = self.text, ""
        return out

    def add(self, chunk: str) -> str | None:
        s = self.settings
        if s.mode == AudiocppBufferMode.OFF:
            return chunk

        with self._lock:
            now = time.monotonic()
            if self.text and now - self.last_update > s.stale_seconds:
                # - never drop: the tail stays and is spoken ahead of this text
                print(f"[audiocpp-proxy] buffer: stale tail kept, speaking with next text {self.text[:60]!r}")
            self.last_update = now

            if not self.text and self._is_punct_only(chunk):
                # - Trailing bit of an ellipsis/"?!" whose sentence already fired
                return None

            glue = self.text and not self.text[-1].isspace() and not chunk[:1].isspace()
            if glue and not self._is_punct_only(chunk):
                self.text += s.joiner
            self.text += chunk

            out: str | None = None
            if s.mode == AudiocppBufferMode.STOP:
                out = self._take_until_last_stop()
            if out is None and self._over_max():
                out = self._take_all()

            if out is None:
                print(f"[audiocpp-proxy] buffer: holding {self._words(self.text)} words / {len(self.text)} chars")
            return out


chunk_buffer = ChunkBuffer()


def _apply_buffer(payload: dict[str, object]) -> bool:
    """
    - Swap payload['input'] for buffered text
    - False = keep waiting
    """
    text = payload.get("input")
    if not isinstance(text, str):
        return True  # Shared text cleanup rejects non-strings.
    if text.strip().startswith(tuple(AUDIOCPP_PROXY_QUOTES.always_play_prefixes)):
        return True
    ready = chunk_buffer.add(text)
    if ready is None:
        return False
    payload["input"] = ready
    return True


def transform_text(
    payload: dict[str, object],
    preset: cfg.AudiocppProxyRequestModelPreset | None,
    cleanup: Callable[[dict[str, object]], tuple[str | None, float]],
) -> tuple[dict[str, object], float] | None:
    tone_enabled = payload.get("model") in cfg.BREEZE_MODELS
    if tone_enabled:
        tts_text_processing.apply_breeze_tone(payload)
    text = payload.get("input")
    if not isinstance(text, str):
        return None
    checkpoint = quote_state.checkpoint()
    quoted, pause = quote_state.process(text)
    payload["input"] = quoted
    cleaned, _ = cleanup(payload)
    if cleaned is None:
        quote_state.restore(checkpoint)
        return None
    if preset and preset.prepend:
        cleaned = preset.prepend + cleaned
    payload["input"] = cleaned
    return payload, pause


def _rms(chunk: bytes, width: int) -> float:
    """
    - Legacy buffered-only silence analysis; streaming does not import NumPy
    - audioop.rms, which PEP 594 removed from the stdlib in 3.13
    - every width is signed little-endian, matching audioop (verified against
      it on 3.12); audioop returned a truncated int, this returns the float,
      so the two differ by under 1 at the cutoff above
    """
    import numpy as np

    if width in (1, 2, 4):
        values = np.frombuffer(chunk, dtype=f"<i{width}").astype(np.float64)
    else:
        samples = [
            int.from_bytes(chunk[i : i + width], "little", signed=True) for i in range(0, len(chunk) - width + 1, width)
        ]
        values = np.array(samples, dtype=np.float64)

    return float(np.sqrt(np.mean(np.square(values)))) if values.size else 0.0


def _trim_silence(
    data: bytes, trim_leading: bool, trim_trailing: bool, pad_seconds: float
) -> tuple[bytes, float, float]:
    """
    - Legacy buffered-only; native streams never enter this helper
    - Optionally crops dead air off the start and/or end of a WAV clip
      (keeping pad_seconds so a cut isn't abrupt)
    - Only ever trims past the first/last loud chunk - a real mid-clip pause
      (e.g. a dialogue beat) is never touched
    - Returns (trimmed_wav_bytes, raw_duration, trimmed_duration)
    - Falls back to the original bytes if nothing can be parsed or there's
      nothing to trim
    - Leading trim is riskier than trailing: cut too aggressively and you clip
      the start of the first word instead of just losing dead air - hence it's
      off by default
    """
    try:
        with wave.open(BytesIO(data), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            pcm = wav.readframes(frames)
    except Exception:
        traceback.print_exc()
        return data, 0.0, 0.0

    raw_duration = frames / rate if rate else 0.0
    if not rate or not (trim_leading or trim_trailing):
        return data, raw_duration, raw_duration

    frame_bytes = width * channels
    chunk_bytes = int(rate * SILENCE_CHUNK_SECONDS) * frame_bytes
    pad_bytes = int(rate * pad_seconds) * frame_bytes

    loud_starts_ends = []
    try:
        for i in range(0, len(pcm), chunk_bytes):
            chunk = pcm[i : i + chunk_bytes]
            if chunk and _rms(chunk, width) > SILENCE_RMS_THRESHOLD:
                loud_starts_ends.append((i, i + len(chunk)))
    except Exception:
        traceback.print_exc()
        return data, raw_duration, raw_duration

    if not loud_starts_ends:
        return data, raw_duration, raw_duration  # entirely silent or failed - leave as-is

    start_at = 0
    if trim_leading:
        start_at = max(0, loud_starts_ends[0][0] - pad_bytes)
        start_at -= start_at % frame_bytes  # keep sample-aligned

    cut_at = len(pcm)
    if trim_trailing:
        cut_at = min(len(pcm), loud_starts_ends[-1][1] + pad_bytes)

    if start_at == 0 and cut_at >= len(pcm):
        return data, raw_duration, raw_duration  # nothing worth trimming

    trimmed_pcm = pcm[start_at:cut_at]
    out = BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(trimmed_pcm)
    trimmed_duration = len(trimmed_pcm) / frame_bytes / rate
    return out.getvalue(), raw_duration, trimmed_duration


class PlaybackQueue:
    """Arrival ordering and legacy complete-WAV pacing; no audio decoding or HTTP."""

    def __init__(self, playback: AudiocppPlaybackSettings):
        self.playback = playback
        self.playback_lock = Lock()
        self.playback_cv = Condition(self.playback_lock)
        self.transform_cv = Condition(Lock())
        self.next_play_time = 0.0
        self.next_ticket = 0
        self.next_to_schedule = 0
        self.next_transform_ticket = 0

    def get_ticket(self) -> int:
        """
        - Hand out a ticket for this request's arrival order
        - Call before the upstream/generation call, not after
        """
        with self.playback_lock:
            t = self.next_ticket
            self.next_ticket += 1
        return t

    @contextlib.contextmanager
    def transform_turn(self, ticket: int):
        # - body reads and transforms share one cleanup path, including failed reads
        with self.transform_cv:
            while ticket != self.next_transform_ticket:
                self.transform_cv.wait()
            try:
                yield
            finally:
                self.next_transform_ticket += 1
                self.transform_cv.notify_all()

    def release_ticket(self, ticket: int) -> None:
        """
        - Give up a ticket without reserving a playback slot (skip/error path)
        - Must be called for every ticket that skips schedule_playback, or
          later tickets wait forever
        """
        with self.playback_cv:
            while ticket != self.next_to_schedule:
                self.playback_cv.wait()
            self.next_to_schedule += 1
            self.playback_cv.notify_all()

    def schedule_playback(self, ticket: int, pause_before: float, audio_duration: float) -> tuple[float, float]:
        """
        - Reserve this clip's slot on the shared playback timeline
        - Returns (wait_time, queue_ahead): wait_time is how long to sleep
          before sending it; queue_ahead is the resulting backlog (seconds of
          queued audio still ahead of "now"), useful for telling a one-off
          backlog apart from one that keeps growing
        - Clips never overlap - each starts no earlier than the previous one's
          estimated end, plus pause_before if generation didn't already cover it
        - Served strictly in ticket (arrival) order so a fast-generating later
          line can't jump ahead of an earlier one
        """
        with self.playback_cv:
            while ticket != self.next_to_schedule:
                self.playback_cv.wait()

            now = time.perf_counter()
            playback_start = max(now, self.next_play_time)
            if pause_before:
                playback_start = max(playback_start, self.next_play_time + pause_before)
            wait_time = max(0.0, playback_start - now)
            self.next_play_time = playback_start + audio_duration + self.playback.margin
            queue_ahead = self.next_play_time - now

            self.next_to_schedule += 1
            self.playback_cv.notify_all()
        return wait_time, queue_ahead
