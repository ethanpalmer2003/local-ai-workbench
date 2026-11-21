import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config.shared import hardware
from scripts.launchers.runtime import gpu_selection

LISTING = (
    "Available devices:\n"
    "  Vulkan0: AMD Radeon RX 7800 XT (16368 MiB, 14616 MiB free)\n"
    "  Vulkan1: AMD Radeon(TM) Graphics (16171 MiB, 15362 MiB free)\n"
)


def _listing(text: str = LISTING, code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["llama-server.exe", "--list-devices"], returncode=code, stdout=text, stderr=""
    )


class GpuSelectionTests(unittest.TestCase):
    def test_the_discrete_adapter_is_the_listed_device(self):
        with patch.object(gpu_selection.subprocess, "run", return_value=_listing()):
            self.assertEqual(gpu_selection.discrete_vulkan_device(Path("llama-server.exe")), "Vulkan0")

    def test_a_missing_discrete_adapter_is_an_error(self):
        listing = "Available devices:\n  Vulkan0: AMD Radeon(TM) Graphics (16171 MiB, 15362 MiB free)\n"
        with (
            patch.object(gpu_selection.subprocess, "run", return_value=_listing(listing)),
            self.assertRaises(RuntimeError),
        ):
            gpu_selection.discrete_vulkan_device(Path("llama-server.exe"))

    def test_a_failed_listing_is_an_error(self):
        with (
            patch.object(gpu_selection.subprocess, "run", return_value=_listing("", code=1)),
            self.assertRaises(RuntimeError),
        ):
            gpu_selection.discrete_vulkan_device(Path("llama-server.exe"))

    def test_the_tracked_names_come_from_one_file(self):
        self.assertEqual(hardware.discrete_gpu(), hardware.read()["discrete_gpu"])
        self.assertIn("integrated_gpu", hardware.read())
