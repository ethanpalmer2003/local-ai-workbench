"""Contract checks the ComfyUI startup runs, exercised without ComfyUI's interpreter."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.config.comfyui import verify_node

TRACKED_NODE = project_cfg.CONFIG_DIR / "comfyui" / "ltx_prompt_cache.py"


def node_class(**overrides: object) -> type:
    """Stand-in with the same callable contract as the tracked node class."""

    class Node:
        RETURN_TYPES = ("CONDITIONING",)
        FUNCTION = "encode"
        CATEGORY = "conditioning/local"
        INPUTS = {
            "required": {
                "clip": ("CLIP", {"lazy": True}),
                "text": ("STRING", {"multiline": True}),
                "cache_enabled": ("BOOLEAN", {"default": True}),
            },
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

        @classmethod
        def INPUT_TYPES(cls):
            return cls.INPUTS

        @classmethod
        def IS_CHANGED(cls, **_kwargs: object) -> float:
            return float("nan")

        def check_lazy_status(self, **_kwargs: object) -> list[str]:
            return []

        def encode(self, **_kwargs: object) -> tuple[object]:
            return (None,)

    for name, value in overrides.items():
        setattr(Node, name, value)
    return Node


def node_module(node: type | None = None, display: bool = True) -> ModuleType:
    module = ModuleType("installed_node")
    module.__dict__["NODE_CLASS_MAPPINGS"] = {verify_node.NODE_CLASS: node or node_class()}
    if display:
        module.__dict__["NODE_DISPLAY_NAME_MAPPINGS"] = {verify_node.NODE_CLASS: "LTX Prompt Encode"}
    return module


class VerifyNodeTests(unittest.TestCase):
    def test_tracked_node_satisfies_the_startup_contract(self) -> None:
        self.assertEqual(verify_node.contract_issues(verify_node.load(TRACKED_NODE)), [])

    def test_missing_registration_and_display_name_are_reported(self) -> None:
        unregistered = ModuleType("unregistered")
        self.assertIn("NODE_CLASS_MAPPINGS", verify_node.contract_issues(unregistered)[0])
        self.assertTrue(verify_node.contract_issues(node_module(display=False)))

    def test_class_and_input_changes_are_reported(self) -> None:
        class_values = {"FUNCTION": "missing_method", "RETURN_TYPES": ()}
        for name, value in class_values.items():
            with self.subTest(attribute=name):
                issues = verify_node.contract_issues(node_module(node_class(**{name: value})))
                self.assertTrue(any(name in issue for issue in issues), issues)
        inputs = {"required": {"clip": ("CLIP", {}), "text": ("STRING", {})}, "hidden": {"prompt": "PROMPT"}}
        issues = verify_node.contract_issues(node_module(node_class(INPUTS=inputs)))
        self.assertEqual(len(issues), 3, issues)
        self.assertTrue(any("is not lazy" in issue for issue in issues), issues)

    def test_runtime_issues_name_the_missing_module(self) -> None:
        with patch.object(verify_node, "RUNTIME_MODULES", ("verify_node_missing_module",)):
            self.assertTrue(verify_node.runtime_issues(Path(__file__).parent))
        with patch.object(verify_node, "RUNTIME_MODULES", ()):
            self.assertEqual(verify_node.runtime_issues(Path(__file__).parent), [])

    def test_main_reports_success_and_failure(self) -> None:
        with (
            patch.object(verify_node, "runtime_issues", return_value=[]),
            patch.object(verify_node, "provider_issues", return_value=[]),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(verify_node.main([str(TRACKED_NODE)]), 0)
            self.assertIn("[OK] ComfyUI node", output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(verify_node.main([str(TRACKED_NODE.parent / "absent.py")]), 1)
        self.assertIn("missing installed copy", output.getvalue())


class ProviderTests(unittest.TestCase):
    def test_registered_type_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory)
            provider = custom_nodes / "ComfyUI-GGUF"
            provider.mkdir()
            (provider / "nodes.py").write_text(
                'NODE_CLASS_MAPPINGS = {\n    "CLIPLoaderGGUF": CLIPLoaderGGUF,\n}\n', encoding="utf-8"
            )
            issues = verify_node.provider_issues(custom_nodes)
            self.assertNotIn("CLIPLoaderGGUF: custom_nodes/ComfyUI-GGUF does not register it", issues)

    def test_missing_folder_and_missing_registration_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory)
            (custom_nodes / "ComfyUI-GGUF").mkdir()
            issues = verify_node.provider_issues(custom_nodes)
            self.assertTrue(any("does not register" in issue for issue in issues), issues)
            self.assertTrue(any("is missing" in issue for issue in issues), issues)

    def test_comment_only_mention_is_not_a_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory)
            provider = custom_nodes / "ComfyUI-GGUF"
            provider.mkdir()
            (provider / "notes.py").write_text('"""CLIPLoaderGGUF is handled elsewhere."""\n', encoding="utf-8")
            issues = verify_node.provider_issues(custom_nodes)
            self.assertTrue(any(issue.startswith("CLIPLoaderGGUF") for issue in issues), issues)


if __name__ == "__main__":
    unittest.main()
