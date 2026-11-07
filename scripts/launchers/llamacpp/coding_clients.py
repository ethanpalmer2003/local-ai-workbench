import json
import os
from pathlib import Path
from typing import Any

from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import llamacpp


def model_provider(conf: llamacpp.LlamaConfig) -> dict[str, Any]:
    return {
        "baseUrl": f"http://127.0.0.1:{conf.port}/v1",
        "api": "openai-completions",
        "apiKey": cfg.LLAMACPP_API_KEY_NOOP,
        "models": [
            {
                "id": conf.alias,
                "name": conf.alias,
                "reasoning": True,
                "compat": {"supportsReasoningEffort": False},
                "input": ["text"],
                "contextWindow": int({**conf.get_ini(), **conf.profile.extra_args}.get("ctx-size", "98304")),
                "maxTokens": 16384,
            }
        ],
    }


def prepare_ohmypi(
    conf: llamacpp.LlamaConfig,
    provider: dict[str, Any] | None = None,
    provider_name: str = "llamacpp",
    client: cfg.SharedStartupRequestCodingClientSettings | None = None,
) -> tuple[list[str], dict[str, str]]:
    import yaml

    client = cfg.OHMYPI_CLIENT if client is None else client
    client.agent_dir.mkdir(parents=True, exist_ok=True)
    models_path = client.agent_dir / "models.yml"
    models = yaml.safe_load(models_path.read_text(encoding="utf-8")) if models_path.exists() else {}
    provider = model_provider(conf) if provider is None else provider
    models.setdefault("providers", {})[provider_name] = provider
    models_path.write_text(yaml.safe_dump(models, sort_keys=False), encoding="utf-8")
    env = os.environ.copy()
    env["PI_CODING_AGENT_DIR"] = str(client.agent_dir)
    # - OMP joins this directory name to homedir, even for an absolute value
    env["PI_CONFIG_DIR"] = os.path.relpath(client.agent_dir.parent, Path.home())
    env["OMP_PROFILE"] = ""
    # - the compiled native loader uses XDG_DATA_HOME independently of PI_CONFIG_DIR
    data_dir = client.agent_dir.parent / "data"
    (data_dir / "omp").mkdir(parents=True, exist_ok=True)
    env["XDG_DATA_HOME"] = str(data_dir)
    env[cfg.LLAMACPP_API_KEY_ENV] = cfg.LLAMACPP_API_KEY_NOOP
    return [str(client.entry), "--provider", provider_name, "--model", provider["models"][0]["id"]], env


def prepare_nanocoder(
    conf: llamacpp.LlamaConfig,
    provider: dict[str, Any] | None = None,
    provider_name: str = "llamacpp",
    client: cfg.SharedStartupRequestCodingClientSettings | None = None,
) -> tuple[list[str], dict[str, str]]:
    client = cfg.NANOCODER_CLIENT if client is None else client
    client.agent_dir.mkdir(parents=True, exist_ok=True)
    provider = model_provider(conf) if provider is None else provider
    env = os.environ.copy()
    env["NANOCODER_CONFIG_DIR"] = str(client.agent_dir)
    env["NANOCODER_DATA_DIR"] = str(client.agent_dir / "data")
    env["NANOCODER_LOG_DIR"] = str(client.agent_dir / "logs")
    env["NANOCODER_PROVIDERS"] = json.dumps(
        [
            {
                "name": provider_name,
                "baseUrl": provider["baseUrl"],
                "apiKey": provider["apiKey"],
                "models": [provider["models"][0]["id"]],
                "contextWindow": provider["models"][0]["contextWindow"],
                "maxOutputTokens": provider["models"][0]["maxTokens"],
            }
        ]
    )
    return [
        client.node_cmd,
        str(client.entry),
        "--provider",
        provider_name,
        "--model",
        provider["models"][0]["id"],
    ], env
