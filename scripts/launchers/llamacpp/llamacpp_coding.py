import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.config.coding_agents.pi import packages as pi_packages
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import coding_clients, llamacpp, llamacpp_proxy


def prepare_pi_env(
    client: cfg.SharedStartupRequestCodingClientSettings | None = None, seed_dir: Path | None = None
) -> dict[str, str]:
    client = cfg.PI_CLIENT if client is None else client
    env = os.environ.copy()
    previous_dir = (
        seed_dir
        if seed_dir is not None
        else Path(env.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent").expanduser()
    )
    agent_dir = client.agent_dir
    if seed_dir is None and client is cfg.LITTLECODER_CLIENT and not env.get("PI_CODING_AGENT_DIR"):
        previous_dir = cfg.PI_CLIENT.agent_dir
    agent_dir.mkdir(parents=True, exist_ok=True)
    if previous_dir.resolve() != agent_dir.resolve():
        # - seed persistent state once; never overwrite newer local state
        for name in (
            "settings.json",
            "auth.json",
            "models.json",
            "keybindings.json",
            "little-coder-prompt-history.json",
            "sessions",
        ):
            source = previous_dir / name
            target = agent_dir / name
            if source.exists() and not target.exists():
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)

    sessions_dir = agent_dir / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    if client.extensions:
        extension_dir = agent_dir / "extensions"
        extension_dir.mkdir(exist_ok=True)
        for source in client.extensions:
            shutil.copy2(source, extension_dir / source.name)
    if client.packages or client.additional_tools:
        settings_path = agent_dir / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
        settings["packages"] = [
            value for value in settings.get("packages", []) if not pi_packages.managed_package_reference(value)
        ]
        for key, values in (
            ("packages", [path.as_posix() for path in client.packages]),
            ("defaultTools", [f"+{name}" for name in client.additional_tools]),
        ):
            entries = settings.setdefault(key, [])
            entries.extend(value for value in values if value not in entries)
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    # - exercise both settings-lock mkdir and session-file writes before loading the model.
    #   A default-mode probe keeps the Windows sandbox token able to write: TemporaryDirectory
    #   applies mode 0700, whose DACL excludes that restricted token.
    for directory in (agent_dir, sessions_dir):
        probe = Path(directory) / f".write-probe-{os.getpid()}"
        probe.mkdir(exist_ok=True)
        try:
            (probe / "write-check").write_text("", encoding="utf-8")
        finally:
            shutil.rmtree(probe, ignore_errors=True)

    env["PI_CODING_AGENT_DIR"] = str(agent_dir)
    env.update(pi_packages.environment(client.packages, env))
    if client is cfg.LITTLECODER_CLIENT:
        env["LITTLE_CODER_MODELS_FILE"] = str(agent_dir / "models.json")
    cfg.LAUNCH.temp_dir.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = str(cfg.LAUNCH.temp_dir)
    env["TMP"] = str(cfg.LAUNCH.temp_dir)
    env["LLAMACPP_BASE_URL"] = cfg.llama_base_url()
    env[cfg.LLAMACPP_API_KEY_ENV] = cfg.LLAMACPP_API_KEY_NOOP
    allowed = [
        env.get("LITTLE_CODER_BASH_ALLOW", ""),
        cfg.VENV_PYTHON.as_posix(),
        "uv",
        "where.exe",
        "sleep",
        "taskkill",
        "cd",
    ]
    env["LITTLE_CODER_BASH_ALLOW"] = ",".join(prefix for prefix in allowed if prefix)
    return env


def pi_command(
    conf: llamacpp.LlamaConfig, client: cfg.SharedStartupRequestCodingClientSettings | None = None
) -> list[str]:
    # - single-model server uses the compatible API, rather than Pi's router provider
    client = cfg.PI_CLIENT if client is None else client
    models_path = client.agent_dir / "models.json"
    models = json.loads(models_path.read_text(encoding="utf-8")) if models_path.exists() else {}
    models.setdefault("providers", {})["llamacpp"] = coding_clients.model_provider(conf)
    models_path.write_text(json.dumps(models, indent=2) + "\n", encoding="utf-8")
    return [client.node_cmd, str(client.entry), *client.cli_args, "--provider", "llamacpp", "--model", conf.alias]


def main(default_client: str = "pi"):
    parser = argparse.ArgumentParser(description="Launch llama-server + coding client")
    parser.add_argument(
        "--client",
        choices=("little-coder", "pi", "ohmypi", "nanocoder", "none"),
        default=default_client,
        help="Client to run after llama-server is up (none = server only).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("client_args", nargs=argparse.REMAINDER, help="Client options after --.")
    llamacpp.add_config_args(parser)
    args = parser.parse_args()
    tag = f"[{args.client}]"

    conf = llamacpp.config_from_args(args)

    if args.dry_run:
        print(" ".join(f'"{a}"' for a in conf.build_cmd(llamacpp.DRY_RUN_LOG_FILE)))
        return

    client = {
        "little-coder": cfg.LITTLECODER_CLIENT,
        "ohmypi": cfg.OHMYPI_CLIENT,
        "nanocoder": cfg.NANOCODER_CLIENT,
    }.get(args.client, cfg.PI_CLIENT)
    cmd = None
    if args.client == "ohmypi":
        cmd, env = coding_clients.prepare_ohmypi(conf)
    elif args.client == "nanocoder":
        cmd, env = coding_clients.prepare_nanocoder(conf)
    else:
        env = prepare_pi_env(client) if args.client != "none" else None

    if cfg.LLAMACPP_SERVICE.mode == cfg.ServiceMode.PROXY:
        # - the proxy owns the model, so this only has to make sure it is up;
        #   the client's first request pulls the model in
        if llamacpp_proxy.running():
            print(f"{tag} llama.cpp proxy already up")
            if llamacpp.config_given(args):
                print(f"{tag} server-config flags ignored; stop the proxy to relaunch it", file=sys.stderr)
        else:
            llamacpp_proxy.start(args)
    else:
        llamacpp.launch(conf=conf)

    if args.client == "none":
        print("\n[pi] --client none: server left running.")
        return

    model = conf.alias
    print(f"{tag} state: {client.agent_dir}")
    print(f"{tag} client model ID: {model}")
    if cmd is None:
        if args.client == "pi":
            cmd = pi_command(conf)
        else:
            agents_md = project_cfg.BASE_DIR / "AGENTS.md"
            cmd = [*pi_command(conf, client), "--append-system-prompt", str(agents_md)]

    client_args = args.client_args[1:] if args.client_args[:1] == ["--"] else args.client_args
    subprocess.run([*cmd, *client_args], shell=False, cwd=project_cfg.BASE_DIR, env=env, check=True)


if __name__ == "__main__":
    main()
