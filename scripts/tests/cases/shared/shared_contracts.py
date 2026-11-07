"""Shared download, startup, and memory contracts; no downloads or model launches."""

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.download.input import get_tts_voices, split_from_csv
from scripts.download.models import cli_download
from scripts.launchers import launch_util, proxy_util
from scripts.launchers.llamacpp import llamacpp, llamacpp_dsh, llamacpp_proxy
from scripts.launchers.runtime import gpu_memory
from scripts.review.inventory_code import inspect_source
from scripts.tests.cases.koboldcpp.kobold_vram_estimate import kv_cache_mib
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.process_fixtures import running_process
from scripts.tests.shared.timing import timed


class SharedContracts(unittest.TestCase):
    def test_structure_audit_counts_elif_and_nested_functions_correctly(self):
        source = '''def example(value):
    """Not code.
    Still not code.
    """
    # Not code either.
    if value:
        return 1
    elif not value:
        return 2
    def nested():
        for item in value:
            if item:
                return item
    return nested()
'''
        outer, inner = inspect_source(source, "example.py")
        self.assertEqual((outer.code_lines, outer.depth), (7, 1))
        self.assertEqual((inner.code_lines, inner.depth), (4, 2))

    def test_structure_audit_measures_nested_control_flow(self):
        source = "def deep():\n    for a in []:\n        if a:\n            while a:\n                with a:\n                    pass\n"
        self.assertEqual(inspect_source(source, "deep.py")[0].depth, 4)

    def test_structure_audit_measures_factory_methods_separately(self):
        source = "def factory():\n    class Handler:\n        def handle(self):\n            for item in []:\n                pass\n    return Handler\n"
        factory, method = inspect_source(source, "factory.py")
        self.assertEqual((factory.code_lines, factory.depth), (3, 0))
        self.assertEqual((method.code_lines, method.depth), (3, 1))

    def test_xlsx_transcripts_preserve_existing_entries_across_sheets(self):
        first, second = Mock(), Mock()
        first.iter_rows.return_value = [("first", "new first"), ("second", "new second")]
        second.iter_rows.return_value = [(None, "third", "new third"), ("third", "do not overwrite")]
        workbook = Mock(worksheets=[first, second])
        mapping = {"first": "existing"}
        files = [Path(name + ".wav") for name in ("first", "second", "third")]
        with patch("openpyxl.load_workbook", return_value=workbook):
            self.assertEqual(get_tts_voices.import_xlsx_transcripts(Path("transcripts.xlsx"), files, mapping), 2)
        self.assertEqual(mapping, {"first": "existing", "second": "new second", "third": "new third"})
        workbook.close.assert_called_once()

    def test_url_preserves_encoded_revision_and_path_without_query(self):
        target = cli_download.parse_url(
            "https://huggingface.co/owner/repo/resolve/release%2Fv1/folder/my%20model.gguf?download=true"
        )
        self.assertEqual(target, cli_download.HubFile("owner/repo", "folder/my model.gguf", "release/v1"))
        with self.assertRaises(ValueError):
            cli_download.parse_url("https://huggingface.co.example/owner/repo/blob/main/model.gguf")

    def test_cli_file_download_forwards_revision(self):
        cases = (
            (["--repo", "owner/repo", "--file", "model.gguf", "--revision", "v1"], "v1"),
            (["--url", "https://huggingface.co/owner/repo/blob/v2/model.gguf"], "v2"),
            (["--url", "https://huggingface.co/owner/repo/blob/v2/model.gguf", "--revision", "v3"], "v3"),
        )
        for args, revision in cases:
            with (
                patch.object(sys, "argv", ["download", *args]),
                patch.object(cli_download, "download_file") as download,
            ):
                cli_download.main()
                self.assertEqual(download.call_args.kwargs["revision"], revision)

    def test_import_does_not_create_download_directory(self):
        with patch("pathlib.Path.mkdir") as mkdir:
            importlib.import_module("scripts.download.models.download_catalog")
            mkdir.assert_not_called()

    def test_sdk_receives_file_revision(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(cli_download.project_cfg, "HF_MODELS_DIR", Path(folder)),
            patch("huggingface_hub.hf_hub_download") as download,
        ):
            cli_download.download_file("owner/repo", "model.gguf", revision="v1")
            self.assertEqual(download.call_args.kwargs["revision"], "v1")

    def test_failed_model_download_propagates_error(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch("huggingface_hub.hf_hub_download", side_effect=RuntimeError("download failed")),
            self.assertRaisesRegex(RuntimeError, "download failed"),
        ):
            cli_download.download_file("owner/repo", "model.gguf", local_dir=Path(folder))

    def test_snapshot_download_uses_destination(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch("huggingface_hub.snapshot_download") as download,
        ):
            cli_download.download_snapshot("owner/repo", revision="v2", local_dir=Path(folder))
            self.assertEqual(download.call_args.kwargs["local_dir"], str(Path(folder)))
            self.assertEqual(download.call_args.kwargs["revision"], "v2")

    def test_zero_memory_is_known_not_missing(self):
        self.assertEqual(gpu_memory._parse_memory_mb("0 MB"), 0.0)
        self.assertIsNone(gpu_memory._parse_memory_mb("0 unknown"))

    def test_kv_estimate_accounts_for_all_kv_heads(self):
        metadata = {
            "general.architecture": "llama",
            "llama.block_count": 2,
            "llama.attention.head_count_kv": 4,
            "llama.attention.key_length": 128,
            "llama.attention.value_length": 128,
        }
        self.assertEqual(kv_cache_mib(metadata, 1024, 2), 4.0)

    def test_dsh_custom_port_is_forwarded_to_direct_launch(self):
        with (
            patch.object(sys, "argv", ["dsh", "--dry-run", "--port", "9988"]),
            patch.object(llamacpp_dsh, "backend_running", return_value=False),
            patch.object(llamacpp_dsh.cfg.LLAMACPP_SERVICE, "mode", llamacpp_dsh.cfg.ServiceMode.SERVER),
            patch.object(
                llamacpp_dsh.llamacpp, "config_from_args", wraps=llamacpp_dsh.llamacpp.config_from_args
            ) as config,
        ):
            self.assertEqual(llamacpp_dsh.main(), 0)
            self.assertEqual(config.call_args.kwargs["port"], 9988)

    def test_proxy_start_forwards_custom_port(self):
        with (
            patch.object(llamacpp_proxy.llamacpp, "config_argv", return_value=[]),
            patch.object(llamacpp_proxy, "launch_module") as launch,
        ):
            llamacpp_proxy.start(Mock(), port=9988)
            self.assertEqual(launch.call_args.kwargs["extra_args"], ["--port", "9988"])

    def test_failed_llama_readiness_stops_new_process(self):
        process = running_process(pid=1234)
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(llamacpp.project_cfg, "LOGS_DIR", Path(folder)),
            patch.object(llamacpp, "launch_process", return_value=process),
            patch.object(llamacpp, "LlamaMonitor") as monitor,
            patch.object(llamacpp, "kill_process_tree") as kill,
        ):
            monitor.return_value.log_file = Path(folder) / "server.log"
            monitor.return_value.wait_ready.return_value = False
            with self.assertRaises(TimeoutError):
                llamacpp.launch()
            kill.assert_called_once_with(1234)
            process.wait.assert_called_once_with(timeout=10)

    def test_silence_cache_is_not_reused_for_another_source(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            first, second, cache = root / "first.mp3", root / "second.mp3", root / "cache.json"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            with patch.object(
                split_from_csv.subprocess, "run", return_value=Mock(stderr="silence_start: 0\nsilence_end: 1")
            ) as scan:
                split_from_csv.detect_silences(first, -30, 0.3, cache)
                split_from_csv.detect_silences(first, -30, 0.3, cache)
                self.assertEqual(scan.call_count, 1)
                split_from_csv.detect_silences(second, -30, 0.3, cache)
                self.assertEqual(scan.call_count, 2)

    @unittest.skipUnless(sys.platform == "win32", "Windows terminal quoting")
    def test_terminal_arguments_are_literal_powershell_strings(self):
        with patch.object(launch_util.subprocess, "Popen", return_value=running_process(pid=42)) as spawn:
            launch_util.launch_process(
                ["backend.exe", "a'b $value `text"],
                "test",
                mode=launch_util.ConsoleTerminalLaunchMode.SPLIT_INDEPENDENT,
                log_file="C:/AI/log $value.txt",
                report_vram=False,
            )
        self.assertEqual(
            spawn.call_args.args[0][-1],
            "$Host.UI.RawUI.WindowTitle = 'test'; & 'backend.exe' 'a''b $value `text' 2>&1 | Tee-Object -FilePath 'C:/AI/log $value.txt'",
        )

    def test_proxy_closes_listener_when_serving_fails(self):
        with (
            patch.object(proxy_util, "ExclusiveThreadingHTTPServer") as server,
            patch.object(proxy_util, "print_ready"),
        ):
            server.return_value.__enter__.return_value.serve_forever.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                proxy_util.serve_proxy(llamacpp_proxy.Handler, "127.0.0.1", 9988, "unused", "test")
            server.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    with timed("shared/shared_contracts"):
        unittest.main()
