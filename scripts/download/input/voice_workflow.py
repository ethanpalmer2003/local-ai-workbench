"""Transcription, wav assembly, preparation, cleanup and validation for one character."""

import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Any

from scripts.config.trash import archive_path
from scripts.download.input.voice_model import (
    CHARACTER_CONFIGS,
    DATA,
    DEFAULT_DUR_TARGET,
    CharacterConfig,
    CharacterWorkspace,
    DurationTarget,
    PreparationResult,
    SelectionRequest,
    SelectionResult,
    audio_id,
    duration,
    get_duration,
    hash_data,
    load_durations,
    load_json,
    record_source,
    roots,
    save_json,
    voice_files,
)
from scripts.download.input.voice_selection import (
    _materialize_selection,
    _selection_manifest_matches,
    download,
    load_map,
    select,
    sort_map,
)
from scripts.download.input.voice_text import clean_text, get_text, is_speech, norm_key
from scripts.launchers.asr.llamacpp import qwen3_asr
from scripts.launchers.shared.services.process import stop_owned
from scripts.launchers.shared.transport.multipart import audio_upload


def get_selection(selected_dir: Path, request: SelectionRequest):
    manifest = selected_dir / "selection.json"
    inventory = sorted((audio_id(f), f.name) for f in request.files)

    current = {
        "selection": request.preferred,
        "fallback": request.fallback,
        "method": None,
        "count": request.count,
        "duration_target": request.duration_target.as_json() if request.duration_target else None,
        "constraints": {"selected": request.selected_ids, "excluded": sorted(request.excluded)},
        "mapping": hash_data(request.mapping),
        "inventory": hash_data(inventory),
    }

    keys = ("selection", "fallback", "count", "duration_target", "constraints", "mapping", "inventory")

    old = _selection_manifest_matches(manifest, current, selected_dir, keys)
    if old is not None:
        print(f"Selected files match current preferences; reusing '{old['method']}'.")
        return SelectionResult([selected_dir / f["name"] for f in old["files"]], old["method"])

    desired, method = select(request)

    current["method"] = method
    _materialize_selection(selected_dir, manifest, desired, current)
    return SelectionResult([selected_dir / f.name for f in desired], method)


def transcribe_file(f, mapping, tmp):
    key = audio_id(f)
    audio = tmp / f"{key}.wav"
    txt = tmp / f"{key}.txt"

    print(f"Transcribing: {f.name}")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(f), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(audio)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    body, content_type = audio_upload(audio.read_bytes(), {"response_format": "json", "language": "auto"})
    result, response_type = qwen3_asr.transcribe(body, content_type)
    if "application/json" in response_type:
        payload = json.loads(result)
        transcript = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(transcript, str):
            raise RuntimeError(f"Qwen ASR returned no transcript for {f.name}")
    elif response_type.startswith("text/plain"):
        transcript = result.decode("utf-8", errors="replace")
    else:
        raise RuntimeError(f"Qwen ASR returned unsupported content type {response_type!r} for {f.name}")

    txt.write_text(transcript, encoding="utf-8")
    text = clean_text(transcript)
    if text:
        mapping[key] = text
        print(f"  {text}")
    else:
        print(f"  WARNING: empty transcription for {key}")


def transcribe(files, mapping, cache, durations, excluded):
    tmp = cache.parent / "stt_tmp"
    archive_path(tmp, cache.parent)
    tmp.mkdir()
    server_process = None
    server_ready = False

    try:
        for f in files:
            key = audio_id(f)
            if mapping.get(key, "").strip():
                print(f"Skipping existing transcript: {f.name}")
                continue
            if not server_ready:
                server_process = qwen3_asr.start()
                server_ready = True
            transcribe_file(f, mapping, tmp)
    finally:
        try:
            if server_process is not None:
                stop_owned(server_process)
        finally:
            archive_path(tmp, cache.parent)

    mapping = sort_map(mapping, durations)
    save_json(cache, mapping)
    return mapping


def build_wav(files, mapping, workspace, count, duration_target=None):
    if not files:
        raise ValueError("No files selected. Candidates may exceed the max duration budget.")

    wav = workspace.wav_path(duration_target, count)
    reference = workspace.reference_path(duration_target, count)

    reference.write_text(" ".join(mapping[audio_id(f)] for f in files), encoding="utf-8")

    inputs = [x for f in files for x in ("-i", str(f))]
    filt = "".join(f"[{i}:a]" for i in range(len(files)))
    filt += f"concat=n={len(files)}:v=0:a=1[out]"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filt,
            "-map",
            "[out]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ],
        check=True,
    )

    length = duration(wav)

    print(f"Selected: {len(files)}")
    print(f"WAV: {wav}")
    print(f"Reference: {reference}")
    print(f"Length: {length:.1f}s")

    return wav, length


def ensure_sources(config: CharacterConfig, workspace: CharacterWorkspace) -> Path:
    """Sources = the character directory as-is (never reorganized).
    - if there's no source audio yet and a url is configured, fetch the zip and extract it
      into a subfolder named after the zip - same as a manual extract
    """
    directory = workspace.directory
    generated = workspace.generated
    for f in directory.rglob("*"):
        if f.is_file() and generated not in f.parents and f.suffix.lower() in (".ogg", ".wav", ".mp3"):
            print("DOWNLOAD MODE OFF (sources already present)")
            record_source(config, workspace)
            return directory

    if not config.url:
        raise FileNotFoundError(
            f"No source audio under {directory} and no url configured to fetch one - populate it manually."
        )
    print("DOWNLOAD MODE ON")
    generated.mkdir(parents=True, exist_ok=True)
    download(config.url, workspace.archive)
    record_source(config, workspace)
    target = directory / workspace.archive.stem
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(workspace.archive) as z:
        z.extractall(target)
    return directory


def import_xlsx_transcripts(xlsx_path: Path, files: list[Path], mapping: dict[str, str]) -> int:
    """Merge filename->transcript rows from an xlsx into the mapping cache.
    - rows are matched by audio filename stem
    - lazy-imports openpyxl
    """
    try:
        import openpyxl
    except ImportError:
        print(
            f"WARNING: openpyxl is not installed, skipping xlsx transcripts ({xlsx_path}). Install with: uv add openpyxl"
        )
        return 0

    ids = {audio_id(f) for f in files}
    added = 0
    workbook = openpyxl.load_workbook(xlsx_path, read_only=True)
    try:
        for row in chain.from_iterable(sheet.iter_rows(values_only=True) for sheet in workbook.worksheets):
            values = [str(cell).strip() for cell in row if cell is not None]
            for i, value in enumerate(values):
                key = value.lower()
                if key not in ids or i + 1 >= len(values):
                    continue
                text = values[i + 1]
                if not text or text.lower() in ids or mapping.get(key, "").strip():
                    continue
                mapping[key] = clean_text(text)
                added += 1
                break
    finally:
        workbook.close()
    return added


@dataclass
class VoiceInventory:
    files: list[Path]
    mapping: dict[str, str]
    durations: dict[str, float]


def prepare_sources(
    workspace: CharacterWorkspace, config: CharacterConfig, preferred: str, fallback: str | None
) -> VoiceInventory:
    directory = workspace.directory
    cache = workspace.cache
    durations_path = workspace.durations
    directory.mkdir(parents=True, exist_ok=True)
    workspace.generated.mkdir(parents=True, exist_ok=True)

    sources = ensure_sources(config, workspace)
    roots_ = roots(sources)
    print("Using folders:", ", ".join(p.name for p in roots_))

    excluded = set(config.exclude)
    files = voice_files(roots_, excluded, workspace.generated)
    durations = load_durations(durations_path)

    # - only longestAudio actually ranks by duration; precompute durations just for it
    #   (longestText ranks by transcript length)
    if "longestAudio" in (preferred, fallback):
        print("Computing durations for duration-based selection...")
        for f in files:
            get_duration(f, durations)

    mapping = load_map(cache, files, durations, excluded)

    if config.transcripts_xlsx:
        xlsx_path = directory / config.transcripts_xlsx
        added = import_xlsx_transcripts(xlsx_path, files, mapping)
        if added:
            print(f"Imported {added} transcripts from {xlsx_path}")
            mapping = sort_map(mapping, durations)
            save_json(cache, mapping)

    return VoiceInventory(files, mapping, durations)


def prepare(char, preferred, fallback, count, do_transcribe, duration_target=None, top_n=0):
    config = CHARACTER_CONFIGS[char]
    count = config.count if count is None else count
    name = getattr(char, "value", char)
    if config.superseded_by:
        print(f"NOTE: {name} is superseded by {config.superseded_by}; preparing its own clips anyway.")
    workspace = CharacterWorkspace(DATA, name, config.category)
    excluded = set(config.exclude)
    selected_dir = workspace.selected
    cache = workspace.cache
    durations_path = workspace.durations
    inventory = prepare_sources(workspace, config, preferred, fallback)
    mapping = inventory.mapping

    top_done = 0
    if top_n:
        mapping, top_done = transcribe_top(
            inventory.files,
            mapping,
            cache,
            inventory.durations,
            excluded,
            top_n,
            workspace.generated / "asr_empty.json",
        )
        save_json(durations_path, inventory.durations)

    def make_request():
        return SelectionRequest(
            inventory.files,
            mapping,
            preferred,
            fallback,
            count,
            excluded,
            list(config.selected),
            inventory.durations,
            duration_target,
        )

    selection = get_selection(selected_dir, make_request())
    save_json(durations_path, inventory.durations)

    transcribed = top_done
    if do_transcribe:
        # Transcribe only what the selection needs: untranscribed clips picked by the longestAudio
        # fallback. Then reselect, so longestText re-ranks with the new transcripts and the fallback
        # pulls in the next-longest untranscribed clip if still short. Stops when nothing is left to do.
        tried = set()
        while True:
            todo = [f for f in selection.files if not mapping.get(audio_id(f), "").strip() and audio_id(f) not in tried]
            if not todo:
                break
            parts = selection.method.split("+")
            if not any(p in ("longestAudio", "longestText") for p in parts):
                raise ValueError(
                    f"Refusing to transcribe: selection '{selection.method}' is not duration-based "
                    "(transcription is only for longestAudio/longestText flows)"
                )
            mapping = transcribe(todo, mapping, cache, inventory.durations, excluded)
            tried.update(audio_id(f) for f in todo)
            transcribed += sum(bool(mapping.get(audio_id(f), "").strip()) for f in todo)
            selection = get_selection(selected_dir, make_request())
        save_json(durations_path, inventory.durations)

    selected_files = selection.files
    method = selection.method

    missing = [audio_id(f) for f in selected_files if not mapping.get(audio_id(f), "").strip()]
    if missing:
        print("Selected files need transcripts:", ", ".join(missing))
        print(f"They have been copied to: {selected_dir}")
        status = "MISSING TRANSCRIPTS"
        length = None
    else:
        _, length = build_wav(selected_files, mapping, workspace, count, duration_target)
        print(f"JSON: {cache}")
        print(f"Selection method: {method}")
        status = "OK"

    return PreparationResult(
        character=name,
        status=status,
        selected=len(selected_files),
        method=method,
        transcribed=transcribed,
        missing=missing,
        length=length,
    )


def duration_targets_for_args(args):
    if args.min_duration is not None:
        return [DurationTarget(args.min_duration, "min")]
    if args.max_duration is not None:
        return [DurationTarget(args.max_duration, "max")]
    if args.count is not None:
        return [None]  # explicit --count with no duration flag: old count-based single file
    return [
        DurationTarget(DEFAULT_DUR_TARGET, "min"),
        DurationTarget(DEFAULT_DUR_TARGET, "max"),
    ]  # no options at all: build both defaults


def print_summary(results: list[PreparationResult]) -> None:
    headers = ("Character", "Variant", "Status", "Clips", "Method", "Transcribed", "Length")
    rows = []
    for r in results:
        m = re.match(r"^(.*) \((.*)\)$", r.character)
        name, variant = (m[1], m[2]) if m else (r.character, "")
        length = f"{r.length:.1f}s" if r.length is not None else "-"
        rows.append((name, variant, r.status, str(r.selected), r.method, str(r.transcribed), length))

    widths = [max(len(h), *(len(row[i]) for row in rows)) if rows else len(h) for i, h in enumerate(headers)]
    # numeric columns are right-aligned
    right = {3, 5, 6}

    def fmt(row):
        return "  ".join(
            (c.rjust(w) if i in right else c.ljust(w)) for i, (c, w) in enumerate(zip(row, widths, strict=True))
        ).rstrip()

    print("\n=== SUMMARY ===")
    print(fmt(headers))
    print("  ".join("-" * w for w in widths))
    last = None
    for row in rows:
        if last is not None and row[0] != last:
            print()
        last = row[0]
        print(fmt(row))

    for r in results:
        if r.missing:
            print(f"\n{r.character} missing transcripts: {', '.join(r.missing)}")


def build_mapping(raw, files):
    """Transcript map from raw subtitles.json data: normalized keys, cleaned text, gaps filled from filenames."""
    mapping = {}
    for k, v in raw.items():
        key = norm_key(k)
        text = clean_text(v)
        if text or not mapping.get(key, "").strip():
            mapping[key] = text
    for k, v in get_text(files).items():
        if not mapping.get(k, "").strip():
            mapping[k] = v
    return mapping


def transcribe_top(files, mapping, cache, durations, excluded, n, empty_path):
    """Make sure the n longest clips (by audio length) have transcripts. Idempotent: it is always the same
    n clips, so running it per variant or on later runs doesn't transcribe more. Clips ASR returned nothing
    for are remembered in asr_empty.json so they aren't retried every run."""
    ranked = sorted(files, key=lambda f: -get_duration(f, durations))[:n]
    empty = set(load_json(empty_path, []))
    todo = [f for f in ranked if not mapping.get(audio_id(f), "").strip() and audio_id(f) not in empty]
    if not todo:
        return mapping, 0
    print(f"Transcribing {len(todo)} of the {len(ranked)} longest clips...")
    mapping = transcribe(todo, mapping, cache, durations, excluded)
    done = [f for f in todo if mapping.get(audio_id(f), "").strip()]
    empty.update(audio_id(f) for f in todo if not mapping.get(audio_id(f), "").strip())
    save_json(empty_path, sorted(empty))
    return mapping, len(done)


def source_files(char):
    """(workspace, config, files) for a character without downloading anything; files is None if no audio."""
    config = CHARACTER_CONFIGS[char]
    workspace = CharacterWorkspace(DATA, char.value, config.category)
    return workspace, config, _source_files(workspace, set(config.exclude))


def cleanup_character(char, drop_orphans=False):
    """Rewrite one character's subtitles.json cleanly: normalized keys, cleaned text, filename transcripts
    filled in. Original is kept once as subtitles.json.bak. Orphans are kept unless drop_orphans."""
    workspace, config, files = source_files(char)
    result: dict[str, Any] = {
        "character": char.value,
        "status": "NO SOURCES",
        "keys": 0,
        "texts": 0,
        "orphans": 0,
        "dropped": 0,
    }
    if files is None:
        return result

    excluded = set(config.exclude)
    cache = workspace.cache
    raw = load_json(cache)
    if not isinstance(raw, dict):
        raw = {}

    mapping = build_mapping(raw, files)

    ids = {audio_id(f) for f in files}
    orphans = [k for k, v in mapping.items() if v.strip() and k not in ids and k not in excluded]
    result["orphans"] = len(orphans)
    if drop_orphans:
        for k in orphans:
            del mapping[k]
        result["dropped"] = len(orphans)
    for i in ids:
        mapping.setdefault(i, "")

    result["keys"] = sum(norm_key(k) != str(k).lower() for k in raw)
    result["texts"] = sum(clean_text(v) != str(v) for v in raw.values())
    mapping = sort_map(mapping, load_durations(workspace.durations))

    if mapping == raw:
        result["status"] = "ALREADY CLEAN"
        return result

    backup = cache.with_name(cache.name + ".bak")
    if cache.exists() and not backup.exists():
        shutil.copy2(cache, backup)
    save_json(cache, mapping)
    result["status"] = "CLEANED"
    return result


def print_cleanup(rows):
    print("\n=== CLEANUP ===")
    for r in rows:
        print(f"{r['character']}: {r['status']}")
        if r["status"] == "NO SOURCES":
            continue
        if r["status"] == "CLEANED":
            print(f"  Keys normalized: {r['keys']}  Texts cleaned: {r['texts']}")
        if r["dropped"]:
            print(f"  Orphan transcripts dropped: {r['dropped']}")
        elif r["orphans"]:
            print(f"  Orphan transcripts kept: {r['orphans']} (use --drop-orphans to remove them)")


def plan_character(char, preferred, fallback, count, targets, top_n):
    """Dry run for one character: what --transcribe / --transcribe-top would transcribe. Writes nothing."""
    workspace, config, files = source_files(char)
    plan: dict[str, Any] = {
        "character": char.value,
        "status": "OK",
        "files": 0,
        "with_text": 0,
        "usable": 0,
        "top_n": 0,
        "variants": [],
    }
    if files is None:
        plan["status"] = "NO SOURCES"
        return plan

    excluded = set(config.exclude)
    raw = load_json(workspace.cache)
    if not isinstance(raw, dict):
        raw = {}
    mapping = build_mapping(raw, files)
    all_ids = {audio_id(f) for f in files}
    for i in all_ids:
        mapping.setdefault(i, "")
    durations = load_durations(workspace.durations)
    mapping = sort_map(mapping, durations)

    plan["files"] = len(all_ids)
    plan["with_text"] = sum(bool(mapping[i].strip()) for i in all_ids)
    plan["usable"] = sum(is_speech(mapping[i]) for i in all_ids)

    if top_n:
        ranked = sorted(files, key=lambda f: -get_duration(f, durations))[:top_n]
        empty = set(load_json(workspace.generated / "asr_empty.json", []))
        plan["top_n"] = sum(not mapping[audio_id(f)].strip() and audio_id(f) not in empty for f in ranked)

    for target in targets:
        label = workspace.wav_suffix(target, count)
        try:
            desired, method = select(
                SelectionRequest(
                    files, mapping, preferred, fallback, count, excluded, list(config.selected), durations, target
                )
            )
            need = sum(not mapping[audio_id(f)].strip() for f in desired)
            plan["variants"].append((label, method, need, None))
        except Exception as e:
            plan["variants"].append((label, "-", 0, str(e)))
    return plan


def print_plan(plans, top_n):
    print("\n=== DRY RUN (nothing is transcribed or written) ===")
    total_top = total_sel = 0
    for p in plans:
        print(f"{p['character']}: {p['status']}")
        if p["status"] == "NO SOURCES":
            continue
        print(f"  Files: {p['files']}  Transcribed: {p['with_text']}  Usable speech: {p['usable']}")
        if top_n:
            print(f"  --transcribe-top {top_n}: would transcribe {p['top_n']} clips")
        need_max = 0
        for label, method, need, err in p["variants"]:
            if err:
                print(f"  {label}: cannot build ({err})")
                continue
            print(f"  {label}: {method}, {need} untranscribed clip(s) picked by the fallback")
            need_max = max(need_max, need)
        total_top += p["top_n"]
        total_sel += need_max
    if top_n:
        print(f"\nTotal: {total_top} clips from --transcribe-top, plus up to {total_sel} more from selection fallback")
    else:
        print(f"\nTotal with --transcribe: at least {total_sel} clips (more if new transcripts rank lower)")


def _source_files(workspace, excluded) -> list[Path] | None:
    """Every eligible audio file for one character, or None when the folder has none."""
    directory = workspace.directory
    has_audio = directory.is_dir() and any(
        f.is_file() and workspace.generated not in f.parents and f.suffix.lower() in (".ogg", ".wav", ".mp3")
        for f in directory.rglob("*")
    )
    if not has_audio:
        return None
    try:
        return voice_files(roots(directory), excluded, workspace.generated)
    except ValueError:
        return None


def _duplicate_detail(files, directory) -> list[tuple[str, list[str]]]:
    by_id = {}
    for f in files:
        by_id.setdefault(audio_id(f), []).append(str(f.relative_to(directory)))
    return [(k, v) for k, v in by_id.items() if len(v) > 1]


def _transcript_map(raw, files) -> dict[str, str]:
    """Cached transcripts win over the sidecar text; both are keyed by normalized audio id."""
    mapping = {}
    for k, v in raw.items():
        key = norm_key(k)
        text = clean_text(v)
        if text or key not in mapping:
            mapping[key] = text
    for k, v in get_text(files).items():
        if not mapping.get(k, "").strip():
            mapping[k] = v
    return mapping


def _validation_status(row) -> str:
    if row["orphans"] or row["dup_ids"]:
        return "ISSUES"
    if row["files"] and row["with_text"] == 0:
        return "NO TRANSCRIPTS"
    if row["legacy_keys"] or row["underscores"]:
        return "NEEDS CLEANUP"  # auto-fixed the next time the character is run
    return "OK"


def validate_character(char):
    """Read-only health check for one character: never downloads, transcribes or writes anything.
    Returns a dict describing key-matching / transcript problems.
    """
    config = CHARACTER_CONFIGS[char]
    name = str(getattr(char, "value", char))
    workspace = CharacterWorkspace(DATA, name, config.category)
    directory = workspace.directory
    excluded = set(config.exclude)
    row: dict[str, Any] = {
        "character": name,
        "status": "OK",
        "files": 0,
        "with_text": 0,
        "missing": 0,
        "orphans": [],
        "legacy_keys": 0,
        "underscores": 0,
        "dup_ids": 0,
        "dup_detail": [],
        "usable": 0,
        "superseded_by": config.superseded_by,
    }

    files = _source_files(workspace, excluded)
    if files is None:
        row["status"] = "NO SOURCES"
        return row

    ids = [audio_id(f) for f in files]
    id_set = set(ids)
    row["files"] = len(id_set)
    row["dup_ids"] = len(ids) - len(id_set)
    if row["dup_ids"]:
        row["dup_detail"] = _duplicate_detail(files, directory)

    raw = load_json(workspace.cache)
    if not isinstance(raw, dict):
        raw = {}
    row["legacy_keys"] = sum(norm_key(k) != str(k).lower() for k in raw)
    row["underscores"] = sum("_" in str(v) for v in raw.values())

    mapping = _transcript_map(raw, files)
    row["orphans"] = sorted(k for k, v in mapping.items() if v.strip() and k not in id_set and k not in excluded)
    row["with_text"] = sum(bool(mapping.get(i, "").strip()) for i in id_set)
    row["missing"] = row["files"] - row["with_text"]
    row["usable"] = sum(is_speech(mapping.get(i, "")) for i in id_set)
    row["status"] = _validation_status(row)
    return row


def print_validation(rows):
    print("\n=== VALIDATION ===")
    for r in rows:
        print(f"{r['character']}: {r['status']}")
        if r["superseded_by"]:
            print(f"  Superseded by: {r['superseded_by']}")
        if r["status"] == "NO SOURCES":
            continue
        print(
            f"  Files: {r['files']}  With transcript: {r['with_text']}  Missing: {r['missing']}"
            f"  Usable speech: {r['usable']}"
        )
        if r["legacy_keys"]:
            print(f"  Legacy keys (e.g. '.0b2' suffix, auto-normalized on next run): {r['legacy_keys']}")
        if r["underscores"]:
            print(f"  Transcripts containing '_' (auto-cleaned on next run): {r['underscores']}")
        if r["dup_ids"]:
            print(f"  Files sharing an audio id (collisions): {r['dup_ids']}")
            for k, names in r["dup_detail"][:5]:
                print(f"    {k}: {' | '.join(names)}")
        if r["orphans"]:
            print(f"  Transcripts matching no audio file: {len(r['orphans'])}, e.g. {', '.join(r['orphans'][:5])}")
    bad = [r["character"] for r in rows if r["status"] not in ("OK", "NO SOURCES")]
    print(f"\nNeed attention: {', '.join(bad) if bad else 'none'}")
