"""Pool ordering, maps and the selection a character's recordings are built from."""

import random
import shutil

import requests

from scripts.config.trash import archive_path
from scripts.download.input.voice_model import (
    DOWNLOAD_TIMEOUT,
    SelectionRequest,
    accumulate,
    audio_id,
    get_duration,
    load_json,
    save_json,
)
from scripts.download.input.voice_text import clean_text, get_text, is_speech, norm_key


def sort_map(mapping, durations):
    return dict(
        sorted(
            mapping.items(),
            key=lambda x: (0 if x[1].strip() else 1, -len(x[1]) if x[1].strip() else -durations.get(x[0], 0)),
        )
    )


def load_map(cache, files, durations, excluded):
    raw = load_json(cache)
    existing = {}

    for k, v in raw.items():
        key = norm_key(k)
        value = clean_text(v)
        if value or not existing.get(key, "").strip():
            existing[key] = value

    for k, v in get_text(files).items():
        if not existing.get(k, "").strip():
            existing[k] = v

    ids = {audio_id(f) for f in files}

    renamed = sum(norm_key(k) != str(k).lower() for k in raw)
    if renamed:
        print(f"NOTE: normalized {renamed} transcript keys (e.g. stripped '.0b2' suffixes).")

    # transcripts whose key matches no audio file: stale, or a key-format mismatch
    orphans = [k for k, v in existing.items() if v.strip() and k not in ids and k not in excluded]
    if orphans:
        print(
            f"WARNING: {len(orphans)} transcripts match no audio file (key mismatch?), e.g.: {', '.join(orphans[:5])}"
        )
        print(f"  sample file ids: {', '.join(sorted(ids)[:5])}")

    for f in files:
        existing.setdefault(audio_id(f), "")

    mapping = sort_map(existing, durations)
    missing = sum(not mapping.get(audio_id(f), "").strip() for f in files)

    if missing:
        print(f"WARNING: {missing} IDs have no transcript.")
        print(f"Add transcripts to: {cache}")

    save_json(cache, mapping)
    return mapping


def download(url, path):
    with requests.get(url, headers={"User-Agent": "audiocpp-preparer"}, timeout=DOWNLOAD_TIMEOUT, stream=True) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            shutil.copyfileobj(r.raw, f)


def ordered_pool(files, mapping, mode, pinned_ids, durations):
    if mode == "pinned":
        by_id = {audio_id(f): f for f in files}
        out = []
        for x in pinned_ids:
            f = by_id.get(x.lower())
            if f is None:
                raise FileNotFoundError(f"Missing audio file: {x}")
            out.append(f)
        return out

    if mode == "random":
        pool = files[:]
        random.shuffle(pool)
        return pool

    by_id = {audio_id(f): f for f in files}

    if mode == "longestText":
        usable = {audio_id(f) for f in files if is_speech(mapping.get(audio_id(f), ""))}
        return [by_id[k] for k in mapping if k in usable]

    if mode == "longestAudio":
        usable = {audio_id(f) for f in files if not mapping.get(audio_id(f), "").strip()}
        return [by_id[k] for k in mapping if k in usable]

    if mode == "alphabeticalText":
        usable = [f for f in files if is_speech(mapping.get(audio_id(f), ""))]
        return sorted(usable, key=lambda f: f.name)

    if mode == "alphabeticalAudio":
        usable = [f for f in files if not mapping.get(audio_id(f), "").strip()]
        return sorted(usable, key=lambda f: f.name)

    raise ValueError(f"Invalid selection mode: {mode}")


def choose(files, mapping, mode, count, pinned_ids, durations):
    pool = ordered_pool(files, mapping, mode, pinned_ids, durations)
    return pool if mode == "pinned" else pool[:count]


class VoiceSelector:
    # - longestText is the primary mode: orders by transcript length, so it needs transcripts to exist
    # - longestAudio is the bootstrap mode: picks UNTRANSCRIBED clips longest-first, purely so
    #   --transcribe can fill them in; once transcripts exist, selection goes back to longestText
    MODES = frozenset(("random", "longestAudio", "longestText", "pinned", "alphabeticalText", "alphabeticalAudio"))

    def __init__(self, request: SelectionRequest):
        self.request = request
        if request.count < 0:
            raise ValueError("Selection count must not be negative")
        overlap = set(request.selected_ids) & request.excluded
        if overlap:
            raise ValueError(f"Required ID is excluded: {sorted(overlap)[0]}")

    def select(self):
        request = self.request
        by_id = {audio_id(f): f for f in request.files}
        required = []
        for x in request.selected_ids:
            if x not in by_id:
                raise FileNotFoundError(f"Required ID not found: {x}")
            required.append(by_id[x])

        used = {audio_id(f) for f in required}
        candidates = [f for f in request.files if audio_id(f) not in used]

        if request.duration_target:
            target = request.duration_target.seconds
            dur_mode = request.duration_target.mode
            total = sum(get_duration(f, request.durations) for f in required)
            if dur_mode == "max" and total > target:
                raise ValueError(f"Required clips alone exceed max duration: {total:.1f}s > {target}s")

            picked, total, cut = accumulate(
                ordered_pool(candidates, request.mapping, request.preferred, request.selected_ids, request.durations),
                request.durations,
                dur_mode,
                target,
                total,
            )
            method = request.preferred

            if total < target and request.fallback and not cut:
                print(
                    f"Preferred '{request.preferred}' reached {total:.1f}s of {target}s ({dur_mode}); using '{request.fallback}' for the rest."
                )
                used.update(audio_id(f) for f in picked)
                remaining = [f for f in candidates if audio_id(f) not in used]
                more, total, _ = accumulate(
                    ordered_pool(remaining, request.mapping, request.fallback, request.selected_ids, request.durations),
                    request.durations,
                    dur_mode,
                    target,
                    total,
                )
                if more:
                    picked += more
                    method = f"{request.preferred}+{request.fallback}"

            if dur_mode == "min" and total < target:
                raise ValueError(f"Not enough audio to reach minimum duration: {total:.1f}s < {target}s")
            return required + picked, method

        remaining = request.count - len(required)
        if remaining <= 0:
            return required[: request.count], "pinned"

        selected = choose(
            candidates, request.mapping, request.preferred, remaining, request.selected_ids, request.durations
        )
        method = request.preferred
        if len(selected) < remaining and request.fallback:
            needed = remaining - len(selected)
            print(
                f"Preferred '{request.preferred}' returned {len(selected)}/{remaining}; using '{request.fallback}' for {needed} more."
            )
            used.update(audio_id(f) for f in selected)
            candidates = [f for f in candidates if audio_id(f) not in used]
            selected += choose(
                candidates, request.mapping, request.fallback, needed, request.selected_ids, request.durations
            )
            method = f"{request.preferred}+{request.fallback}"
        return required + selected, method


def select(request: SelectionRequest):
    return VoiceSelector(request).select()


def _selection_manifest_matches(manifest, current, selected_dir, keys):
    old = load_json(manifest)
    if not old or not all(old.get(k) == current[k] for k in keys):
        return None
    if not all((selected_dir / f["name"]).is_file() for f in old.get("files", [])):
        return None
    return old


def _materialize_selection(selected_dir, manifest, desired, current):
    current["files"] = [{"id": audio_id(f), "name": f.name} for f in desired]
    archive_path(selected_dir, selected_dir.parent)
    selected_dir.mkdir()
    for f in desired:
        shutil.copy2(f, selected_dir / f.name)
    save_json(manifest, current)
