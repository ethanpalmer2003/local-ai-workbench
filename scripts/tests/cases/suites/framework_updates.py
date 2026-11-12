import contextlib
import io
import json
import os
import sys
import tarfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import build_frameworks as build_all
from scripts.download.frameworks import framework_catalog as cfg
from scripts.download.frameworks import update_frameworks as entry
from scripts.download.frameworks import update_shared as updater
from scripts.download.frameworks import update_types
from scripts.download.frameworks.asr import whispercpp
from scripts.download.frameworks.shared import other_updates
from scripts.download.frameworks.strata import updates as strata_updates
from scripts.download.frameworks.tts import updates as tts_updates
from scripts.tests.shared.http_fixtures import http_response
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.timing import timed


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

    def test_category_selects_only_speech_and_preserves_check_only(self):
        tools = [
            cfg.ToolSpec("llamacpp/demo", "tool.exe", cfg.ReleaseType.DATE, category="llamacpp"),
            cfg.ToolSpec("tts/demo", "tool.exe", cfg.ReleaseType.DATE, category="speech"),
        ]

        def check(tool, directory, check_only, summary=None):
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

        def process(tool, _folder, _check, summary=None):
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
                strata_updates.process(root, True)
            command = run.call_args.args[0]
            self.assertIn("--check", command)
            self.assertIn("--app", command)
            self.assertEqual(command[command.index("--app-version") + 1], "0.2.6")
            self.assertIn("--model-config", command)
            environment = run.call_args.kwargs["env"]
            for key in ("PYTHONHOME", "PYTHONPATH", "STRATA_NO_ACQUIRE"):
                self.assertNotIn(key, environment)

    def test_strata_app_installers_are_listed_oldest_first(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            app = root / "strata/desktop/components/.updates/app"
            app.mkdir(parents=True)
            for name, hours in (("Strata-0.2.9-setup.exe", 5), ("Strata-0.2.11-setup.exe", 1)):
                installer = app / name
                installer.write_bytes(b"x")
                stamp = time.time() - hours * 3600
                os.utime(installer, (stamp, stamp))
            with patch.object(strata_updates.project_cfg, "STATE_DIR", root):
                self.assertEqual(
                    [path.name for path in strata_updates.app_installers()],
                    ["Strata-0.2.9-setup.exe", "Strata-0.2.11-setup.exe"],
                )

    def _strata_app_fixture(self, root: Path, versions: tuple[str, ...]) -> Path:
        app = root / "strata/desktop/components/.updates/app"
        app.mkdir(parents=True)
        for index, version in enumerate(versions):
            installer = app / f"Strata-{version}-windows-x64-setup.exe"
            installer.write_bytes(b"x")
            stamp = time.time() + index
            os.utime(installer, (stamp, stamp))
        return app

    def test_strata_app_installer_runs_silently_and_prunes_superseded_files(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            app = self._strata_app_fixture(root, ("0.2.9", "0.2.11"))
            with (
                patch.object(strata_updates.project_cfg, "STATE_DIR", root),
                patch.object(strata_updates, "installed_app_version", side_effect=["0.2.6", "0.2.11"]),
                patch.object(strata_updates.subprocess, "run") as run,
            ):
                self.assertEqual(strata_updates.install_app(Path("C:/AI/frameworks/Strata")), "0.2.11")
            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertTrue(command[0].endswith("Strata-0.2.11-windows-x64-setup.exe"))
            self.assertEqual(command[1:], ["/S", "/D=C:\\AI\\frameworks\\Strata"])
            self.assertEqual([path.name for path in app.iterdir()], ["Strata-0.2.11-windows-x64-setup.exe"])

    def test_strata_app_installer_that_does_not_take_reports_a_failure(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            self._strata_app_fixture(root, ("0.2.11",))
            with (
                patch.object(strata_updates.project_cfg, "STATE_DIR", root),
                patch.object(strata_updates, "installed_app_version", side_effect=["0.2.6", "0.2.6"]),
                patch.object(strata_updates.subprocess, "run"),
                self.assertRaises(updater.UpdateError),
            ):
                strata_updates.install_app(Path("C:/AI/frameworks/Strata"))

    def _comfyui_tool(self):
        return next(tool for tool in cfg.TOOLS if tool.name == "comfyui/rocm")

    def test_comfyui_commit_match_skips_the_external_updater(self):
        tool = self._comfyui_tool()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(other_updates.subprocess, "run", return_value=Mock(stdout="abc\n")),
            patch.object(other_updates.requests, "get", return_value=Mock(json=lambda: {"sha": "abc"})),
            patch.object(other_updates.subprocess, "Popen") as launch,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            summary = updater.UpdateSummary()
            other_updates.process_bat(tool, Path(folder), Path(folder) / tool.exe, False, summary)
        self.assertIn("UP TO DATE", output.getvalue())
        self.assertEqual(summary.current, [tool.name])
        launch.assert_not_called()

    def test_comfyui_newer_commit_queues_the_external_updater(self):
        tool = self._comfyui_tool()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(other_updates.subprocess, "run", return_value=Mock(stdout="local\n")),
            patch.object(other_updates.requests, "get", return_value=Mock(json=lambda: {"sha": "remote"})),
            patch.object(other_updates.subprocess, "Popen") as launch,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            summary = updater.UpdateSummary()
            updater_exe = Path(folder) / tool.exe
            updater_exe.write_text("@echo off\n")
            other_updates.process_bat(tool, Path(folder), updater_exe, False, summary)
        self.assertEqual(summary.available, [tool.name])
        launch.assert_called_once()

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

        def process(tool, _folder, check_only, summary=None):
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
                patch.object(sys, "argv", ["update_frameworks"]),
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

    def test_a_newer_strata_part_is_applied_only_with_the_opt_in(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "strata")
        summary = updater.UpdateSummary(optional_apply={"strata"})
        report = {
            "engine": {"installed": "0.1.50", "offered": "0.1.59", "status": "available"},
            "control": {"installed": "0.1.51", "offered": None, "status": "not-in-feed"},
            "app": {"installed": "0.2.13", "offered": "0.2.13", "status": "current"},
        }
        with patch.object(strata_updates, "process", return_value=report):
            self.assertTrue(updater.process_tool(tool, Path("unused"), True, summary))
        self.assertEqual(summary.manual_check, [])
        self.assertIn("strata", summary.apply_keys)

    def test_pi_package_installation_is_deferred_until_after_all_checks(self):
        from scripts.download.frameworks.coding_agents.pi import packages as pi_packages

        events = []

        def process(tool, _folder, check_only, summary=None):
            events.append("check")
            self.assertTrue(check_only)
            assert summary is not None
            summary.record(tool, "current")
            return True

        with (
            patch.object(sys, "argv", ["update_frameworks"]),
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

    def test_strata_update_command_hands_over_a_materialized_config(self):
        command = strata_updates.update_command(project_cfg.FRAMEWORKS_DIR / "strata", True)
        config = Path(command[command.index("--model-config") + 1])
        self.assertTrue(config.is_file())
        self.assertNotIn("{AI_ROOT}", config.read_text(encoding="utf-8"))

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

    def test_local_commit_in_a_dirty_tree_still_reports_a_merge(self):
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
                    Mock(stdout=" M ggml/src/ggml-cuda/moe-cache.cu\n"),
                ]
                summary = updater.UpdateSummary()
                updater.process_source(tool, root, False, summary=summary)
                self.assertFalse(any("pull" in call.args[0] for call in run.call_args_list))
                self.assertEqual(summary.manual_rebuild, ["avalon"])
                self.assertEqual(summary.source_build, [])

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

    def test_closed_desktop_app_is_queued_for_a_silent_install(self):
        tool = self._desktop_tool()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(other_updates.requests, "get", return_value=Mock(text=self.feed_yaml)) as get,
            patch.object(other_updates, "installed_desktop_version", return_value="0.2.1-rc.5"),
            patch.object(other_updates, "app_running", return_value=False),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            summary = updater.UpdateSummary()
            other_updates.process_desktop(tool, Path(folder), True, summary)
        self.assertEqual(get.call_args.args[0], "https://download.deepseek.com/dsh-desk/feeds/win-x64/nightly.yml")
        self.assertIn("Status: UPDATE AVAILABLE", output.getvalue())
        self.assertEqual(summary.available, [tool.name])
        self.assertIn(tool.name, summary.apply_keys)

    def test_running_desktop_app_is_stopped_and_then_installed(self):
        tool = self._desktop_tool()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(other_updates.requests, "get", return_value=Mock(text=self.feed_yaml)),
            patch.object(other_updates, "installed_desktop_version", return_value="0.2.1-rc.5"),
            patch.object(other_updates, "app_running", return_value=True),
            patch.object(other_updates, "stop_app") as stop,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            summary = updater.UpdateSummary()
            other_updates.process_desktop(tool, Path(folder), True, summary)
        stop.assert_called_once()
        self.assertIn("Status: UPDATE AVAILABLE", output.getvalue())
        self.assertEqual(summary.available, [tool.name])
        self.assertIn(tool.name, summary.apply_keys)

    def test_desktop_installer_runs_silently_and_verifies_the_version(self):
        tool = self._desktop_tool()
        installer = Path("C:/cache/deepseek-harness-0.2.2-rc.1-win-x64.exe")
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(other_updates.requests, "get", return_value=Mock(text=self.feed_yaml)),
            patch.object(other_updates, "installed_desktop_version", side_effect=["0.2.1-rc.5", "0.2.2-rc.1"]),
            patch.object(other_updates, "app_running", return_value=False),
            patch.object(other_updates, "download_feed_installer", return_value=installer),
            patch.object(other_updates.subprocess, "run") as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            summary = updater.UpdateSummary()
            other_updates.process_desktop(tool, Path(folder), False, summary)
        self.assertEqual(run.call_args.args[0], [str(installer), "/S", f"/D={Path(folder)}"])
        self.assertEqual(summary.available, [tool.name])

    def test_build_command_targets_are_the_sources_compiled_by_hand(self):
        targets = build_all.build_targets()
        self.assertEqual([tool.name for tool in targets], ["avalon"])
        self.assertEqual(targets[0].build_command[:2], ("cmake", "--build"))

    def test_missing_source_check_only_does_not_clone(self):
        response = Mock()
        response.json.return_value = {"sha": "latest"}
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(updater.requests, "get", return_value=response),
            patch.object(updater.subprocess, "run") as run,
        ):
            self.assertEqual(updater.process_source(cfg.hrx_tools()[0], Path(folder) / "missing", True), "latest")
            run.assert_not_called()

    def test_dirty_hrx_source_saves_binary_patch_and_never_pulls(self):
        tool = cfg.hrx_tools()[0]
        response = Mock()
        response.json.return_value = {"sha": "upstream"}
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            with (
                patch.object(updater.requests, "get", return_value=response),
                patch.object(project_cfg, "STATE_DIR", root / "state"),
                patch.object(updater.subprocess, "run") as run,
            ):
                run.side_effect = [Mock(stdout="base\n"), Mock(stdout=" M queue.cpp\n"), Mock(stdout=b"binary patch\n")]
                self.assertEqual(updater.process_source(tool, root, False), "base")
                self.assertFalse(any("pull" in call.args[0] for call in run.call_args_list))
                snapshot = next((root / "state/llamacpp/hrx/source-patches").rglob("local.patch"))
                self.assertEqual(snapshot.read_bytes(), b"binary patch\n")
                manifest = json.loads(snapshot.with_name("manifest.json").read_text(encoding="utf-8"))
                self.assertEqual((manifest["base"], manifest["upstream"]), ("base", "upstream"))

    def test_dirty_hrx_check_only_does_not_snapshot_or_pull(self):
        response = Mock()
        response.json.return_value = {"sha": "upstream"}
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(updater.requests, "get", return_value=response),
            patch.object(updater.subprocess, "run") as run,
            patch.object(updater, "snapshot_source_patches") as snapshot,
        ):
            run.side_effect = [Mock(stdout="base\n"), Mock(stdout=" M queue.cpp\n")]
            self.assertEqual(updater.process_source(cfg.hrx_tools()[0], Path(folder), True), "base")
            snapshot.assert_not_called()
            self.assertEqual(run.call_count, 2)

    def test_committed_hrx_patches_require_merge_without_attempting_pull(self):
        response = Mock()
        response.json.return_value = {"sha": "upstream"}
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(updater.requests, "get", return_value=response),
            patch.object(updater.subprocess, "run") as run,
            patch.object(updater.subprocess, "check_output", return_value="local\n"),
        ):
            run.side_effect = [Mock(stdout="local\n"), Mock(stdout=""), Mock(returncode=1), Mock(stdout="2\n")]
            self.assertEqual(updater.process_source(cfg.hrx_tools()[1], Path(folder), False), "local")
            self.assertFalse(any("pull" in call.args[0] for call in run.call_args_list))

    def test_lemonade_summary_reports_release_rocm_without_downloading(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "llamacpp/rocm/lemonade")
        for body, expected in [("**ROCm Version**: 10.2.0a20261007", "10.2.0a20261007"), (None, "UNKNOWN")]:
            with (
                patch.object(
                    updater,
                    "get_release",
                    return_value=({"tag_name": "b1341", "published_at": "new", "body": body}, {"name": "rocm.zip"}),
                ),
                patch.object(updater, "update_tool") as update,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertTrue(updater.process_tool(tool, Path("unused"), check_only=True))
                self.assertIn(f"Latest ROCm: {expected}", output.getvalue())
                update.assert_not_called()

    def test_installed_desktop_version_reads_the_packaged_manifest(self):
        tool = cfg.ToolSpec("coding_agents/demo", "Demo.exe", cfg.ReleaseType.DESKTOP)
        with CasePaths(__file__).temporary_directory() as folder:
            dest = Path(folder)
            (dest / "resources" / "app").mkdir(parents=True)
            (dest / "resources" / "app" / "package.json").write_text('{"version":"0.1.60"}', encoding="utf-8")
            self.assertEqual(other_updates.installed_desktop_version(tool, dest), "0.1.60")
            (dest / "resources" / "app" / "package.json").unlink()
            self.assertIsNone(other_updates.installed_desktop_version(tool, dest))

    def test_catalog_covers_installed_frameworks(self):
        if not project_cfg.FRAMEWORKS_DIR.is_dir():
            self.skipTest("frameworks are not installed in this checkout")
        covered = {
            project_cfg.framework_install_dir(tool.name).relative_to(project_cfg.FRAMEWORKS_DIR).parts[0]
            for tool in cfg.TOOLS
        }
        installed = {path.name for path in project_cfg.FRAMEWORKS_DIR.iterdir() if path.is_dir()}
        self.assertFalse(installed - covered)
        self.assertEqual(
            {tool.name for tool in cfg.TOOLS if not tool.in_use},
            {
                "lemonade_server",
                "localai",
                "text-generation-webui",
                "avalon",
                "tts/sherpa-onnx",
                "tts/piper",
                "audiocpp/additions/rocm/7.1-old",
                "audiocpp/additions/rocm/therock-10.2-hip-7.17-gfx1101",
                "asr/whispercpp/vulkan",
                "asr/parakeetcpp/cpu-stream",
                "llamacpp/rocm/stock",
                "llamacpp/rdna",
                "llamacpp/additions/llama-cpp-rdna-boosts",
                "llamacpp/additions/hrx/llama.cpp",
                "llamacpp/additions/hrx/hrx-system",
                "llamacpp/additions/hrx/rocm-systems",
            },
        )

    def test_unused_tools_do_not_query_or_run(self):
        with patch.object(updater.requests, "get") as get, patch.object(updater.subprocess, "run") as run:
            for tool in cfg.TOOLS:
                if not tool.in_use:
                    updater.process_tool(tool, Path("unused"), check_only=False)
            get.assert_not_called()
            run.assert_not_called()

    def test_unavailable_source_preserves_installation_and_reports_failure(self):
        tool = cfg.ToolSpec("benchmarks/missing-source", "", cfg.ReleaseType.SOURCE, repo="example/missing-source")
        with (
            patch.object(updater.requests, "get", return_value=http_response(status=404)),
            patch.object(updater.subprocess, "run") as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertFalse(updater.process_tool(tool, Path("unused"), check_only=False))
            self.assertIn("Upstream unavailable: example/missing-source", output.getvalue())
            self.assertIn("local installation is preserved", output.getvalue())
            run.assert_not_called()

    def test_running_installation_is_stopped_before_replacement(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            with (
                patch.object(project_cfg, "FRAMEWORKS_DIR", root),
                patch.object(updater, "stop_installation_processes") as stop,
                patch.object(updater.shutil, "copytree"),
            ):
                updater.replace_installation(root / "staged", root / "tool")
                stop.assert_called_once_with(root / "tool")

    def test_rdna_build_and_patches_share_the_skipped_group(self):
        self.assertEqual(
            {tool.name for tool in cfg.rdna_tools()}, {"llamacpp/rdna", "llamacpp/additions/llama-cpp-rdna-boosts"}
        )
        self.assertTrue(all(not tool.in_use for tool in cfg.rdna_tools()))

    def test_benchmark_catalog_is_grouped_under_frameworks_benchmarks(self):
        tools = cfg.benchmark_tools()
        self.assertEqual(
            {tool.name for tool in tools},
            {"benchmarks/aider-polyglot", "benchmarks/specspeed", "benchmarks/speed-bench", "benchmarks/club-rdna16"},
        )
        self.assertEqual({tool.name for tool in tools if not tool.in_use}, set())

    def test_specspeed_update_preserves_english_code_scope(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "specspeed.py"
            path.write_text(
                'PROMPTS = [("code", "Python"), ("prose_zh", "Chinese"), ("prose_en", "English")]\n', encoding="utf-8"
            )
            other_updates.restrict_specspeed(path)
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("prose_zh", source)
            self.assertIn("prose_en", source)
            self.assertIn("code", source)

    def test_snapshot_check_only_does_not_download_or_replace(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "benchmarks/specspeed")
        response = Mock()
        response.json.return_value = {"sha": "new"}
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(updater.requests, "get", return_value=response) as get,
            patch.object(updater, "replace_installation") as replace,
        ):
            updater.process_snapshot(tool, Path(folder) / "missing", Path(folder), check_only=True)
            self.assertEqual(get.call_count, 1)
            replace.assert_not_called()

    def test_nested_sccache_release_preserves_sibling_cache(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            destination = root / "sccache/bin"
            destination.mkdir(parents=True)
            cache = root / "sccache/cache"
            cache.mkdir()
            (cache / "data").write_bytes(b"keep")
            content = io.BytesIO()
            with zipfile.ZipFile(content, "w") as archive:
                archive.writestr("sccache-version/sccache.exe", b"new")
            response = http_response(content.getvalue())
            scratch = root / "scratch"
            scratch.mkdir()
            with (
                patch.object(project_cfg, "FRAMEWORKS_DIR", root),
                patch.object(updater.requests, "get", return_value=response),
            ):
                updater.update_tool(
                    {"name": "sccache.zip", "browser_download_url": "https://example.test/sccache.zip"},
                    destination,
                    scratch,
                    "sccache.exe",
                )
            self.assertEqual((destination / "sccache.exe").read_bytes(), b"new")
            self.assertEqual((cache / "data").read_bytes(), b"keep")

    def test_merge_and_build_only_sources_are_reported_separately(self):
        # - rdna carries local patches, so upstream changes need a merge; Avalon is a
        #   clean checkout that only has to be recompiled after a fast-forward.
        self.assertEqual([tool.name for tool in cfg.TOOLS if tool.manual_merge], ["llamacpp/rdna"])
        self.assertEqual([tool.name for tool in cfg.TOOLS if tool.rebuild_required], ["avalon"])
        audio = next(tool for tool in cfg.TOOLS if tool.name == "audiocpp/vulkan")
        self.assertEqual(audio.release_type, cfg.ReleaseType.DATE)
        self.assertEqual(audio.install_subdir, "")
        self.assertEqual(project_cfg.AUDIOCPP_VULKAN_BIN_DIR, project_cfg.AUDIOCPP_VULKAN_DIR)

    def test_kobold_patch_version_is_preserved(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "koboldcpp")
        result = Mock(stdout="1.122.1\n", stderr="")
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(updater.subprocess, "run", return_value=result),
        ):
            self.assertEqual(updater.get_local_version(tool, Path("koboldcpp-nocuda.exe")), "v1.122.1")

    def test_npm_check_only_reads_framework_manifest(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            manifest = root / "node_modules" / "@earendil-works" / "pi-coding-agent" / "package.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"version": "0.84.1"}), encoding="utf-8")
            response = Mock()
            response.json.return_value = {"version": "1.0.0"}
            with (
                patch.object(updater.requests, "get", return_value=response),
                patch.object(updater.subprocess, "run") as run,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                other_updates.process_npm(self.pi_tool, root, check_only=True)
                run.assert_not_called()
                self.assertIn("UPDATE AVAILABLE", output.getvalue())
                self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["version"], "0.84.1")

    def test_npm_update_uses_framework_prefix_and_exact_version(self):
        response = Mock()
        response.json.return_value = {"version": "1.0.0"}
        with (
            patch.object(updater.requests, "get", return_value=response),
            patch.object(updater.shutil, "which", return_value="C:/node/npm.cmd"),
            patch.object(updater.subprocess, "run") as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            destination = CasePaths(__file__).new_run().temp / "npm-test-prefix"
            other_updates.process_npm(self.pi_tool, destination, check_only=False)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--prefix") + 1], str(destination))
            self.assertIn("--save-exact", command)
            self.assertEqual(command[-1], "@earendil-works/pi-coding-agent@1.0.0")
            self.assertIn("UPDATING @earendil-works/pi-coding-agent (NOT INSTALLED -> 1.0.0)", output.getvalue())
            self.assertIn("UPDATED @earendil-works/pi-coding-agent -> 1.0.0", output.getvalue())

    def test_main_check_only_does_not_install(self):
        with (
            patch.object(sys, "argv", ["update_frameworks", "--check-only", "--skip-comfyui"]),
            patch.object(updater, "process_tool") as process,
        ):
            entry.main()
            self.assertEqual(process.call_count, sum(tool.in_use for tool in cfg.TOOLS) - 1)
            self.assertTrue(all(call.args[2] for call in process.call_args_list))

    def test_main_reports_failed_update_and_still_checks_remaining_tools(self):
        with (
            patch.object(sys, "argv", ["update_frameworks", "--check-only"]),
            patch.object(
                updater, "process_tool", side_effect=[False, *([True] * (sum(tool.in_use for tool in cfg.TOOLS) - 1))]
            ) as process,
        ):
            self.assertEqual(entry.main(), 1)
            self.assertEqual(process.call_count, sum(tool.in_use for tool in cfg.TOOLS))

    def test_binary_update_preserves_old_installation_in_trash(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            frameworks = root / "frameworks"
            destination = frameworks / "tool"
            destination.mkdir(parents=True)
            (destination / "tool.exe").write_bytes(b"old installation")
            scratch = root / "scratch"
            scratch.mkdir()
            response = http_response(b"new installation")
            asset: updater.Asset = {"name": "tool.exe", "browser_download_url": "https://example.test/tool.exe"}
            with (
                patch.object(project_cfg, "FRAMEWORKS_DIR", frameworks),
                patch.object(project_cfg, "BASE_DIR", root),
                patch.object(updater.requests, "get", return_value=response),
            ):
                updater.update_tool(asset, destination, scratch, "tool.exe")
            self.assertEqual((destination / "tool.exe").read_bytes(), b"new installation")
            backups = list((root / "trash").glob("*/tool.exe"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"old installation")

    def test_release_archive_build_folders_are_flattened_to_install_root(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            scratch = root / "scratch"
            scratch.mkdir()
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as output:
                prefix = "build/windows-vulkan-release/bin/"
                output.writestr(prefix + "audiocpp_server.exe", b"server")
                output.writestr(prefix + "ggml-vulkan.dll", b"backend")
                output.writestr(prefix + "model_specs/ming3_tts.json", b"{}")
            response = http_response(archive.getvalue())
            target = root / "frameworks/audiocpp/vulkan"
            with (
                patch.object(project_cfg, "FRAMEWORKS_DIR", root / "frameworks"),
                patch.object(updater.requests, "get", return_value=response),
            ):
                updater.update_tool(
                    {"name": "audio.zip", "browser_download_url": "https://example.test/audio.zip"},
                    target,
                    scratch,
                    "audiocpp_server.exe",
                )
            self.assertTrue((target / "audiocpp_server.exe").is_file())
            self.assertTrue((target / "ggml-vulkan.dll").is_file())
            self.assertTrue((target / "model_specs/ming3_tts.json").is_file())
            self.assertFalse((target / "build").exists())

    def test_handy_post_install_runs_without_a_download_only_while_the_app_is_missing(self):
        from scripts.download.frameworks.asr import handy

        tool = next(tool for tool in cfg.TOOLS if tool.name == "asr/handy/installer")
        summary = updater.UpdateSummary()
        with (
            patch.object(updater, "process_tool", return_value=True) as process,
            patch.object(handy, "install_app") as install,
            patch.object(handy, "app_missing", return_value=True),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(updater.apply_updates([tool], Path("unused"), summary, io.StringIO()))
        process.assert_called_once()
        self.assertFalse(process.call_args.args[2])
        install.assert_called_once_with()

    def test_no_update_run_stays_silent_when_the_handy_app_already_exists(self):
        from scripts.download.frameworks.asr import handy

        tool = next(tool for tool in cfg.TOOLS if tool.name == "asr/handy/installer")
        summary = updater.UpdateSummary()
        with (
            patch.object(updater, "process_tool") as process,
            patch.object(handy, "install_app") as install,
            patch.object(handy, "app_missing", return_value=False),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertFalse(updater.apply_updates([tool], Path("unused"), summary, io.StringIO()))
        process.assert_not_called()
        install.assert_not_called()
        self.assertEqual(output.getvalue(), "")

    def test_handy_install_preserves_an_existing_app_without_running_setup(self):
        from scripts.download.frameworks.asr import handy

        with CasePaths(__file__).temporary_directory() as folder:
            app = Path(folder) / "app"
            app.mkdir()
            (app / "handy.exe").write_text("app")
            with (
                patch.object(project_cfg, "HANDY_APP_DIR", app),
                patch.object(handy, "prepare_model") as prepare,
                patch.object(handy.subprocess, "run") as run,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                handy.install_app()
            run.assert_not_called()
            prepare.assert_called_once()


if __name__ == "__main__":
    with timed("shared/framework_updates"):
        unittest.main()
