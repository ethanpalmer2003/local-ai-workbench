import json
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.benchmarks.coding_agents.shared import benchmark_agents as benchmark
from scripts.benchmarks.coding_agents.shared.framework_tasks import TASKS
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import coding_clients, llamacpp, llamacpp_coding
from scripts.shared.timing import timed
from scripts.tests.shared.model_free import fixture_processes
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.process_fixtures import fake_process


class FrameworkClients(unittest.TestCase):
    def test_hanging_verifier_records_a_failed_grade(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            log = root / "checks.log"
            with patch.object(benchmark.subprocess, "run", side_effect=subprocess.TimeoutExpired("verifier", 30)):
                self.assertFalse(benchmark.grade(TASKS[0], root, log))
            self.assertIn("Verifier exceeded", log.read_text(encoding="utf-8"))

    def test_shared_reasoning_default_and_server_overrides(self):
        for overrides, expected in (({}, "medium"), ({"reasoning-effort": "low"}, "low")):
            command = llamacpp.LlamaConfig(ini_overrides=overrides).build_cmd(Path("reasoning-test.log"))
            indices = [index for index, value in enumerate(command) if value == "--reasoning-effort"]
            self.assertEqual(command[indices[-1] + 1], expected)
        conf = llamacpp.LlamaConfig(ini_overrides={"reasoning-effort": "low", "reasoning-budget": "1024"})
        command = conf.build_cmd(Path("reasoning-test.log"))
        self.assertEqual(command[command.index("--reasoning-budget") + 1], "1024")
        conf = llamacpp.LlamaConfig(ini_overrides={"reasoning": "off", "reasoning-budget": "0"})
        command = conf.build_cmd(Path("reasoning-test.log"))
        self.assertEqual(command[command.index("--reasoning") + 1], "off")
        self.assertEqual(command[command.index("--reasoning-budget") + 1], "0")
        self.assertFalse(coding_clients.model_provider(conf)["models"][0]["compat"]["supportsReasoningEffort"])

    def test_provider_and_state_isolation(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            omp = replace(cfg.OHMYPI_CLIENT, agent_dir=root / "omp" / "agent")
            nano = replace(cfg.NANOCODER_CLIENT, agent_dir=root / "nano")
            with patch.object(cfg, "OHMYPI_CLIENT", omp), patch.object(cfg, "NANOCODER_CLIENT", nano):
                conf = llamacpp.LlamaConfig(port=54321)
                cmd, env = coding_clients.prepare_ohmypi(conf)
                self.assertEqual(cmd[0], str(omp.entry))
                self.assertEqual(env["PI_CODING_AGENT_DIR"], str(omp.agent_dir))
                self.assertEqual((Path.home() / env["PI_CONFIG_DIR"]).resolve(), omp.agent_dir.parent.resolve())
                self.assertTrue((Path(env["XDG_DATA_HOME"]) / "omp").is_dir())
                cmd, env = coding_clients.prepare_nanocoder(conf)
                provider = json.loads(env["NANOCODER_PROVIDERS"])[0]
                self.assertEqual(provider["baseUrl"], "http://127.0.0.1:54321/v1")
                self.assertEqual(provider["models"], [conf.alias])
                self.assertEqual(env["NANOCODER_CONFIG_DIR"], str(nano.agent_dir))
                self.assertNotEqual(nano.agent_dir, omp.agent_dir)

    def test_new_client_launchers_use_shared_server_flow(self):
        for name, prepare in (("ohmypi", "prepare_ohmypi"), ("nanocoder", "prepare_nanocoder")):
            with (
                self.subTest(client=name),
                patch("sys.argv", ["launcher", "--", "--help"]),
                patch.object(coding_clients, prepare, return_value=(["client.exe"], {"STATE": name})),
                patch.object(llamacpp, "launch") as launch,
                patch.object(llamacpp_coding.subprocess, "run") as run,
                patch.object(cfg.LLAMACPP_SERVICE, "mode", cfg.ServiceMode.SERVER),
            ):
                llamacpp_coding.main(default_client=name)
                launch.assert_called_once()
                self.assertEqual(run.call_args.args[0], ["client.exe", "--help"])
                self.assertEqual(run.call_args.kwargs["env"], {"STATE": name})
                self.assertTrue(run.call_args.kwargs["check"])

    @fixture_processes()
    def test_verifier_rejects_broken_fixture_and_accepts_real_fix(self):
        if not cfg.VENV_PYTHON.is_file():
            self.skipTest("this checkout has no virtual environment")
        solutions = {
            "text_utils.py": "def normalize_spaces(text):\n    return ' '.join(text.split())\n",
            "duration.py": (
                "def parse_duration(text):\n    parts = text.strip().split(':')\n"
                "    if len(parts) > 3 or any(not part.isdecimal() for part in parts):\n        raise ValueError\n"
                "    values = list(map(int, parts))\n"
                "    if len(values) > 1 and values[-1] > 59 or len(values) == 3 and values[1] > 59:\n        raise ValueError\n"
                "    return sum(value * 60 ** index for index, value in enumerate(reversed(values)))\n"
            ),
            "ledger.py": (
                "import csv, io\nfrom decimal import Decimal\n\ndef totals(text):\n    result = {}\n"
                "    for row in csv.DictReader(io.StringIO(text)):\n        key = row['category'].strip()\n"
                "        result[key] = result.get(key, Decimal(0)) + Decimal(row['amount'])\n    return result\n"
            ),
            "report.py": (
                "from ledger import totals\n\ndef render(text):\n"
                "    return '\\n'.join(f'{key}: {value:.2f}' for key, value in sorted(totals(text).items()))\n"
            ),
        }
        for task in TASKS:
            with self.subTest(task=task.name), CasePaths(__file__).temporary_directory() as folder:
                root = Path(folder)
                for name, text in task.files.items():
                    (root / name).write_text(text, encoding="utf-8")
                self.assertFalse(benchmark.grade(task, root, root / "checks.log"))
                for name in task.files:
                    (root / name).write_text(solutions[name], encoding="utf-8")
                self.assertTrue(benchmark.grade(task, root, root / "checks.log"))

    def test_benchmark_timeout_stops_client_tree_and_records_failure(self):
        process = fake_process(pid=1234, exit_code=1, wait_timeouts=1)
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(benchmark, "client_command", return_value=(["client"], {"PATH": "original"})),
            patch.object(benchmark.subprocess, "Popen", return_value=process) as popen,
            patch.object(benchmark.launch_util, "kill_process_tree") as kill,
            patch.object(benchmark, "grade", return_value=True),
        ):
            task = replace(TASKS[0], files={**TASKS[0].files, "fixture_test.py": "import unittest\n"})
            result = benchmark.run_task("pi", task, 1, RunPaths(Path(folder)), llamacpp.LlamaConfig(), 1)
            kill.assert_called_once_with(1234)
            self.assertTrue(result.timed_out)
            self.assertFalse(result.passed)
            self.assertTrue(result.tests_passed)
            self.assertEqual(result.max_turns, 12)
            self.assertIn("--extension", popen.call_args.args[0])
            self.assertEqual(popen.call_args.kwargs["env"]["HARNESS_BENCHMARK_MAX_TURNS"], "12")
            self.assertIn("-m unittest discover", popen.call_args.args[0][-1])
            self.assertIn("reply only Done", popen.call_args.args[0][-1])
            self.assertTrue(popen.call_args.kwargs["env"]["PATH"].startswith(str(cfg.VENV_PYTHON.parent)))


if __name__ == "__main__":
    with timed("coding_agents/shared/framework_clients"):
        unittest.main()
