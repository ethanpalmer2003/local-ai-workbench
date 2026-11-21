import contextlib
import io
import json
import sys
import tarfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import framework_catalog as cfg
from scripts.download.frameworks import update_frameworks as entry
from scripts.download.frameworks import update_shared as updater
from scripts.download.frameworks import update_types
from scripts.download.frameworks.asr import whispercpp
from scripts.download.frameworks.shared import other_updates
from scripts.download.frameworks.strata import updates as strata_updates
from scripts.download.frameworks.tts import updates as tts_updates
from scripts.shared.timing import timed
from scripts.tests.shared.http_fixtures import http_response
from scripts.tests.shared.paths import CasePaths


class FrameworkUpdates(unittest.TestCase):
    pi_tool = next(tool for tool in cfg.TOOLS if tool.package == "@earendil-works/pi-coding-agent")

    def setUp(self):
        # - Toolchain checks run real executables; the model-free suite forbids starting processes.
        check = patch.object(entry.toolchains, "check", return_value=[])
        check.start()
        self.addCleanup(check.stop)
        apply_toolchains = patch.object(entry.toolchains, "apply", return_value=False)
        apply_toolchains.start()
        self.addCleanup(apply_toolchains.stop)
        # - a mocked check writes nothing, so its log directory must not land in the real logs folder
        scratch = contextlib.ExitStack()
        self.addCleanup(scratch.close)
        folder = scratch.enter_context(CasePaths(__file__).temporary_directory())
        logs = patch.object(project_cfg, "LOGS_DIR", Path(folder))
        logs.start()
        self.addCleanup(logs.stop)

    def test_category_selects_only_speech_and_preserves_check_only(self):
        tools = [
            cfg.ToolSpec("llamacpp/demo", "tool.exe", cfg.ReleaseType.DATE, category="llamacpp"),
            cfg.ToolSpec("tts/demo", "tool.exe", cfg.ReleaseType.DATE, category="speech"),
        ]

        def check(tool: cfg.ToolSpec, directory: Path, check_only: bool, summary: updater.UpdateSummary | None = None):
            self.assertTrue(check_only)
            assert summary is not None
            summary.record(tool, "current")
            return True

        with (
            patch.object(sys, "argv", ["update_frameworks", "--category", "speech", "--check-only"]),
            patch.object(cfg, "TOOLS", tools),
            patch.object(updater, "process_tool", side_effect=check) as process,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(entry.main(), 0)
        self.assertEqual([call.args[0].name for call in process.call_args_list], ["tts/demo"])
        self.assertIn("=== TTS / ASR ===", output.getvalue())
        self.assertNotIn("=== LLAMA.CPP ===", output.getvalue())

    def test_sherpa_asset_contains_tts_and_is_cpu_windows_x64(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "tts/sherpa-onnx")
        wanted = {"name": "sherpa-onnx-v2.0.1-win-x64-shared-MD-Release.tar.bz2"}
        response = Mock()
        response.json.return_value = {
            "assets": [{"name": "sherpa-onnx-v2.0.1-win-x64-shared-MD-Release-no-tts.tar.bz2"}, wanted]
        }
        with patch.object(updater.requests, "get", return_value=response):
            _, asset = updater.get_release(tool)
        self.assertEqual(asset, wanted)
        self.assertEqual(tool.exe, "bin/sherpa-onnx-offline-tts.exe")

    def test_tar_release_keeps_sibling_native_libraries(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            scratch = root / "scratch"
            scratch.mkdir()
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w:bz2") as output:
                for name in ("bin/tts.exe", "lib/onnxruntime.dll", "share/espeak/data"):
                    data = b"required runtime asset"
                    member = tarfile.TarInfo("vendor/" + name)
                    member.size = len(data)
                    output.addfile(member, io.BytesIO(data))
            response = http_response(archive.getvalue())
            destination = root / "frameworks/sherpa"
            with (
                patch.object(project_cfg, "FRAMEWORKS_DIR", root / "frameworks"),
                patch.object(updater.requests, "get", return_value=response),
            ):
                updater.update_tool(
                    {"name": "sherpa.tar.bz2", "browser_download_url": "https://example.test/archive"},
                    destination,
                    scratch,
                    "bin/tts.exe",
                )
            self.assertTrue((destination / "bin/tts.exe").is_file())
            self.assertTrue((destination / "lib/onnxruntime.dll").is_file())
            self.assertTrue((destination / "share/espeak/data").is_file())

    def test_incomplete_piper_target_never_replaces_an_installation(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            wheel = root / "piper.whl"
            wheel.write_bytes(b"wheel fixture")

            def install(command, **kwargs):
                target = Path(command[command.index("--target") + 1])
                self.assertTrue(target.is_relative_to(root))
                self.assertIn("--only-binary", command)
                (target / "piper").mkdir()
                (target / "piper/__main__.py").write_text("pass")

            with (
                patch.object(tts_updates.shutil, "which", return_value="uv"),
                patch.object(updater, "download_asset", return_value=wheel),
                patch.object(tts_updates.subprocess, "run", side_effect=install),
                patch.object(updater, "replace_installation") as replace,
                self.assertRaisesRegex(updater.UpdateError, "dependencies are missing"),
            ):
                tts_updates.install_wheel(
                    {"name": "piper.whl", "browser_download_url": "unused"},
                    root / "installed",
                    root,
                    "piper/__main__.py",
                )
            replace.assert_not_called()

    def test_piper_check_only_reads_markers_without_running_python_sources(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "tts/piper")
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(project_cfg, "FRAMEWORKS_DIR", Path(folder)),
        ):
            destination = project_cfg.framework_install_dir(tool.name)
            (destination / "piper").mkdir(parents=True)
            (destination / tool.exe).write_text("pass")
            (destination / updater.MARKER_NAME).write_text("published")
            asset = {"name": "piper_tts-1.8.0-cp39-abi3-win_amd64.whl"}
            (destination / updater.ASSET_MARKER_NAME).write_text(asset["name"])
            with (
                patch.object(
                    updater, "get_release", return_value=({"tag_name": "v1.8.0", "published_at": "published"}, asset)
                ),
                patch.object(updater.subprocess, "run") as run,
            ):
                self.assertTrue(updater.process_tool(tool, Path(folder), True))
            run.assert_not_called()

    def test_official_audiocpp_rocm_asset_selection_and_install_path(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "audiocpp/rocm")
        self.assertTrue(tool.in_use)
        self.assertEqual(tool.release_type, cfg.ReleaseType.DATE)
        self.assertEqual(project_cfg.framework_install_dir(tool.name), project_cfg.AUDIOCPP_ROCM_DIR)
        asset = {"name": "audio-v0.9.3-bin-windows-x64-rocm10.0.0-test.zip"}
        response = Mock()
        response.json.return_value = {
            "tag_name": "v0.9.3",
            "assets": [{"name": "audio-v0.9.3-bin-ubuntu-x64-rocm10.0.0-test.tar.gz"}, asset],
        }
        with patch.object(updater.requests, "get", return_value=response):
            _, selected = updater.get_release(tool)
        self.assertEqual(selected, asset)

    def test_whisper_stable_release_resolves_its_linked_binary_release(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "asr/whispercpp/vulkan-build")
        stable = Mock()
        stable.json.return_value = {
            "tag_name": "v1.9.5",
            "assets": [],
            "body": "Nightly build: [b5454](https://github.com/ggml-org/whisper.cpp/releases/tag/b5454)",
        }
        with patch.object(whispercpp.github.requests, "get", return_value=stable):
            self.assertEqual(whispercpp.latest_source_tag(tool), "b5454")

    def test_current_whisper_build_active_and_legacy_disabled(self):
        tools = [tool for tool in cfg.TOOLS if tool.name.startswith("asr/whispercpp/")]
        self.assertEqual({tool.name for tool in tools}, {"asr/whispercpp/vulkan", "asr/whispercpp/vulkan-build"})
        legacy = next(tool for tool in tools if tool.name == "asr/whispercpp/vulkan")
        self.assertFalse(legacy.in_use)
        built = next(tool for tool in tools if tool.name == "asr/whispercpp/vulkan-build")
        self.assertTrue(built.in_use)
        self.assertEqual(built.release_type, cfg.ReleaseType.NATIVE_BUILD)

    def test_final_status_groups_appear_once_in_order_and_unused_tools_are_not_processed(self):
        tools = [
            cfg.ToolSpec("patched-source", "", cfg.ReleaseType.SOURCE),
            cfg.ToolSpec("unused-a", "", cfg.ReleaseType.MANUAL, in_use=False),
            cfg.ToolSpec("unused-b", "", cfg.ReleaseType.MANUAL, in_use=False),
        ]

        def process(tool: cfg.ToolSpec, _folder: Path, _check: bool, summary: updater.UpdateSummary | None = None):
            updater.report_rebuild(tool, summary)
            return True

        with (
            patch.object(sys, "argv", ["update_frameworks", "--check-only"]),
            patch.object(cfg, "TOOLS", tools),
            patch.object(updater, "process_tool", side_effect=process) as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(entry.main(), 0)
        text = output.getvalue()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(text.count("UPSTREAM CHANGED; MANUAL MERGE/REBUILD REQUIRED"), 1)
        # - Inactive entries are ignored outright: not checked, not listed.
        self.assertNotIn("NOT CURRENTLY IN USE", text)
        self.assertNotIn("unused-a", text)
        self.assertNotIn("unused-b", text)
        self.assertNotIn("=== unused-a ===", text)

    def test_strata_delegates_to_native_updater_with_check_only_and_clean_python_environment(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "host").mkdir()
            (root / "host/package.json").write_text(json.dumps({"version": "0.2.6"}))
            with (
                patch.dict(
                    strata_updates.os.environ, {"PYTHONHOME": "wrong", "PYTHONPATH": "wrong", "STRATA_NO_ACQUIRE": "1"}
                ),
                patch.object(strata_updates.subprocess, "run") as run,
            ):
                run.return_value.returncode = 0
                run.return_value.stdout = json.dumps(
                    {
                        part: {"status": "current", "installed": "1", "offered": "1"}
                        for part in ("engine", "control", "app")
                    }
                )
                strata_updates.process(root)
            command = run.call_args.args[0]
            self.assertIn("--check", command)
            self.assertIn("--app", command)
            self.assertEqual(command[command.index("--app-version") + 1], "0.2.6")
            self.assertIn("--model-config", command)
            environment = run.call_args.kwargs["env"]
            for key in ("PYTHONHOME", "PYTHONPATH", "STRATA_NO_ACQUIRE"):
                self.assertNotIn(key, environment)

    def _comfyui_tool(self):
        return next(tool for tool in cfg.TOOLS if tool.name == "comfyui/rocm")

    def test_comfyui_commit_match_skips_the_external_updater(self):
        tool = self._comfyui_tool()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(other_updates.subprocess, "run", return_value=Mock(stdout="abc\n")) as run,
            patch.object(other_updates.requests, "get", return_value=Mock(json=lambda: {"sha": "abc"})),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            summary = updater.UpdateSummary()
            other_updates.process_bat(tool, Path(folder), Path(folder) / tool.exe, False, summary)
        self.assertIn("UP TO DATE", output.getvalue())
        self.assertEqual(summary.current, [tool.name])
        # - one call: the commit comparison; the updater never runs when the commits match
        self.assertEqual(run.call_count, 1)

    def test_comfyui_newer_commit_runs_the_external_updater_and_records_success(self):
        tool = self._comfyui_tool()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(
                other_updates.subprocess, "run", side_effect=[Mock(stdout="local\n"), Mock(returncode=0)]
            ) as run,
            patch.object(other_updates.requests, "get", return_value=Mock(json=lambda: {"sha": "remote"})),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            summary = updater.UpdateSummary()
            updater_exe = Path(folder) / tool.exe
            updater_exe.write_text("@echo off\n")
            other_updates.process_bat(tool, Path(folder), updater_exe, False, summary)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(summary.current[0].startswith(tool.name))
        self.assertEqual(summary.failures, [])

    def test_a_failed_external_updater_is_a_failure_not_an_available_update(self):
        tool = self._comfyui_tool()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(other_updates.subprocess, "run", side_effect=[Mock(stdout="local\n"), Mock(returncode=1)]),
            patch.object(other_updates.requests, "get", return_value=Mock(json=lambda: {"sha": "remote"})),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            summary = updater.UpdateSummary()
            updater_exe = Path(folder) / tool.exe
            updater_exe.write_text("@echo off\n")
            other_updates.process_bat(tool, Path(folder), updater_exe, False, summary)
        # - a fetch that dies mid-transfer must not read as a finished update
        self.assertTrue(summary.failures[0].startswith(tool.name))
        self.assertIn("exit", summary.failures[0])
        self.assertEqual(summary.available, [])

    def test_summary_collapses_a_component_onto_one_line(self):
        summary = updater.UpdateSummary()
        strata = next(tool for tool in cfg.TOOLS if tool.name == "strata")
        summary.record(strata, "current", "engine: 0.1.57")
        summary.record(strata, "current", "app: 0.2.11")
        pi = next(tool for tool in cfg.TOOLS if tool.name == "coding_agents/pi")
        summary.record(pi, "current")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            summary.print()
        text = output.getvalue()
        self.assertIn("- strata: engine: 0.1.57; app: 0.2.11", text)
        self.assertIn("- coding_agents/pi", text)
        self.assertNotIn("(current)", text)

    def test_every_release_type_maps_to_one_reported_update_kind(self):
        self.assertEqual(set(update_types.KIND_OF_RELEASE), set(cfg.ReleaseType))
        self.assertEqual(set(update_types.KIND_OF_RELEASE.values()), set(update_types.UPDATE_KINDS))
        self.assertEqual(len(update_types.UPDATE_KINDS), len(set(update_types.UPDATE_KINDS)))
        self.assertEqual(len(update_types.UPDATE_KINDS), 9)

    def test_summary_nests_status_under_update_kind_inside_its_category(self):
        summary = updater.UpdateSummary()
        git = cfg.ToolSpec("benchmarks/demo", "", cfg.ReleaseType.SOURCE, category="other")
        npm = cfg.ToolSpec("coding_agents/demo", "", cfg.ReleaseType.NPM, category="other")
        release = cfg.ToolSpec("tts/demo", "", cfg.ReleaseType.DATE, category="speech")
        summary.record(git, "current")
        summary.record(npm, "available")
        summary.record(release, "available")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            summary.print()
        text = output.getvalue()
        other = text.split("=== OTHER ===", 1)[1]
        speech = text.split("=== TTS / ASR ===", 1)[1].split("=== OTHER ===", 1)[0]
        self.assertLess(other.index("--- git fast-forward ---"), other.index("--- npm package ---"))
        self.assertLess(other.index("[UP TO DATE]"), other.index("[UPDATE AVAILABLE]"))
        self.assertIn("- benchmarks/demo", other.split("--- npm package ---")[0])
        self.assertIn("- coding_agents/demo", other.split("--- npm package ---")[1])
        self.assertNotIn("npm package", speech)
        self.assertIn("--- github release ---", speech)
        self.assertIn("- tts/demo", speech)

    def test_a_component_split_across_update_kinds_is_expanded_not_repeated(self):
        summary = updater.UpdateSummary()
        cli = cfg.ToolSpec("coding_agents/demo", "", cfg.ReleaseType.NPM, category="other")
        app = cfg.ToolSpec(
            "coding_agents/demo-desktop", "", cfg.ReleaseType.DESKTOP, category="other", group="coding_agents/demo"
        )
        summary.record(cli, "current")
        summary.record(app, "current")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            summary.print()
        text = output.getvalue()
        self.assertIn("- coding_agents/demo\n", text)
        self.assertIn("- coding_agents/demo-desktop", text)
        self.assertNotIn("- coding_agents/demo:", text)

    def test_a_failure_names_its_own_entry_instead_of_the_collapsed_group(self):
        summary = updater.UpdateSummary()
        speed = next(tool for tool in cfg.TOOLS if tool.name == "benchmarks/speed-bench")
        club = next(tool for tool in cfg.TOOLS if tool.name == "benchmarks/club-rdna16")
        summary.record(club, "current")
        summary.record(speed, "failures")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            summary.print()
        text = output.getvalue()
        self.assertIn("- benchmarks/club-rdna16", text)
        self.assertIn("- benchmarks/speed-bench", text)
        self.assertNotIn("- benchmarks\n", text)

    def test_custom_node_behind_its_origin_is_detected(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            config = root / "custom_nodes" / "Node-A" / ".git"
            config.mkdir(parents=True)
            (config / "config").write_text(
                '[remote "origin"]\n\turl = https://github.com/owner/node-a.git\n', encoding="utf-8"
            )
            with (
                patch.object(
                    other_updates.subprocess, "run", side_effect=[Mock(stdout="main\n"), Mock(stdout="abc1234\n")]
                ),
                patch.object(other_updates.shared.github, "get_json", return_value={"sha": "def5678"}),
            ):
                drift = other_updates.checkout_drift(root / "custom_nodes", {"ComfyUI-Manager"})
        self.assertEqual(drift, [("Node-A", "abc1234", "def5678", False)])

    def test_managed_nodes_are_read_from_the_vendor_updater(self):
        with CasePaths(__file__).temporary_directory() as folder:
            script = Path(folder) / "updater.bat"
            script.write_text(
                'call :UpdateCustomNode "ComfyUI-Manager" "https://github.com/Comfy-Org/ComfyUI-Manager"\n'
                'call :UpdateCustomNode "ComfyUI-INT8-Fast-ROCM" "https://github.com/patientx/ComfyUI-INT8-Fast-ROCM"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                other_updates.managed_nodes(script),
                [
                    ("ComfyUI-Manager", "https://github.com/Comfy-Org/ComfyUI-Manager"),
                    ("ComfyUI-INT8-Fast-ROCM", "https://github.com/patientx/ComfyUI-INT8-Fast-ROCM"),
                ],
            )

    def test_matching_core_commit_with_a_behind_node_still_queues_the_updater(self):
        tool = self._comfyui_tool()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(
                other_updates.subprocess,
                "run",
                side_effect=[Mock(stdout="core\n"), Mock(stdout="main\n"), Mock(stdout="node1\n")],
            ),
            patch.object(other_updates.shared.github, "get_json", return_value={"sha": "core"}),
            patch.object(other_updates, "checkout_drift", return_value=[("Node-A", "node1", "node2", False)]),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            summary = updater.UpdateSummary()
            other_updates.process_bat(tool, Path(folder), Path(folder) / tool.exe, True, summary)
        self.assertIn("behind: Node-A node1 -> node2 (updater pull)", output.getvalue())
        self.assertEqual(summary.available[0].split(" :: ")[0], tool.name)
        self.assertIn("custom node(s) behind", summary.available[0])

    def test_all_checks_and_grouped_plan_precede_updates_and_failed_checks_are_not_applied(self):
        tools = [cfg.ToolSpec(name, "", cfg.ReleaseType.SOURCE) for name in ("new", "current", "patched", "broken")]
        tools.append(cfg.ToolSpec("unused", "", cfg.ReleaseType.MANUAL, in_use=False))
        events = []

        def process(tool: cfg.ToolSpec, _folder: Path, check_only: bool, summary: updater.UpdateSummary | None = None):
            events.append((tool.name, check_only))
            if check_only:
                print("Status: SOURCE UP TO DATE")
                assert summary is not None
                summary.record(
                    tool,
                    {"new": "available", "current": "current", "patched": "manual_rebuild", "broken": "available"}[
                        tool.name
                    ],
                )
                return tool.name != "broken"
            self.assertEqual(events[:4], [(tool.name, True) for tool in tools[:4]])
            self.assertEqual(tool.name, "new")
            return True

        with CasePaths(__file__).temporary_directory() as folder:
            with (
                patch.object(sys, "argv", ["update_frameworks", "--yes"]),
                patch.object(cfg, "TOOLS", tools),
                patch.object(project_cfg, "LOGS_DIR", Path(folder)),
                patch.object(updater, "process_tool", side_effect=process),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(entry.main(), 1)
            text = output.getvalue()
            self.assertNotIn("Status: SOURCE UP TO DATE", text)
            self.assertEqual(text.count("[UP TO DATE]"), 1)
            self.assertEqual(text.count("[UPDATE AVAILABLE]"), 1)
            self.assertLess(text.index("[CHECK FAILED]"), text.index("=== APPLYING UPDATES ==="))
            self.assertNotIn("NOT CURRENTLY IN USE", text)
            self.assertNotIn(("unused", True), events)
            self.assertEqual(events[-1], ("new", False))
            log = next(Path(folder).rglob("*.log")).read_text()
            self.assertIn("Status: SOURCE UP TO DATE", log)

    def test_strata_reports_current_parts_without_a_manual_notice(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "strata")
        summary = updater.UpdateSummary()
        report = {
            "engine": {"installed": "0.1.59", "offered": "0.1.59", "status": "current"},
            "control": {"installed": "0.1.51", "offered": None, "status": "not-in-feed"},
            "app": {"installed": "0.2.13", "offered": "0.2.13", "status": "current"},
        }
        with patch.object(strata_updates, "process", return_value=report) as native:
            self.assertTrue(updater.process_tool(tool, Path("unused"), True, summary))
        native.assert_called_once()
        self.assertEqual(summary.manual_check, [])
        self.assertEqual(len(summary.current), 1)
        self.assertTrue(summary.current[0].startswith("strata"))
        self.assertEqual(summary.apply_keys, set())

    def test_strata_reports_a_manual_notice_only_when_a_part_is_newer(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "strata")
        summary = updater.UpdateSummary()
        report = {
            "engine": {"installed": "0.1.50", "offered": "0.1.59", "status": "available"},
            "control": {"installed": "0.1.51", "offered": None, "status": "not-in-feed"},
            "app": {"installed": "0.2.13", "offered": "0.2.13", "status": "current"},
        }
        with patch.object(strata_updates, "process", return_value=report):
            self.assertTrue(updater.process_tool(tool, Path("unused"), True, summary))
        self.assertEqual(summary.current, [])
        self.assertEqual(len(summary.manual_check), 1)
        self.assertIn("0.1.59", summary.manual_check[0])
        self.assertEqual(summary.apply_keys, set())

    def test_a_newer_strata_part_is_never_work_for_this_run(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "strata")
        summary = updater.UpdateSummary()
        report = {
            "engine": {"installed": "0.1.50", "offered": "0.1.59", "status": "available"},
            "control": {"installed": "0.1.51", "offered": None, "status": "not-in-feed"},
            "app": {"installed": "0.2.13", "offered": "0.2.13", "status": "current"},
        }
        with patch.object(strata_updates, "process", return_value=report), contextlib.redirect_stdout(io.StringIO()):
            updater.process_tool(tool, Path("unused"), True, summary)
        # - the app installs its own bundle, so a notice must never enter the apply set
        self.assertEqual(len(summary.manual_check), 1)
        self.assertIn("0.1.59", summary.manual_check[0])
        self.assertEqual(summary.apply_keys, set())

    def test_strata_update_command_is_a_check_with_a_materialized_config(self):
        command = strata_updates.update_command(project_cfg.FRAMEWORKS_DIR / "strata")
        self.assertIn("--check", command)
        self.assertEqual(command[-2:], ["--output", "json"])
        config = Path(command[command.index("--model-config") + 1])
        self.assertTrue(config.is_file())
        self.assertNotIn("{AI_ROOT}", config.read_text(encoding="utf-8"))

    def test_pi_package_installation_is_deferred_until_after_all_checks(self):
        from scripts.download.frameworks.coding_agents.pi import packages as pi_packages

        events = []

        def process(tool: cfg.ToolSpec, _folder: Path, check_only: bool, summary: updater.UpdateSummary | None = None):
            events.append("check")
            self.assertTrue(check_only)
            assert summary is not None
            summary.record(tool, "current")
            return True

        with (
            patch.object(sys, "argv", ["update_frameworks", "--yes"]),
            patch.object(cfg, "TOOLS", [self.pi_tool]),
            patch.object(updater, "process_tool", side_effect=process),
            patch.object(pi_packages, "sync_plan", return_value=(["new-extension"], [])),
            patch.object(pi_packages, "sync", side_effect=lambda **_: events.append("sync")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(entry.main(), 0)
        self.assertEqual(events, ["check", "sync"])

    def test_pending_patch_backups_use_fresh_local_state_without_merging(self):
        tool = cfg.hrx_tools()[0]
        summary = updater.UpdateSummary(patch_sources=[(tool, Path("source"), "upstream")])
        with (
            patch.object(
                updater.subprocess, "run", side_effect=[Mock(stdout="fresh-head\n"), Mock(stdout=" M local.cpp\n")]
            ) as run,
            patch.object(updater, "snapshot_source_patches", return_value=Path("backup")) as snapshot,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(updater.save_pending_patches(summary, io.StringIO()))
        snapshot.assert_called_once_with(tool, Path("source"), "fresh-head", "upstream", " M local.cpp\n")
        self.assertEqual(run.call_count, 2)
        self.assertFalse(any("pull" in call.args[0] for call in run.call_args_list))

    def test_legacy_audiocpp_asset_is_recognized(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "audiocpp/additions/rocm/7.1-old")
        with CasePaths(__file__).temporary_directory() as folder:
            destination = Path(folder) / tool.name
            destination.mkdir(parents=True)
            (destination / "README-HIP.txt").write_text("audio.cpp Windows HIP package (rocm6.4)", encoding="utf-8")
            self.assertEqual(updater.installed_release_asset(tool, destination), "audiocpp-bin-win-hip-rocm6.4-x64.zip")

    def test_asset_checksum_mismatch_prevents_replacement(self):
        response = http_response(b"wrong content")
        asset: updater.Asset = {
            "name": "tool.zip",
            "browser_download_url": "https://example.test/tool.zip",
            "digest": "sha256:" + "0" * 64,
        }
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(project_cfg, "FRAMEWORKS_DIR", Path(folder)),
            patch.object(updater.requests, "get", return_value=response),
            patch.object(updater, "replace_installation") as replace,
        ):
            with self.assertRaisesRegex(updater.UpdateError, "checksum mismatch"):
                updater.update_tool(asset, Path(folder) / "tool", Path(folder), "tool.exe")
            replace.assert_not_called()

    def test_clean_build_only_source_reports_a_build_and_pulls_only_when_applying(self):
        tool = cfg.ToolSpec("avalon", "", cfg.ReleaseType.SOURCE, repo="example/avalon", rebuild_required=True)
        response = Mock()
        response.json.return_value = {"sha": "upstream"}
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            with (
                patch.object(updater.requests, "get", return_value=response),
                patch.object(updater.subprocess, "check_output", return_value="base\n"),
                patch.object(updater.subprocess, "run") as run,
            ):
                run.side_effect = [Mock(stdout="base\n"), Mock(returncode=1), Mock(stdout="0\n"), Mock(stdout="")]
                summary = updater.UpdateSummary()
                self.assertEqual(updater.process_source(tool, root, True, summary=summary), "base")
                self.assertEqual(summary.source_build, ["avalon"])
                self.assertIn("avalon", summary.apply_keys)
                self.assertFalse(any("pull" in call.args[0] for call in run.call_args_list))

                run.side_effect = [
                    Mock(stdout="base\n"),
                    Mock(returncode=1),
                    Mock(stdout="0\n"),
                    Mock(stdout=""),
                    Mock(),
                ]
                summary = updater.UpdateSummary()
                updater.process_source(tool, root, False, summary=summary)
                self.assertTrue(any("pull" in call.args[0] for call in run.call_args_list))
                self.assertEqual(summary.manual_rebuild, [])
                self.assertEqual(summary.source_build, ["avalon"])

    def test_source_with_local_edits_reports_a_merge_instead_of_failing_the_pull(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "avalon")
        response = Mock()
        response.json.return_value = {"sha": "upstream"}
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            with (
                patch.object(updater.requests, "get", return_value=response),
                patch.object(updater.subprocess, "check_output", return_value="base\n"),
                patch.object(updater.subprocess, "run") as run,
            ):
                run.side_effect = [
                    Mock(stdout="base\n"),
                    Mock(returncode=1),
                    Mock(stdout="0\n"),
                    Mock(stdout=" M ggml/src/ggml-cuda/moe-cache.cu\n"),
                ]
                summary = updater.UpdateSummary()
                self.assertEqual(updater.process_source(tool, root, False, summary=summary), "base")
                self.assertFalse(any("pull" in call.args[0] for call in run.call_args_list))
                self.assertEqual(summary.manual_rebuild, ["avalon"])
                self.assertEqual(summary.source_build, [])

    def test_local_commit_ahead_of_upstream_is_replayed_instead_of_reported(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "avalon")
        response = Mock()
        response.json.return_value = {"sha": "upstream"}
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            with (
                patch.object(updater.requests, "get", return_value=response),
                patch.object(updater.subprocess, "check_output", return_value="base\n"),
                patch.object(updater.subprocess, "run") as run,
            ):
                run.side_effect = [
                    Mock(stdout="base\n"),
                    Mock(returncode=1),
                    Mock(stdout="1\n", returncode=0),
                    Mock(stdout=""),
                    Mock(),
                ]
                summary = updater.UpdateSummary()
                updater.process_source(tool, root, False, summary=summary)
                pulls = [call.args[0] for call in run.call_args_list if "pull" in call.args[0]]
                self.assertEqual(len(pulls), 1)
                self.assertIn("--rebase", pulls[0])
                self.assertIn("--autostash", pulls[0])
                self.assertEqual(summary.manual_rebuild, [])
                self.assertEqual(summary.source_build, ["avalon"])

    feed_yaml = (
        "version: 0.2.2-rc.1\n"
        "path: https://example.test/deepseek-harness-0.2.2-rc.1-win-x64.exe\n"
        "sha512: abc\n"
        "files:\n"
        "  - url: https://example.test/deepseek-harness-0.2.2-rc.1-win-x64.exe\n"
        "    sha512: abc\n"
        "    size: 293425336\n"
    )

    def _desktop_tool(self):
        return next(tool for tool in cfg.TOOLS if tool.name == "coding_agents/deepseek")


if __name__ == "__main__":
    with timed("shared/framework_updates"):
        unittest.main()
