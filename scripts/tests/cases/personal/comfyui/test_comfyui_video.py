"""Model-free checks for saved workflow conversion and execution events."""

import json
import math
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.benchmarks.personal.comfyui.comfyui_settings import commands, setting_cases
from scripts.benchmarks.personal.comfyui.comfyui_video import (
    ENCODERS,
    MODELS,
    check_ports,
    generate,
    launch_options,
    tile_cases,
)
from scripts.config import project_config as project_cfg
from scripts.config.comfyui import workflow_overrides
from scripts.config.comfyui.workflow_overrides import (
    LTXWorkflowOverrides,
    VAEDecode,
    VideoVAE,
    adapt_loaders,
    set_video_decode,
    workflow,
)
from scripts.tests.shared.paths import CasePaths


def response_context(payload: object) -> AsyncMock:
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value=payload)
    context = AsyncMock()
    context.__aenter__.return_value = response
    return context


class WorkflowTests(unittest.TestCase):
    def test_setting_screen_fixes_workload_and_keeps_reverse_order(self) -> None:
        self.assertEqual(
            setting_cases("focused"),
            [
                ("baseline", []),
                ("dynamic-off", ["--launch-case", "dynamic-off"]),
                ("spatial-1024-256", ["--spatial-tile", "1024", "--spatial-overlap", "256"]),
            ],
        )
        scaling = setting_cases("scaling")
        self.assertEqual(len(scaling), 4)
        self.assertEqual([options[1] for _, options in scaling], ["640", "640", "10", "10"])
        self.assertEqual(
            [options[-3:] for _, options in scaling],
            [
                ["512", "--spatial-overlap", "64"],
                ["1024", "--spatial-overlap", "256"],
                ["512", "--spatial-overlap", "64"],
                ["1024", "--spatial-overlap", "256"],
            ],
        )
        for group in ("focused", "scaling", "stability", "flags", "spatial", "temporal"):
            plan = commands(group, 2, False, True)
            self.assertEqual(commands(group, 2, True, True), list(reversed(plan)))
            for _, command in plan:
                self.assertIn("--dry-run", command)
                self.assertEqual(command[command.index("--video-vae") + 1], "diffusion")
                self.assertEqual(command[command.index("--model") + 1], "2")
                self.assertEqual(command[command.index("--encoder") + 1], "1")
        stability = setting_cases("stability")
        self.assertEqual(["--no-vram-monitor" in options for _, options in stability], [False, True, True, False])

    def test_tile_matrix_is_bounded_and_uses_original_vae(self) -> None:
        cases = tile_cases("all")
        self.assertEqual(len(cases), 9)
        self.assertEqual(len(tile_cases("spatial")), 6)
        self.assertEqual(len(tile_cases("temporal")), 3)
        self.assertEqual(len({name for name, _ in cases}), 9)
        saved = json.loads((project_cfg.CONFIG_DIR / "comfyui/workflows/video_ltx2_5_i2v_default.json").read_text())
        for name, settings in cases:
            self.assertEqual(settings.video_vae, VideoVAE.DIFFUSION)
            self.assertEqual(settings.vae_decode, VAEDecode.TILED)
            graph = workflow(saved, settings)
            effective = settings.effective_settings(graph, saved["extra"]["benchmark_controls"])
            self.assertEqual(effective["spatial_tile"], settings.spatial_tile)
            self.assertEqual(effective["temporal_tile"], settings.temporal_tile)
            self.assertEqual(graph["14"]["inputs"]["noise_seed"], 42)
            if name.startswith("temporal"):
                self.assertEqual(settings.seconds, 10)
                self.assertEqual(settings.resolution, 480)

    def test_prompt_overrides_replace_only_conditioning_text(self) -> None:
        saved = json.loads((project_cfg.CONFIG_DIR / "comfyui/workflows/video_ltx2_5_i2v_fast480.json").read_text())
        graph = workflow(saved, LTXWorkflowOverrides(prompt="sunset", negative="bad"))
        texts = {
            node["inputs"].get("text") for node in graph.values() if str(node["class_type"]).endswith("TextEncode")
        }
        self.assertEqual(texts, {"sunset", "bad"})

    def test_prompt_appends_keep_the_workflow_text(self) -> None:
        saved = json.loads((project_cfg.CONFIG_DIR / "comfyui/workflows/video_ltx2_5_i2v_fast480.json").read_text())
        workflow_overrides.patch_prompts(saved, negative_append="watermark")
        negatives = [
            node["widgets_values_named"]["text"]
            for node in saved["nodes"]
            if isinstance(node.get("widgets_values_named"), dict)
            and "shaky" in str(node["widgets_values_named"].get("text"))
        ]
        self.assertEqual(len(negatives), 1)
        self.assertTrue(negatives[0].endswith(", watermark"))
        self.assertIn("bad anatomy", negatives[0])

    def test_a_shared_text_node_is_only_written_once(self) -> None:
        saved = json.loads((project_cfg.CONFIG_DIR / "comfyui/workflows/video_ltx2_5_i2v_default.json").read_text())
        graph = workflow(saved, LTXWorkflowOverrides(negative="bad"))
        texts = {
            node["inputs"].get("text") for node in graph.values() if str(node["class_type"]).endswith("TextEncode")
        }
        self.assertEqual(len(texts), 1)
        self.assertNotIn("bad", texts)

    def test_vae_and_loader_choices_do_not_mutate_saved_workflow(self) -> None:
        saved = json.loads((project_cfg.CONFIG_DIR / "comfyui/workflows/video_ltx2_5_i2v_default.json").read_text())
        original = json.dumps(saved)
        settings = LTXWorkflowOverrides(dynamic_vram=False, video_vae=VideoVAE.CONV, vae_decode=VAEDecode.UNTILED)
        graph = workflow(saved, settings)
        self.assertEqual(graph["2"]["class_type"], "UnetLoaderGGUF")
        self.assertEqual(graph["4"]["inputs"]["vae_name"], settings.video_vae_filename)
        self.assertEqual(graph["20"]["class_type"], "VAEDecode")
        self.assertEqual(set(graph["20"]["inputs"]), {"samples", "vae"})
        self.assertEqual(json.dumps(saved), original)
        graph = workflow(saved, LTXWorkflowOverrides(dynamic_vram=True))
        effective = LTXWorkflowOverrides().effective_settings(graph, saved["extra"]["benchmark_controls"])
        self.assertEqual(effective["seconds"], 5)
        self.assertEqual(effective["resolution"], 480)
        self.assertEqual(effective["temporal_tile"], 128)
        self.assertEqual(effective["temporal_overlap"], 32)
        self.assertEqual(graph["2"]["class_type"], "UnetLoaderGGUFDynamicVRAM")
        self.assertEqual(graph["35"]["class_type"], "CLIPLoaderGGUF")
        self.assertEqual(graph["20"]["class_type"], "VAEDecodeTiled")

    def test_dynamic_off_uses_regular_gguf_loaders(self) -> None:
        graph: dict[str, Any] = {
            "2": {"class_type": "UnetLoaderGGUFDynamicVRAM", "inputs": {"unet_name": "model.gguf"}}
        }
        adapt_loaders(graph, ["--disable-dynamic-vram"])
        self.assertEqual(graph["2"]["class_type"], "UnetLoaderGGUF")
        self.assertEqual(graph["2"]["inputs"]["unet_name"], "model.gguf")

    def test_untiled_decode_drops_tiling_inputs(self) -> None:
        graph = {
            "20": {
                "class_type": "VAEDecodeTiled",
                "inputs": {"samples": ["19", 0], "vae": ["4", 0], "tile_size": ["50", 0]},
            }
        }
        set_video_decode(graph, "untiled")
        self.assertEqual(graph["20"], {"class_type": "VAEDecode", "inputs": {"samples": ["19", 0], "vae": ["4", 0]}})

    def test_commented_settings_defer_to_comfyui(self) -> None:
        with patch(
            "pathlib.Path.read_text",
            return_value='::set "DYNAMIC_VRAM=1"\nREM set "FA_AUTOTUNE=1"\nset "DISABLE_TRITON=0"\n',
        ):
            flags, env = launch_options("user")
        self.assertIn("--enable-triton-backend", flags)
        self.assertNotIn("--enable-dynamic-vram", flags)
        self.assertNotIn("--disable-dynamic-vram", flags)
        self.assertNotIn("FLASH_ATTENTION_TRITON_AMD_AUTOTUNE", env)

    def test_free_ports_do_not_require_a_connect_response(self) -> None:
        with patch("scripts.benchmarks.personal.comfyui.comfyui_video.socket.socket") as socket_factory:
            connection = socket_factory.return_value.__enter__.return_value
            connection.connect.side_effect = TimeoutError("filtered localhost connect")
            check_ports(8190)
            self.assertEqual(connection.bind.call_count, 2)
            connection.connect.assert_not_called()

    def test_unavailable_port_prevents_launch(self) -> None:
        with patch("scripts.benchmarks.personal.comfyui.comfyui_video.socket.socket") as socket_factory:
            connection = socket_factory.return_value.__enter__.return_value
            connection.bind.side_effect = OSError("address already in use")
            with self.assertRaisesRegex(RuntimeError, "Cannot reserve localhost port"):
                check_ports(8190)

    def test_saved_links_and_settings_are_preserved(self) -> None:
        saved = json.loads((project_cfg.CONFIG_DIR / "comfyui/workflows/video_ltx2_5_i2v_original.json").read_text())
        fps_node = next(node for node in saved["nodes"] if node["id"] == 42)
        self.assertEqual(fps_node["type"], "PrimitiveFloat")
        self.assertEqual(fps_node["outputs"][0]["type"], "FLOAT")
        controls = {node["id"]: node for node in saved["nodes"]}
        self.assertEqual(controls[54]["widgets_values_named"]["value"], 2)
        self.assertEqual(controls[57]["widgets_values_named"]["value"], 5.0)
        graph = workflow(saved, LTXWorkflowOverrides(model=MODELS[0], encoder=ENCODERS[1], prefix="test"))
        self.assertEqual(graph["10"]["inputs"]["length"], ["43", 1])
        self.assertEqual(graph["11"]["inputs"]["strength"], ["45", 0])
        self.assertEqual(graph["45"]["inputs"]["value"], 0.7)
        self.assertEqual(graph["36"]["inputs"]["resize_type.longer_size"], ["49", 0])
        self.assertEqual(graph["49"]["inputs"]["value"], 1536)
        self.assertEqual(graph["27"]["inputs"]["values.c"], ["31", 1])
        self.assertEqual(graph["10"]["inputs"]["width"], ["27", 1])
        self.assertEqual(graph["2"]["inputs"]["unet_name"], MODELS[0])
        self.assertEqual(graph["35"]["inputs"]["clip_name"], ENCODERS[1])
        self.assertNotIn("control_after_generate", graph["14"]["inputs"])
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list):
                    self.assertIn(value[0], graph)

    def test_seconds_fps_and_resolution_overrides(self) -> None:
        saved = json.loads((project_cfg.CONFIG_DIR / "comfyui/workflows/video_ltx2_5_i2v_original.json").read_text())

        def evaluate(graph: dict[str, Any], key: str, slot: int = 0) -> int | float:
            if key == "24":
                return (1920, 2496)[slot]
            node = graph[key]
            fields = node["inputs"]
            if node["class_type"].startswith("Primitive"):
                return fields["value"]
            values = {
                name.split(".")[1]: evaluate(graph, value[0], value[1]) if isinstance(value, list) else value
                for name, value in fields.items()
                if name.startswith("values.")
            }
            return eval(
                fields["expression"], {"__builtins__": {}, "max": max, "round": round, "sqrt": math.sqrt}, values
            )

        for mode, seconds, resolution in ((1, 2, 320), (2, 5, 480), (3, 10, 640), (4, 15, 720)):
            graph = workflow(
                saved, LTXWorkflowOverrides(model=MODELS[0], encoder=ENCODERS[0], prefix="test", mode=mode)
            )
            self.assertEqual(evaluate(graph, "41"), seconds)
            self.assertEqual(evaluate(graph, "40"), resolution)
            for key, expected in (("50", 512), ("51", 64), ("52", 64), ("53", 16)):
                self.assertEqual(evaluate(graph, key, 1), expected)
            self.assertEqual(evaluate(graph, "43", 1), 1 + 8 * round(seconds * 24 / 8))
        targets = {node["id"]: node for node in saved["nodes"]}
        targets[71]["widgets_values_named"]["value"] = 32
        graph = workflow(saved, LTXWorkflowOverrides(model=MODELS[0], encoder=ENCODERS[0], prefix="test", mode=1))
        self.assertEqual(evaluate(graph, "52", 1), 32)
        graph = workflow(
            saved,
            LTXWorkflowOverrides(
                model=MODELS[0], encoder=ENCODERS[0], prefix="test", temporal_tile=96, spatial_tile=768
            ),
        )
        self.assertEqual(evaluate(graph, "52", 1), 96)
        self.assertEqual(evaluate(graph, "50", 1), 768)
        self.assertEqual(graph["20"]["inputs"]["tile_size"], ["50", 1])
        for seconds, fps, video, audio in ((10, 24, 241, 240), (5, 24, 121, 120), (2, 12, 25, 24), (0.1, 24, 9, 8)):
            graph = workflow(
                saved,
                LTXWorkflowOverrides(
                    model=MODELS[0], encoder=ENCODERS[0], prefix="test", seconds=seconds, fps=fps, resolution=480
                ),
            )
            self.assertEqual(evaluate(graph, "43", 1), video)
            self.assertEqual(evaluate(graph, "44", 1), audio)
            self.assertEqual(evaluate(graph, "31", 1), 230400)
            self.assertEqual(evaluate(graph, "27", 1), 416)
            self.assertEqual(evaluate(graph, "29", 1), 544)
            for node, field in (("8", "frame_rate"), ("12", "frame_rate"), ("22", "fps")):
                self.assertEqual(graph[node]["inputs"][field], ["42", 0])
            self.assertEqual(graph["42"]["inputs"]["value"], fps)


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_and_history(self) -> None:
        from aiohttp import WSMsgType

        paths = CasePaths(__file__).new_run()
        session = MagicMock()
        ws = MagicMock()
        messages = [
            {"type": "executing", "data": {"prompt_id": "other", "node": "99"}},
            {"type": "executing", "data": {"prompt_id": "p", "node": "18"}},
            {"type": "progress", "data": {"prompt_id": "p", "node": "18", "value": 8, "max": 8}},
            {"type": "executing", "data": {"prompt_id": "p", "node": None}},
        ]
        ws.receive = AsyncMock(side_effect=[SimpleNamespace(type=WSMsgType.TEXT, data=json.dumps(m)) for m in messages])
        context = AsyncMock()
        context.__aenter__.return_value = ws
        session.ws_connect.return_value = context
        session.post.return_value = response_context({"prompt_id": "p"})
        history = {
            "p": {"status": {"status_str": "success"}, "outputs": {"23": {"images": [{"filename": "test.mp4"}]}}}
        }
        session.get.return_value = response_context(history)
        with patch("tqdm.tqdm") as progress:
            progress.return_value.__enter__.return_value.n = 0
            result = await generate(
                session, "http://test", {"18": {"class_type": "SamplerCustomAdvanced"}}, paths, "mock", 5
            )
            progress.return_value.__enter__.return_value.update.assert_called_once_with(8)
        self.assertIsNotNone(result["sampler_seconds"])
        self.assertEqual(result["outputs"], history["p"]["outputs"])

    async def test_execution_error_is_not_success(self) -> None:
        from aiohttp import WSMsgType

        paths = CasePaths(__file__).new_run()
        session = MagicMock()
        ws = MagicMock()
        ws.receive = AsyncMock(
            return_value=SimpleNamespace(
                type=WSMsgType.TEXT,
                data=json.dumps(
                    {"type": "execution_error", "data": {"prompt_id": "p", "exception_message": "out of memory"}}
                ),
            )
        )
        context = AsyncMock()
        context.__aenter__.return_value = ws
        session.ws_connect.return_value = context
        session.post.return_value = response_context({"prompt_id": "p"})
        with patch("tqdm.tqdm"), self.assertRaisesRegex(RuntimeError, "out of memory"):
            await generate(session, "http://test", {}, paths, "mock-error", 5)
        session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
