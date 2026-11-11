"""Strata benchmark isolation, backend ownership and shared provider configuration."""

import json
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.benchmarks.coding_agents.shared import benchmark_backends as backends
from scripts.benchmarks.coding_agents.shared.benchmark_agents import client_command
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import llamacpp
from scripts.launchers.strata.strata_pi import StrataConnection
from scripts.tests.shared.paths import CasePaths, RunPaths


def benchmark_config() -> llamacpp.LlamaConfig:
    overrides = {"ctx-size": "32768", "reasoning-budget": "2048", "reasoning-effort": "low"}
    return backends.benchmark_llama_config(overrides)


class BenchmarkBackendsTests(unittest.TestCase):
    def test_pi_extensions_default_off_for_both_backends_and_opt_in(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            original = '{"packages":["npm:unrelated-extension"],"defaultTools":["+codemode"]}'
            (source / "settings.json").write_text(original)
            with patch.object(cfg, "PI_CLIENT", replace(cfg.PI_CLIENT, agent_dir=source)):
                for backend in ("llamacpp", "strata"):
                    endpoint = backends.BenchmarkEndpoint(backend, "swift", "http://127.0.0.1:19999/v1", "noop")
                    state = root / backend
                    command, env = client_command("pi", benchmark_config(), endpoint, state)
                    self.assertIn("--no-extensions", command)
                    self.assertNotIn("--no-lens-context", command)
                    settings = json.loads((state / "settings.json").read_text())
                    self.assertEqual(settings["packages"], [])
                    self.assertNotIn("defaultTools", settings)
                    self.assertEqual(env["PI_CODING_AGENT_DIR"], str(state))
                command, _ = client_command("pi", benchmark_config(), endpoint, root / "enabled", True)
                self.assertNotIn("--no-extensions", command)
                self.assertIn("--no-lens-context", command)
            self.assertEqual((source / "settings.json").read_text(), original)

    def test_strata_config_withholds_credentials_and_preserves_memory_options(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            data: dict[str, Any] = {
                "model_name": "swift",
                "args": ["--max-context", "65536", "--vram-reserve-mib", "512"],
                "mcp_servers": {"example": {}},
                "vram_reserve_mib": 512,
            }
            source = StrataConnection(output.temp / "original.json", data, 8080, "secret")
            connection = backends.strata_config(source, output, benchmark_config())
            self.assertEqual(connection.config["args"], ["--max-context", "32768", "--vram-reserve-mib", "512"])
            self.assertEqual(connection.config["reasoning_budget_tokens"], 2048)
            self.assertEqual(connection.config["reasoning_effort"], "low")
            self.assertNotIn("mcp_servers", connection.config)
            self.assertIn("mcp_servers", data)
            self.assertEqual(data["args"][1], "65536")

    def test_existing_backends_are_stopped_before_a_round(self):
        conf = benchmark_config()
        with CasePaths(__file__).temporary_directory() as folder:
            source = StrataConnection(Path(folder) / "saved.json", {}, 18501, "secret")
            with (
                patch.object(backends, "port_in_use", return_value=True),
                patch.object(launch_util, "listening_process_ids", return_value=[1234]),
                patch.object(launch_util, "kill_processes_on_ports") as stop,
                patch.object(backends.strata_pi, "saved_connections", return_value=[source]),
            ):
                backends.preflight(conf, ["strata", "llamacpp"], None)
        self.assertEqual({call.args[0] for call in stop.call_args_list}, {conf.port, cfg.STRATA_SERVICE.port, 18501})

    def test_context_override_reaches_final_llama_command(self):
        conf = benchmark_config()
        command = conf.build_cmd(Path("native.log"))
        values = [command[index + 1] for index, value in enumerate(command) if value == "--ctx-size"]
        self.assertEqual(values[-1], "32768")

    def test_every_harness_can_use_the_same_strata_endpoint(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            endpoint = backends.BenchmarkEndpoint("strata", "swift", "http://127.0.0.1:19999/v1", "noop")
            clients = {
                name: replace(getattr(cfg, name.upper() + "_CLIENT"), agent_dir=root / name / "agent")
                for name in ("pi", "littlecoder", "ohmypi", "nanocoder")
            }
            with (
                patch.object(cfg, "PI_CLIENT", clients["pi"]),
                patch.object(cfg, "LITTLECODER_CLIENT", clients["littlecoder"]),
                patch.object(cfg, "OHMYPI_CLIENT", clients["ohmypi"]),
                patch.object(cfg, "NANOCODER_CLIENT", clients["nanocoder"]),
                patch.dict("os.environ", {"PI_CODING_AGENT_DIR": str(root / "empty-source")}),
            ):
                for name in clients:
                    clients[name].agent_dir.mkdir(parents=True, exist_ok=True)
                    marker = clients[name].agent_dir / "models.json"
                    marker.write_text('{"providers":{"existing":{}}}', encoding="utf-8")
                    state = root / "isolated" / name
                    command, env = client_command(name, benchmark_config(), endpoint, state)
                    self.assertEqual(command[command.index("--provider") + 1], "strata")
                    self.assertEqual(command[command.index("--model") + 1], "swift")
                    if name in ("pi", "littlecoder"):
                        model = json.loads((state / "models.json").read_text())["providers"]["strata"]
                        self.assertEqual(model["baseUrl"], endpoint.base_url)
                    elif name == "nanocoder":
                        self.assertEqual(json.loads(env["NANOCODER_PROVIDERS"])[0]["baseUrl"], endpoint.base_url)
                    self.assertEqual(json.loads(marker.read_text()), {"providers": {"existing": {}}})


if __name__ == "__main__":
    unittest.main()
