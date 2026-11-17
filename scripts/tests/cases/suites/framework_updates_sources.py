"""Framework source, git and desktop update behavior, split from the update suite."""

import contextlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import build_frameworks as build_all
from scripts.download.frameworks import framework_catalog as cfg
from scripts.download.frameworks import update_frameworks as entry
from scripts.download.frameworks import update_shared as updater
from scripts.download.frameworks.shared import other_updates
from scripts.tests.shared.http_fixtures import http_response
from scripts.tests.shared.paths import CasePaths


class FrameworkUpdateSources(unittest.TestCase):
    pi_tool = next(tool for tool in cfg.TOOLS if tool.package == "@earendil-works/pi-coding-agent")
    # - a manifest the desktop and npm cases feed to the updater
    feed_yaml = (
        "version: 0.2.2-rc.1\n"
        "path: https://example.test/deepseek-harness-0.2.2-rc.1-win-x64.exe\n"
        "sha512: abc\n"
        "files:\n"
        "  - url: https://example.test/deepseek-harness-0.2.2-rc.1-win-x64.exe\n"
        "    sha512: abc\n"
        "    size: 293425336\n"
    )

    def setUp(self):
        # - Toolchain checks run real executables; the model-free suite forbids starting processes.
        check = patch.object(entry.toolchains, "check", return_value=[])
        check.start()
        self.addCleanup(check.stop)
        apply_toolchains = patch.object(entry.toolchains, "apply", return_value=False)
        apply_toolchains.start()
        self.addCleanup(apply_toolchains.stop)

    def _comfyui_tool(self):
        return next(tool for tool in cfg.TOOLS if tool.name == "comfyui/rocm")

    def _desktop_tool(self):
        return next(tool for tool in cfg.TOOLS if tool.name == "coding_agents/deepseek")

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

    def test_a_missing_source_install_is_offered_before_any_build(self):
        tool: Any = SimpleNamespace(name="fixture/build", build_command=["cmake", "--build", "."])
        with (
            patch.object(entry.build_frameworks, "build_targets", return_value=[tool]),
            patch.object(entry.project_cfg, "framework_install_dir", return_value=Path("absent")),
        ):
            self.assertEqual(entry.missing_builds([tool]), [tool])

    def test_declining_the_offer_builds_nothing(self):
        tool: Any = SimpleNamespace(name="fixture/build", build_command=["cmake"])
        with patch("builtins.input", return_value="n"), patch.object(entry.build_frameworks, "run_builds") as run:
            self.assertEqual(entry.build_missing([tool], assume_yes=False), 0)
        run.assert_not_called()

    def test_assuming_yes_builds_without_a_prompt(self):
        tool: Any = SimpleNamespace(name="fixture/build", build_command=["cmake"])
        with (
            patch("builtins.input", side_effect=AssertionError("should not ask")),
            patch.object(entry.build_frameworks, "run_builds", return_value=0) as run,
        ):
            entry.build_missing([tool], assume_yes=True)
        run.assert_called_once_with([tool], foreground=True)
