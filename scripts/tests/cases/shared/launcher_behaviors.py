from scripts.tests.shared.process_fixtures import running_process
import io
import json
import subprocess
import sys
import unittest
from scripts.tests.shared.model_free import fixture_processes
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.config import project_config as project_cfg
from scripts.download.frameworks.llamacpp import rdna_build as llamacpp_rdna_build
from scripts.download.input import get_tts_voices, split_from_csv
from scripts.file_util import archive_path
from scripts.launchers.runtime import gpu_memory
from scripts.launchers import launch_util
from scripts.launchers.launch_util import assign_process_to_job
from scripts.launchers.llamacpp.llamacpp import LlamaConfig, LlamaMonitor
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.timing import timed


class LauncherBehaviors(unittest.TestCase):
    def test_console_launch_values_control_window_and_process_ownership(self):
        for value, split, dependent in (
            ("split-independent", True, False),
            ("split-dependent", True, True),
            ("merge", False, True),
        ):
            with (
                self.subTest(mode=value),
                patch.object(launch_util.sys, "platform", "win32"),
                patch.object(launch_util.subprocess, "Popen", return_value=running_process(pid=42)) as spawn,
                patch.object(launch_util, "assign_process_to_job") as assign,
            ):
                launch_util.launch_process(["backend.exe"], title="test", mode=value)
                self.assertEqual(spawn.call_args.kwargs["creationflags"] != 0, split)
                self.assertEqual(assign.called, dependent)
                self.assertEqual(spawn.call_args.args[0][0], "powershell.exe" if split else "backend.exe")

    def test_service_shutdown_ownership_ignores_third_party_document_arguments(self):
        from scripts.launchers import kill_all_services as shutdown

        root = str(project_cfg.BASE_DIR)
        cases = (
            (
                "adobe with workspace document",
                {
                    "name": "AdobeCollabSync.exe",
                    "exe": r"C:\Program Files\Adobe\AdobeCollabSync.exe",
                    "cwd": root,
                    "cmdline": [r"C:\Program Files\Adobe\AdobeCollabSync.exe", root + r"\notes.pdf"],
                },
                False,
            ),
            (
                "adobe with outside cwd",
                {
                    "name": "AdobeCollabSync.exe",
                    "exe": r"C:\Program Files\Adobe\AdobeCollabSync.exe",
                    "cwd": r"C:\Program Files\Adobe",
                    "cmdline": [r"C:\Program Files\Adobe\AdobeCollabSync.exe", root + r"\notes.pdf"],
                },
                False,
            ),
            (
                "project executable",
                {
                    "name": "llama-server.exe",
                    "exe": root + r"\frameworks\llamacpp\llama-server.exe",
                    "cwd": r"C:\Windows\System32",
                    "cmdline": [root + r"\frameworks\llamacpp\llama-server.exe"],
                },
                True,
            ),
            (
                "python running a project script",
                {
                    "name": "python.exe",
                    "exe": r"C:\Program Files\Python\python.exe",
                    "cwd": r"C:\Windows\System32",
                    "cmdline": [r"C:\Program Files\Python\python.exe", root + r"\scripts\launcher.py"],
                },
                True,
            ),
            (
                "python with no workspace reference",
                {
                    "name": "python.exe",
                    "exe": r"C:\Program Files\Python\python.exe",
                    "cwd": r"C:\Program Files\Python",
                    "cmdline": [r"C:\Program Files\Python\python.exe", r"C:\Program Files\Python\tool.py"],
                },
                False,
            ),
        )
        for label, info, expected in cases:
            with self.subTest(label), patch.object(shutdown.psutil, "Process") as process:
                process.return_value.as_dict.return_value = info
                self.assertEqual(shutdown.process_details(4456), (info["name"], expected))

    def test_service_shutdown_non_agent_mode_preserves_agent_stack(self):
        from scripts.launchers import kill_all_services as shutdown

        root = str(project_cfg.BASE_DIR)
        roots = shutdown.agent_roots()
        ports = shutdown.agent_ports()
        self.assertIn(shutdown.cfg.LLAMACPP_SERVICE.port, ports)
        self.assertIn(shutdown.cfg.LLAMACPP_SERVICE.internal_port, ports)
        self.assertIn(shutdown.cfg.STRATA_SERVICE.port, ports)
        agents = (
            {
                "name": "node.exe",
                "exe": r"C:\Program Files\nodejs\node.exe",
                "cwd": root,
                "cmdline": [r"C:\Program Files\nodejs\node.exe", root + r"\frameworks\coding_agents\pi\dist\cli.js"],
            },
            {
                "name": "Command Code.exe",
                "exe": root + r"\frameworks\coding_agents\Command Code\Command Code.exe",
                "cwd": root,
                "cmdline": [root + r"\frameworks\coding_agents\Command Code\Command Code.exe"],
            },
            {
                "name": "llama-server.exe",
                "exe": root + r"\frameworks\llamacpp\llama-server.exe",
                "cwd": r"C:\Windows\System32",
                "cmdline": [root + r"\frameworks\llamacpp\llama-server.exe"],
            },
            {
                "name": "strata.exe",
                "exe": root + r"\frameworks\Strata\engine\strata.exe",
                "cwd": r"C:\Windows\System32",
                "cmdline": [root + r"\frameworks\Strata\engine\strata.exe"],
            },
        )
        for info in agents:
            with self.subTest(info["name"]):
                self.assertTrue(shutdown.is_agent_process(info, roots))
        audio = {
            "name": "audiocpp_server.exe",
            "exe": root + r"\frameworks\audiocpp\vulkan\audiocpp_server.exe",
            "cwd": root,
            "cmdline": [root + r"\frameworks\audiocpp\vulkan\audiocpp_server.exe"],
        }
        self.assertFalse(shutdown.is_agent_process(audio, roots))

    def test_new_terminals_apply_supplied_title_with_safe_powershell_quoting(self):
        for log_file in (None, "C:/logs/it's audio.log"):
            with (
                patch.object(launch_util.sys, "platform", "win32"),
                patch.object(launch_util.subprocess, "Popen", return_value=running_process(pid=42)) as spawn,
            ):
                launch_util.launch_process(
                    ["C:/tools/it's audio.exe", "hello world"],
                    title="AudioCpp Server",
                    mode=launch_util.ConsoleTerminalLaunchMode.SPLIT_INDEPENDENT,
                    log_file=log_file,
                )
            command = spawn.call_args.args[0]
            self.assertEqual(command[:4], ["powershell.exe", "-NoProfile", "-NoExit", "-Command"])
            self.assertIn("WindowTitle = 'AudioCpp Server'", command[4])
            self.assertIn("'C:/tools/it''s audio.exe' 'hello world'", command[4])
            self.assertEqual("Tee-Object" in command[4], log_file is not None)

    def test_hrx_selection_uses_compatible_profile_and_leaves_default_build_unchanged(self):
        from scripts.launchers import launcher_config as cfg

        hrx = LlamaConfig(build_name="hrx")
        self.assertEqual(hrx.name, "swift15-hrx")
        self.assertEqual(LlamaConfig(build_dir=hrx.build_dir).name, "swift15-hrx")
        self.assertEqual(LlamaConfig().name, cfg.LLAMACPP_ACTIVE_CODING_AGENT_PROFILE)
        command = hrx.build_cmd(Path("test.log"))
        self.assertNotIn("--reasoning-effort", command)
        for flag, expected in (("--ctx-size", "8192"), ("--cache-type-k", "f16"), ("--spec-type", "none")):
            index = max(i for i, value in enumerate(command) if value == flag)
            self.assertEqual(command[index + 1], expected)

    def test_stale_pyinstaller_extractions_are_pruned_but_fresh_ones_survive(self):
        import os
        import time

        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            stale = root / "_MEI100"
            fresh = root / "_MEI200"
            for directory in (stale, fresh):
                directory.mkdir()
                (directory / "payload.dll").write_bytes(b"x")
            old = time.time() - 3 * 86400
            os.utime(stale, (old, old))
            with patch.object(launch_util.cfg.LAUNCH, "temp_dir", root):
                self.assertEqual(launch_util.prune_stale_temp(), 1)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())

    def test_child_environment_removes_arch_override_without_mutating_parent(self):
        process = running_process(pid=42)
        with (
            patch.dict(launch_util.os.environ, {"HSA_OVERRIDE_GFX_VERSION": "11.5.1"}),
            patch.object(launch_util.subprocess, "Popen", return_value=process) as spawn,
            patch.object(launch_util, "assign_process_to_job"),
        ):
            launch_util.launch_process(
                ["unused"],
                title="test",
                mode=launch_util.ConsoleTerminalLaunchMode.MERGE,
                env={"HSA_OVERRIDE_GFX_VERSION": None, "ROCR_VISIBLE_DEVICES": "1"},
            )
            self.assertNotIn("HSA_OVERRIDE_GFX_VERSION", spawn.call_args.kwargs["env"])
            self.assertEqual(spawn.call_args.kwargs["env"]["ROCR_VISIBLE_DEVICES"], "1")
            self.assertEqual(launch_util.os.environ["HSA_OVERRIDE_GFX_VERSION"], "11.5.1")

    @unittest.skipUnless(sys.platform == "win32", "Windows job objects")
    def test_job_assignment_closes_process_handle_on_success_and_failure(self):
        for succeeds in (True, False):
            kernel = Mock()
            kernel.OpenProcess.return_value = 123
            kernel.AssignProcessToJobObject.return_value = succeeds
            with (
                patch.object(launch_util, "_kernel32", kernel),
                patch.object(launch_util, "_ensure_job", return_value=456),
            ):
                if succeeds:
                    assign_process_to_job(42)
                else:
                    with self.assertRaises(OSError):
                        assign_process_to_job(42)
            kernel.CloseHandle.assert_called_once_with(123)

    @unittest.skipUnless(sys.platform == "win32", "Windows job objects")
    def test_job_configuration_failure_closes_unpublished_job(self):
        kernel = Mock()
        kernel.CreateJobObjectW.return_value = 456
        kernel.SetInformationJobObject.return_value = False
        with patch.object(launch_util, "_kernel32", kernel), patch.object(launch_util, "_job_handle", None):
            with self.assertRaises(OSError):
                launch_util._ensure_job()
            self.assertIsNone(launch_util._job_handle)
        kernel.CloseHandle.assert_called_once_with(456)

    def test_failed_job_assignment_stops_spawned_process(self):
        process = running_process(pid=42)
        with (
            patch.object(launch_util.subprocess, "Popen", return_value=process),
            patch.object(launch_util, "assign_process_to_job", side_effect=OSError("assignment failed")),
            patch.object(launch_util, "kill_process_tree") as kill,
            self.assertRaises(OSError),
        ):
            launch_util.launch_process(
                ["unused"], title="test", mode=launch_util.ConsoleTerminalLaunchMode.MERGE, report_vram=False
            )
        kill.assert_called_once_with(42)
        process.wait.assert_called_once_with(timeout=10)

    def test_native_allocations_keep_estimate_separate_and_do_not_sum_repeated_buffers(self):
        with CasePaths(__file__).temporary_directory() as folder:
            log = Path(folder) / "server.log"
            log.write_text(
                "fit: projected to use 14000 MiB vs. 16000 MiB\n"
                "load: offloaded 66/66 layers to GPU\n"
                "reserve: ROCm0 compute buffer size = 164.02 MiB\n"
                "reserve: ROCm0 compute buffer size = 164.02 MiB\n",
                encoding="utf-8",
            )
            report = LlamaMonitor(log).allocation_report()
            self.assertEqual((report.projected_mb, report.available_before_mb), (14000, 16000))
            self.assertEqual((report.offloaded_layers, report.total_layers), (66, 66))
            self.assertEqual(len(report.buffer_lines), 1)
            self.assertIsNone(LlamaMonitor(Path(folder) / "missing.log").allocation_report().projected_mb)

    def test_gpu_report_returns_the_same_measured_snapshot_it_prints(self):
        before = gpu_memory.GpuMemorySnapshot(1024, 16384, 0)
        measured = gpu_memory.GpuMemorySnapshot(14336, 16384, 12288)
        output = io.StringIO()
        with (
            patch.object(gpu_memory, "_poll_vram_until_stable", return_value=(measured, True)),
            redirect_stdout(output),
        ):
            report = gpu_memory.report_vram_usage("test", 42, before)
        assert report is not None
        self.assertIs(report.measured, measured)
        self.assertTrue(report.stable)
        self.assertIn("GPU memory measured (stable)", output.getvalue())

    def test_gpu_selects_adapter_used_by_target_process(self):
        samples = [
            {"Path": r"\gpu adapter memory(luid_a_phys_0)\dedicated usage", "Value": 8 * 1024**2},
            {"Path": r"\gpu adapter memory(luid_b_phys_0)\dedicated usage", "Value": 16 * 1024**2},
            {"Path": r"\gpu process memory(pid_42_luid_b_phys_0)\dedicated usage", "Value": 6 * 1024**2},
        ]
        snapshot = gpu_memory.parse_windows_memory(samples, {42}, {})
        assert snapshot is not None
        self.assertEqual(snapshot.used_mb, 16)
        self.assertEqual(snapshot.process_used_mb, 6)

    def test_ffprobe_failure_is_not_a_zero_duration(self):
        error = subprocess.CalledProcessError(1, ["ffprobe"])
        with (
            patch.object(get_tts_voices.subprocess, "run", side_effect=error),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            get_tts_voices.duration(Path("missing.wav"))

    def test_failed_silence_scan_does_not_write_cache(self):
        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(Path, "stat", return_value=Mock(st_size=1, st_mtime_ns=1)),
            patch.object(Path, "resolve", return_value=Path("missing.mp3")),
            patch.object(Path, "write_text") as write,
            patch.object(split_from_csv.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["ffmpeg"])),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                split_from_csv.detect_silences(Path("missing.mp3"), -30, 0.3, Path("cache.json"))
            write.assert_not_called()

    def test_corrupt_transcripts_raise(self):
        with patch.object(Path, "read_text", return_value="{invalid"), self.assertRaises(json.JSONDecodeError):
            get_tts_voices.load_json(Path("subtitles.json"))

    def test_spreadsheet_closes_after_import_failure(self):
        sheet = Mock()
        sheet.iter_rows.side_effect = RuntimeError("bad spreadsheet")
        workbook = Mock(worksheets=[sheet])
        with patch("openpyxl.load_workbook", return_value=workbook), self.assertRaises(RuntimeError):
            get_tts_voices.import_xlsx_transcripts(Path("transcripts.xlsx"), [], {})
        workbook.close.assert_called_once()

    def test_archive_preserves_data_and_rejects_outside_root(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            source = root / "generated"
            source.mkdir()
            (source / "voice.txt").write_text("keep me", encoding="utf-8")
            with patch.object(project_cfg, "BASE_DIR", root):
                archive_path(source, root)
                archived = next((root / "trash").glob("generated-*"))
                self.assertEqual((archived / "voice.txt").read_text(encoding="utf-8"), "keep me")
                self.assertFalse(source.exists())
                with self.assertRaises(ValueError):
                    archive_path(root.parent, root)

    def test_rdna_baseline_uses_explicit_base_key(self):
        with patch.object(Path, "read_text", return_value=json.dumps({"tip": "wrong", "base": "correct"})):
            self.assertEqual(llamacpp_rdna_build.get_baseline_commit(Path("patches")), "correct")

    @fixture_processes()
    def test_server_runner_prints_summary_in_its_own_process(self):
        with CasePaths(__file__).temporary_directory() as folder:
            marker = Path(folder) / "startup.ready"
            marker.touch()
            code = (
                "import sys; from pathlib import Path; from scripts.launchers.llamacpp import llamacpp_terminal as t; "
                "t.get_gpu_memory_snapshot=lambda: None; "
                "t.LlamaMonitor.print_summary=lambda self: print('allocation summary', flush=True); "
                "t.report_vram_usage=lambda *args: print('GPU summary', flush=True); "
                "sys.exit(t.run_server([sys.executable,'-c','import time; time.sleep(0.6)'],"
                "Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[1])/'server.log'))"
            )
            result = subprocess.run(
                [sys.executable, "-c", code, folder, str(marker)],
                cwd=project_cfg.BASE_DIR,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertEqual(result.stdout.splitlines(), ["allocation summary", "GPU summary"])
            self.assertFalse(marker.exists())
            report = json.loads((Path(folder) / "server.memory.json").read_text(encoding="utf-8"))
            self.assertIsNone(report["measured"])
            self.assertIsNone(report["native"]["projected_mb"])


if __name__ == "__main__":
    with timed("shared/launcher_behaviors"):
        unittest.main()
