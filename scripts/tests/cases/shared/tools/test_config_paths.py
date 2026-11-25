"""Config text resolves the repository root, and a config that is not an object fails where it is named."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from scripts.benchmarks.llamacpp.hrx import hrx_tensor_probe as probe
from scripts.config import paths
from scripts.config import project_config as project_cfg
from scripts.download.frameworks import native_build
from scripts.download.frameworks.llamacpp import rdna_build
from scripts.tools import rocm_inventory


class ConfigPathTests(unittest.TestCase):
    def test_a_placeholder_resolves_to_the_repository_root(self):
        text = paths.resolve_text('{"path": "{AI_ROOT}/data"}')
        self.assertEqual(text, f'{{"path": "{project_cfg.BASE_DIR.as_posix()}/data"}}')

    def test_a_json_object_loads_with_its_placeholder_resolved(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "server.json"
            path.write_text('{"root": "{AI_ROOT}"}', encoding="utf-8")
            self.assertEqual(paths.load_json(path), {"root": project_cfg.BASE_DIR.as_posix()})

    def test_a_json_array_is_refused_where_the_file_is_named(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "server.json"
            path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must hold a JSON object"):
                paths.load_json(path)


class HostToolsTests(unittest.TestCase):
    def test_bindings_are_absolute_and_derived_from_their_roots(self):
        self.assertTrue(project_cfg.AMD_ROCM_PROGRAM_ROOT.is_absolute())
        self.assertEqual(project_cfg.VSWHERE_EXE.name, "vswhere.exe")
        self.assertEqual(
            project_cfg.RC_EXE,
            project_cfg.WINDOWS_KITS_ROOT / "bin" / project_cfg.WINDOWS_SDK_VERSION / "x64" / "rc.exe",
        )
        self.assertEqual(project_cfg.MSVC_ROOT.name, project_cfg.MSVC_VERSION)

    def test_consumers_read_the_bindings_instead_of_their_own_literals(self):
        self.assertIs(rocm_inventory.AMD_ROOT, project_cfg.AMD_ROCM_PROGRAM_ROOT)
        self.assertEqual(rdna_build.BUILD_DEFAULTS.rc_compiler, str(project_cfg.RC_EXE))
        with (
            TemporaryDirectory() as folder,
            patch.object(project_cfg, "MSVC_ROOT", Path(folder) / "msvc"),
            patch.object(project_cfg, "WINDOWS_KITS_ROOT", Path(folder) / "kits"),
            patch.object(project_cfg, "WINDOWS_SDK_VERSION", "10.0.1"),
        ):
            compiler, env = probe.native_build_environment()
        self.assertEqual(compiler, Path(folder) / "msvc/bin/Hostx64/x64/cl.exe")
        self.assertIn(str(Path(folder) / "kits/Include/10.0.1/ucrt"), env["INCLUDE"])

    def test_the_vswhere_call_uses_the_configured_executable(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(project_cfg, "VSWHERE_EXE", Path(folder) / "vswhere.exe"),
            patch.object(project_cfg, "component", return_value=SimpleNamespace(generated_dir=Path(folder))),
            patch.object(native_build.subprocess, "check_output") as check,
        ):
            (Path(folder) / "vs/VC/Auxiliary/Build").mkdir(parents=True)
            (Path(folder) / "vs/VC/Auxiliary/Build/vcvarsall.bat").write_text("@echo off\n", encoding="utf-8")
            check.side_effect = [str(Path(folder) / "vs"), "A=1\n"]
            env = native_build.visual_studio_environment()
            self.assertEqual(check.call_args_list[0].args[0][0], str(Path(folder) / "vswhere.exe"))
            self.assertEqual(env, {"A": "1"})
            self.assertTrue((Path(folder) / "build-environment.cmd").is_file())


if __name__ == "__main__":
    unittest.main()
