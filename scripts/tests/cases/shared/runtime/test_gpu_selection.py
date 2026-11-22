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
SD_LISTING = (
    "ggml_vulkan: Found 2 Vulkan devices:\n"
    "ggml_vulkan: 0 = AMD Radeon(TM) Graphics (AMD proprietary driver) | uma: 1\n"
    "load_backend: loaded Vulkan backend\n"
    "Vulkan1\tAMD Radeon(TM) Graphics\n"
    "Vulkan0\tAMD Radeon RX 7800 XT\n"
    "CPU\tAMD Ryzen 5 7600 6-Core Processor\n"
)
AUDIO_LISTING = (
    "ggml_vulkan: Found 2 Vulkan devices:\n"
    'Vulkan:0 "AMD Radeon RX 7800 XT" [GPU]\n'
    'Vulkan:1 "AMD Radeon(TM) Graphics" [IGPU]\n'
    'CPU:0 "AMD Ryzen 5 7600 6-Core Processor" [CPU]\n'
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

    def test_each_engine_listing_format_yields_the_same_device(self):
        for listing, expected in (("llama", LISTING), ("sd", SD_LISTING), ("audio", AUDIO_LISTING)):
            with self.subTest(engine=listing):
                device = gpu_selection.discrete_from_listing(expected)
                self.assertEqual((device.id, device.index), ("Vulkan0", 0))
                self.assertEqual(device.name, hardware.discrete_gpu())

    def test_a_listing_keeps_the_engine_order_and_every_name(self):
        self.assertEqual(
            gpu_selection.devices(SD_LISTING),
            [
                gpu_selection.Device("Vulkan1", hardware.read()["integrated_gpu"], 1),
                gpu_selection.Device("Vulkan0", hardware.discrete_gpu(), 0),
            ],
        )

    def test_a_missing_adapter_names_what_was_listed(self):
        with self.assertRaisesRegex(RuntimeError, "available: Vulkan1"):
            gpu_selection.discrete_from_listing('Vulkan:1 "AMD Radeon(TM) Graphics" [IGPU]\n')

    def test_the_cli_reports_the_resolved_device(self):
        with patch.object(
            gpu_selection, "device_for_binary", return_value=gpu_selection.Device("Vulkan0", hardware.discrete_gpu(), 0)
        ):
            self.assertEqual(gpu_selection.main(["sd-server.exe"]), 0)

    def test_the_cli_fails_when_a_binary_cannot_find_it(self):
        with patch.object(gpu_selection, "device_for_binary", side_effect=RuntimeError("not listed")):
            self.assertEqual(gpu_selection.main(["sd-server.exe"]), 1)
