"""Repetition-loop check for a chat model behind an OpenAI-compatible endpoint.

Sends repetition-prone prompts across a small sampler matrix, then flags the failure modes a
review cannot see from scores: an exact line or sentence repeating, a word stuck in a run, and
thinking that never resolves into an answer. Exits 1 when any case loops, so a validation run
fails loudly instead of printing a wall of text.

Example:
    python -m scripts.benchmarks.llamacpp.benchmark_repetition --url http://127.0.0.1:8080
"""

import argparse
import json
import re
import urllib.request
from dataclasses import dataclass

from scripts.shared.tables import render_table

PROMPTS = {
    "story": "Tell me a short story about a lighthouse keeper, about 150 words.",
    "explain": "Explain why the sky is blue, in about 100 words, for a ten-year-old.",
    "list": "Name twelve constellations and one fact about each.",
}

MATRIX: list[dict[str, object]] = [
    {"temperature": 0.7, "repeat_penalty": 1.0},
    {"temperature": 0.7, "repeat_penalty": 1.18},
    {"temperature": 1.0, "repeat_penalty": 1.0},
    {"temperature": 1.0, "repeat_penalty": 1.18},
]

WORD_RUN = re.compile(r"(\b\w+\b)(?:\s+\1){5,}", re.IGNORECASE)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class CaseResult:
    prompt: str
    settings: str
    finish: str
    content_tokens: int
    thinking_chars: int
    findings: tuple[str, ...]


def repeated(items: list[str], minimum: int) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        key = item.strip().lower()
        if len(key) > 3:
            counts[key] = counts.get(key, 0) + 1
    return sorted(((key, count) for key, count in counts.items() if count >= minimum), key=lambda pair: -pair[1])


def diagnose(text: str, repeats: int = 3) -> list[str]:
    findings = []
    lines = [line for line in text.splitlines() if line.strip()]
    for key, count in repeated(lines, repeats)[:3]:
        findings.append(f"line x{count}: {key[:60]}")
    sentences = [part for part in SENTENCE_END.split(text) if part.strip()]
    for key, count in repeated(sentences, repeats)[:3]:
        findings.append(f"sentence x{count}: {key[:60]}")
    match = WORD_RUN.search(text)
    if match:
        findings.append(f"word run: {match.group(1)!r} x6+")
    words = text.split()
    if words and len(set(words)) / len(words) < 0.25 and len(words) > 60:
        findings.append(f"low diversity: {len(set(words))}/{len(words)} unique")
    return findings


def complete(url: str, model: str, prompt: str, settings: dict[str, object], max_tokens: int) -> CaseResult:
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, **settings}
    ).encode()
    request = urllib.request.Request(
        f"{url}/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.loads(response.read())
    choice = payload["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""
    thinking = message.get("reasoning_content") or ""
    findings = diagnose(content + "\n" + thinking)
    if not content and choice["finish_reason"] == "length":
        findings.append("unresolved thinking: budget spent before any answer")
    label = ",".join(f"{key}={value}" for key, value in sorted(settings.items()))
    return CaseResult(
        prompt, label, choice["finish_reason"], payload["usage"]["completion_tokens"], len(thinking), tuple(findings)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="stock")
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--prompts", nargs="*", default=sorted(PROMPTS), choices=sorted(PROMPTS))
    parser.add_argument("--fail-fast", action="store_true", help="stop after the first looping case")
    parser.add_argument("--settings", nargs="*", default=None, help="only run matrix entries containing all these k=v")
    args = parser.parse_args(argv)
    wanted = args.settings or []
    matrix = [
        entry for entry in MATRIX if all(item in {f"{k}={v}" for k, v in entry.items()} for item in wanted)
    ] or MATRIX
    rows = []
    for name in args.prompts:
        for settings in matrix:
            try:
                result = complete(args.url, args.model, PROMPTS[name], settings, args.max_tokens)
                summary = "; ".join(result.findings) or "clean"
                rows.append([name, result.settings, result.finish, str(result.content_tokens), summary])
            except Exception as error:  # - a refused or timed-out case is data, not a crash
                summary = f"error: {str(error)[:80]}"
                rows.append([name, str(settings), "error", "0", summary])
            print(f"[CASE] {name} {rows[-1][1]} -> {rows[-1][2]} {rows[-1][3]} tokens: {summary[:100]}", flush=True)
            if args.fail_fast and summary != "clean" and not summary.startswith("error"):
                break
        else:
            continue
        break
    print(render_table(rows, ["prompt", "settings", "finish", "tokens", "findings"]))
    looping = sum(1 for row in rows if row[4] not in ("clean",) and not row[4].startswith("error"))
    print(f"[{'FAIL' if looping else 'OK'}] {looping} looping case(s) in {len(rows)}")
    return 1 if looping else 0


if __name__ == "__main__":
    raise SystemExit(main())
