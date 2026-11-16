"""ROCm inventory: detection, kind, version preference and reference matching."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.tools import rocm_inventory


def _tree(folder: str, name: str = "install", dlls=("amdhip64_7.dll",)) -> Path:
    root = Path(folder) / name
    (root / "bin").mkdir(parents=True)
    for dll in dlls:
        (root / "bin" / dll).write_bytes(b"x")
    return root


class RocmInventoryTests(unittest.TestCase):
    def test_a_tree_with_a_hip_library_is_a_rocm_install(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = _tree(folder)
            empty = Path(folder) / "empty"
            empty.mkdir()
            self.assertTrue(rocm_inventory.is_rocm(root))
            self.assertFalse(rocm_inventory.is_rocm(empty))

    def test_kind_separates_sdk_builds_from_bundled_and_plain_runtimes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sdk = _tree(folder, "sdk")
            (sdk / "bin" / "clang++.exe").write_bytes(b"x")
            build = _tree(folder, "build")
            (build / "BUILD.json").write_text('{"rocm_version": "10.2"}', encoding="utf-8")
            plain = _tree(folder, "plain")
            self.assertEqual(rocm_inventory.kind_of(sdk), "sdk install")
            self.assertEqual(rocm_inventory.kind_of(build), "bundled build")
            self.assertEqual(rocm_inventory.kind_of(plain), "runtime libs")

    def test_version_prefers_the_markers_then_the_build_file_then_the_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            marked = _tree(folder, "marked")
            (marked / ".hipVersion").write_text("7.2.1\n", encoding="utf-8")
            built = _tree(folder, "built")
            (built / "BUILD.json").write_text('{"rocm_version": "10.2.0a"}', encoding="utf-8")
            named = _tree(folder, "therock-10.2a")
            self.assertEqual(rocm_inventory.version_of(marked), "7.2.1")
            self.assertEqual(rocm_inventory.version_of(built), "10.2.0a")
            self.assertEqual(rocm_inventory.version_of(named), "therock-10.2a")

    def test_shell_style_version_markers_become_one_version(self) -> None:
        text = "# Auto-generated\nHIP_VERSION_MAJOR=7\nHIP_VERSION_MINOR=17\nHIP_VERSION_PATCH=26385\n"
        self.assertEqual(rocm_inventory._marker_version(text), "7.17.26385")

    def test_inventory_reports_size_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = _tree(folder)
            rows = rocm_inventory.inventory([root], known={root / "bin": "consumer"}, sizes=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].files, 1)
        self.assertEqual(rows[0].size_bytes, 1)
        self.assertEqual(rows[0].used_by, "consumer")

    def test_size_text_formats_bytes_and_unknown(self) -> None:
        self.assertEqual(rocm_inventory._human(0), "-")
        self.assertEqual(rocm_inventory._human(512), "512 B")
        self.assertEqual(rocm_inventory._human(3 * 1024**3), "3.0 GiB")

    def test_json_rows_carry_every_field(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = _tree(folder)
            rows = rocm_inventory.inventory([root], known={}, sizes=False)
        payload = json.loads(json.dumps([row.__dict__ for row in rows]))
        self.assertEqual(payload[0]["kind"], "runtime libs")
        self.assertEqual(payload[0]["used_by"], "")


if __name__ == "__main__":
    unittest.main()
