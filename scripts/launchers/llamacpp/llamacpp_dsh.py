"""Prepare llama-server for a manually opened DeepSeek Harness.

- Reuses the llama.cpp server-config CLI, so `--ini-*` describes the server
  using the same server configuration as llamacpp_coding.py
- Attaches when llama-server already answers on the port and launches it
  otherwise: the launch path kills whatever holds the port, so it must never
  run against a server that is already up
- The harness profile patch is left alone by default. With `--update-patch`
  it reads the model ids from /v1/models and upserts the `llm-pi-ai` ->
  `llamacpp` route (line-surgical: comments, `!!js` expressions and every
  other entries keep their content). An unwritable patch is a warning:
  the entry is printed so it can be pasted in by hand
- Desktop startup is manual; this wrapper only prepares the server and state
- Stdlib only: the harness patch layer carries `!!js` tags that a plain YAML
  round trip would either refuse or rewrite
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

from scripts.launchers import launcher_config as cfg
from scripts.launchers.launch_util import backend_running, wait_for_backend
from scripts.launchers.llamacpp import llamacpp, llamacpp_proxy

# - the pi-ai adapter entry the harness base bundle mounts dormant
ENTRY_ID = "llm-pi-ai"
ENTRY_NAME = "@deepseek-ai/dsh-llm-pi-ai"

# - how long a just-started proxy gets to bind before this gives up
PROXY_READY_TIMEOUT_S = 30

_ENTRY_HEAD = re.compile(rf"^(?P<indent>[ \t]*)- id: {re.escape(ENTRY_ID)}\s*$")

_BLOCK_COMMENT = (
    "# Local llama.cpp route over the dormant pi-ai adapter. The api key is the",
    "# same ignored value every local client resolves. Model ids are the",
    "# llama-server --alias values; refresh them with python -m scripts.launchers.llamacpp.llamacpp_dsh --update-patch.",
)


def prepare_dsh_env(profile: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    previous_home = Path(env.get("DSH_HOME") or Path.home() / ".dsh").expanduser()
    home = cfg.DEEPSEEK_CLIENT.home
    home.mkdir(parents=True, exist_ok=True)
    if previous_home.resolve() != home.resolve() and previous_home.is_dir():
        # - seed state once; preserve local updates and leave the original intact
        for source in previous_home.iterdir():
            target = home / source.name
            if target.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("lock"))
            else:
                shutil.copy2(source, target)

    for directory in (
        home,
        home / "profiles" / (profile or cfg.DEEPSEEK_CLIENT.profile),
        home / "sessions",
        home / "storages",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    cfg.LAUNCH.temp_dir.mkdir(parents=True, exist_ok=True)
    env["DSH_HOME"] = str(home)
    env[cfg.DEEPSEEK_CLIENT.api_key_env] = cfg.LLAMACPP_API_KEY_NOOP
    for name in ("TEMP", "TMP", "TMPDIR"):
        env[name] = str(cfg.LAUNCH.temp_dir)
    return env


def discover_models(port: int, timeout: float = 5.0) -> list[str]:
    """Loaded model ids advertised by llama-server; raises RuntimeError on failure"""
    url = f"{cfg.llama_base_url(port)}/models"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"could not reach {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{url} did not answer with JSON: {exc}") from exc

    ids = [
        entry["id"]
        for entry in payload.get("data", [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]
    ]

    if not ids:
        raise RuntimeError(f"{url} advertised no models")

    return ids


def render_entry(model_ids: list[str], port: int) -> list[str]:
    """Loader patch lines for the whole `llm-pi-ai` entry"""
    route = cfg.DEEPSEEK_CLIENT
    # - JSON strings are valid YAML quoted scalars
    id_lines = [f"          - id: {json.dumps(model_id, ensure_ascii=False)}" for model_id in model_ids]

    return [
        *_BLOCK_COMMENT,
        f"- id: {ENTRY_ID}",
        f"  name: '{ENTRY_NAME}'",
        "  config:",
        "    providers:",
        f"      {route.route}:",
        f"        displayName: {json.dumps(route.display_name, ensure_ascii=False)}",
        "        api: openai-completions",
        f"        baseURL: {cfg.llama_base_url(port)}",
        f"        apiKeyEnv: {route.api_key_env}",
        f"        defaultContextWindow: {route.default_context_window}",
        f"        defaultMaxTokens: {route.default_max_tokens}",
        f"        streamIdleTimeoutMs: {route.stream_idle_timeout_ms}",
        "        models:",
        *id_lines,
    ]


def upsert_entry(text: str, block: list[str]) -> str:
    """Replace the existing `llm-pi-ai` entry block, or append one when absent"""
    lines = text.splitlines()

    for index, line in enumerate(lines):
        head = _ENTRY_HEAD.match(line)
        if head is None:
            continue

        indent = len(head.group("indent"))

        # - reclaim the comment block the entry owns, so re-running replaces it
        #   instead of stacking a second copy above the first
        start = index
        while start > 0:
            previous = lines[start - 1]
            if not previous.strip().startswith("#"):
                break
            if len(previous) - len(previous.lstrip()) > indent:
                break
            start -= 1

        # - the entry ends at the next non-blank line indented no deeper than
        #   its own `- id:` marker, i.e. the next top-level patch entry
        end = len(lines)
        for cursor in range(index + 1, len(lines)):
            if not lines[cursor].strip():
                continue
            if len(lines[cursor]) - len(lines[cursor].lstrip()) <= indent:
                end = cursor
                break

        return "\n".join([*lines[:start], *block, *lines[end:]]) + "\n"

    separator = [] if (not lines or not lines[-1].strip()) else [""]

    return "\n".join([*lines, *separator, *block]) + "\n"


def update_patch(args: argparse.Namespace, patch_path: Path) -> int:
    """Opt-in: sync the `llm-pi-ai` route in the profile patch. 0 = fine, 1 = fail"""
    if args.models:
        model_ids = [model_id.strip() for model_id in args.models.split(",") if model_id.strip()]
    elif args.dry_run and not backend_running(args.port):
        model_ids = [llamacpp.config_from_args(args).alias]
    else:
        try:
            model_ids = discover_models(args.port)
        except RuntimeError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 1

    print(f"[dsh] route '{cfg.DEEPSEEK_CLIENT.route}' -> {cfg.llama_base_url(args.port)}")
    for model_id in model_ids:
        print(f"  > {model_id}")

    original = patch_path.read_text(encoding="utf-8")
    entry = render_entry(model_ids, args.port)
    updated = upsert_entry(original, entry)

    # - the splice must leave exactly one entry and be a fixed point, or the
    #   entry-boundary scan above is wrong and the file would drift each run
    if updated.count(f"- id: {ENTRY_ID}\n") != 1 or upsert_entry(updated, entry) != updated:
        print("[FAIL] refusing to write: entry splice is not stable", file=sys.stderr)
        return 1

    if updated == original:
        print(f"[OK] {patch_path.name} already current")
        return 0

    if args.dry_run:
        print(f"[dry-run] would write {patch_path}:")
        print(updated)
        return 0

    try:
        _ = patch_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        print(f"[WARN] cannot write {patch_path}: {exc}")
        print("[WARN] patch not written; paste this entry into the profile manually if the route is missing:")
        print("\n".join(entry))
        return 0

    print(f"[OK] wrote {patch_path}")
    print(f"[dsh] needs '{cfg.DEEPSEEK_CLIENT.api_key_env}' in the credential store")
    return 0


def main() -> int:  # noqa: C901
    # - a model id is external text and the Windows console default (cp1252)
    #   would crash on any non-ASCII one
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Prepare llama-server for a manually opened DeepSeek Harness.")
    parser.add_argument("--port", type=int, default=cfg.LLAMACPP_SERVICE.port)
    parser.add_argument("--profile", default=cfg.DEEPSEEK_CLIENT.profile)
    parser.add_argument("--patch", type=Path, default=None, help="DSH profile patch path override")
    parser.add_argument(
        "--update-patch", action="store_true", help="also sync the llm-pi-ai route in the profile patch"
    )
    parser.add_argument("--models", default=None, help="comma-separated ids for --update-patch; skips discovery")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen, write nothing")
    parser.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    llamacpp.add_config_args(parser)
    args = parser.parse_args()

    if not args.dry_run:
        prepare_dsh_env(args.profile)

    patch_path: Path | None = None
    if args.update_patch:
        patch_path = Path(args.patch) if args.patch is not None else cfg.DEEPSEEK_CLIENT.patch_path(args.profile)

        if not patch_path.is_file():
            print(f"[FAIL] profile patch not found: {patch_path}", file=sys.stderr)
            return 1

    attached = backend_running(args.port)
    proxy_mode = cfg.LLAMACPP_SERVICE.mode == cfg.ServiceMode.PROXY

    if attached:
        print(f"[dsh] llama-server already up on 127.0.0.1:{args.port} - attaching")
        if llamacpp.config_given(args):
            print("[dsh] server-config flags ignored while attaching; stop the server to relaunch it", file=sys.stderr)
    elif proxy_mode:
        # - the proxy belongs on this port: starting it loads nothing, and it
        #   answers /v1/models from its own configuration
        if args.dry_run:
            print(f"[dsh] would start the llama.cpp proxy on 127.0.0.1:{args.port} (model loads on first request)")
        else:
            print(f"[dsh] no server on 127.0.0.1:{args.port} - starting the llama.cpp proxy")
            llamacpp_proxy.start(args, port=args.port)
            if not wait_for_backend(args.port, PROXY_READY_TIMEOUT_S):
                print(f"[FAIL] proxy did not answer 127.0.0.1:{args.port} in {PROXY_READY_TIMEOUT_S}s", file=sys.stderr)
                return 1
    else:
        conf = llamacpp.config_from_args(args, port=args.port)
        if args.dry_run:
            print(f"[dsh] would launch profile '{conf.name}':")
            print("      " + " ".join(f'"{a}"' for a in conf.build_cmd(llamacpp.DRY_RUN_LOG_FILE)))
        else:
            print(f"[dsh] no server on 127.0.0.1:{args.port} - launching profile '{conf.name}'")
            llamacpp.launch(conf=conf)

    if patch_path is not None and update_patch(args, patch_path) != 0:
        return 1

    if not args.dry_run:
        print(f"[dsh] llama-server ready at {cfg.llama_base_url(args.port)}")
        print(f"[dsh] open DeepSeek Harness manually: {cfg.DEEPSEEK_CLIENT.exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
