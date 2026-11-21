"""AudioCpp support files and the release assets that now carry them."""

import contextlib
import io
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.download.frameworks import framework_catalog as cfg
from scripts.download.frameworks import update_shared as updater
from scripts.download.frameworks.audiocpp import setup_mecab
from scripts.download.frameworks.audiocpp import updates as audiocpp_updates
from scripts.tests.shared.paths import CasePaths


class FrameworkUpdateAdditions(unittest.TestCase):
    def test_espeak_tracks_its_release_and_unpacks_only_what_audiocpp_loads(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "audiocpp/additions/espeak-ng")
        self.assertEqual(tool.release_type, cfg.ReleaseType.DATE)
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            destination = root / "install"
            installed = destination / "eSpeak NG"
            installed.mkdir(parents=True)
            (installed / "libespeak-ng.dll").write_bytes(b"old")
            package = root / "espeak-ng.msi"
            package.write_bytes(b"msi")

            def extract(command, **_kwargs):
                self.assertEqual(command[1], "/a")
                target = Path(command[-1].split("=", 1)[1]) / "eSpeak NG"
                target.mkdir(parents=True)
                (target / "libespeak-ng.dll").write_bytes(b"new")
                return subprocess.CompletedProcess(command, 0, "", "")

            asset: updater.Asset = {
                "name": "espeak-ng.msi",
                "browser_download_url": "https://example.test/espeak-ng.msi",
            }
            (root / "work").mkdir()
            with (
                patch.object(audiocpp_updates.shared, "download_asset", return_value=package),
                patch.object(
                    audiocpp_updates.shared, "archive_path", side_effect=lambda path, _root: shutil.rmtree(path)
                ) as archive,
                patch.object(audiocpp_updates.subprocess, "run", side_effect=extract),
            ):
                audiocpp_updates.extract_espeak(asset, destination, root / "work", tool.exe)
            archive.assert_called_once()
            self.assertEqual((installed / "libespeak-ng.dll").read_bytes(), b"new")

    def test_a_package_without_the_native_library_fails_instead_of_installing(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "audiocpp/additions/espeak-ng")
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            package = root / "espeak-ng.msi"
            package.write_bytes(b"msi")
            asset: updater.Asset = {
                "name": "espeak-ng.msi",
                "browser_download_url": "https://example.test/espeak-ng.msi",
            }
            (root / "work").mkdir()
            with (
                patch.object(audiocpp_updates.shared, "download_asset", return_value=package),
                patch.object(
                    audiocpp_updates.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")
                ),
                self.assertRaises(updater.UpdateError),
            ):
                audiocpp_updates.extract_espeak(asset, root / "install", root / "work", tool.exe)

    def test_mecab_follows_the_wheel_version_and_installs_only_when_applying(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "audiocpp/additions/mecab")
        self.assertEqual(tool.release_type, cfg.ReleaseType.PYPI)
        self.assertEqual(tool.package, "mecab-python3")
        summary = updater.UpdateSummary()
        with (
            patch.object(setup_mecab, "latest_wheel", return_value=("1.0.13", "https://example.test/mecab.whl")),
            patch.object(setup_mecab, "installed_version", return_value="1.0.12"),
            patch.object(setup_mecab, "install") as install,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            audiocpp_updates.process_pypi(tool, Path("unused"), Path("unused"), True, summary)
        install.assert_not_called()
        self.assertTrue(summary.available[0].startswith(tool.name))
        with (
            patch.object(setup_mecab, "latest_wheel", return_value=("1.0.13", "https://example.test/mecab.whl")),
            patch.object(setup_mecab, "installed_version", return_value="1.0.12"),
            patch.object(setup_mecab, "install") as install,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            audiocpp_updates.process_pypi(tool, Path("unused"), Path("unused"), False, summary)
        install.assert_called_once()

    def test_a_current_wheel_reports_no_update(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "audiocpp/additions/mecab")
        summary = updater.UpdateSummary()
        with (
            patch.object(setup_mecab, "latest_wheel", return_value=("1.0.13", "https://example.test/mecab.whl")),
            patch.object(setup_mecab, "installed_version", return_value="1.0.13"),
            patch.object(setup_mecab, "install") as install,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            audiocpp_updates.process_pypi(tool, Path("unused"), Path("unused"), False, summary)
        install.assert_not_called()
        self.assertTrue(summary.current[0].startswith(tool.name))

    def test_parakeet_streaming_library_comes_from_the_official_asset(self):
        tool = next(tool for tool in cfg.TOOLS if tool.name == "asr/parakeetcpp/cpu-stream")
        self.assertEqual(tool.release_type, cfg.ReleaseType.DATE)
        self.assertTrue(tool.in_use)
        self.assertNotIn(tool.name, {parked.name for parked in cfg.TOOLS if parked.rebuild_required})
