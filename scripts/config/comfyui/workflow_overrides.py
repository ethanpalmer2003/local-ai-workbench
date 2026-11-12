"""Typed overrides for the project's saved LTX 2.5 workflows; no server or filesystem side effects."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# - Upstream LTX-2 model-card examples; generic placeholders until a prompt is supplied.
DEFAULT_PROMPT = "A beautiful sunset over the ocean"
DEFAULT_NEGATIVE = (
    "shaky, glitchy, low quality, worst quality, deformed, distorted, disfigured, motion smear, "
    "motion artifacts, fused fingers, bad anatomy, weird hand, ugly, transition, static."
)


def _text_source(
    by_id: dict[str, dict[str, Any]], links: dict[int, list[Any]], kind: str, link_id: int | None
) -> str | None:
    """Follow one conditioning link to the TextEncode node that owns it."""
    link = links.get(link_id) if link_id is not None else None
    if not link:
        return None
    origin = by_id.get(str(link[1]))
    if origin is None:
        return None
    if str(origin["type"]).endswith("TextEncode"):
        return str(origin["id"])
    for field in origin.get("inputs") or []:
        if field.get("name") == kind:
            return _text_source(by_id, links, kind, field.get("link"))
    return None


def text_nodes(nodes: list[dict[str, Any]], links: dict[int, list[Any]]) -> Iterator[tuple[str, str]]:
    """Yield (positive|negative, node id) by following each conditioning input to its text encoder.

    Guiders point at a conditioning node that splits positive/negative itself, so the same
    kind name is followed recursively before falling back to an upstream search.
    """
    by_id = {str(node["id"]): node for node in nodes}
    seen: set[tuple[str, str]] = set()
    for node in nodes:
        for field in node.get("inputs") or []:
            kind = str(field.get("name"))
            if kind not in ("positive", "negative"):
                continue
            key = _text_source(by_id, links, kind, field.get("link"))
            if key and (kind, key) not in seen:
                seen.add((kind, key))
                yield kind, key


CONTROL_NAMES = (
    "seconds",
    "fps",
    "resolution",
    "mode",
    "spatial_tile",
    "spatial_overlap",
    "temporal_tile",
    "temporal_overlap",
)


def _apply_control(graph: dict[str, Any], controls: dict[str, int], name: str, value: Any) -> None:
    if name not in controls:
        raise ValueError(f"Workflow has no {name} control; use the supplied simplified workflow")
    control = graph[str(controls[name])]
    if control["class_type"] == "ComfyMathExpression":
        control["inputs"] = {"expression": "a", "values.a": value}
    else:
        control["inputs"]["value"] = value


def _written(current: str, replace_text: str | None, append_text: str | None) -> str | None:
    """A replacement wins; an append is joined onto whatever the workflow already carries."""
    if replace_text is not None:
        return replace_text
    if append_text:
        return f"{current.rstrip(', ')}, {append_text}" if current.strip() else append_text
    return None


def patch_prompts(
    saved: dict[str, Any],
    positive: str | None = None,
    negative: str | None = None,
    positive_append: str | None = None,
    negative_append: str | None = None,
) -> dict[str, Any]:
    """Replace or extend the saved workflow's positive/negative text in place and return it."""
    if all(value is None for value in (positive, negative, positive_append, negative_append)):
        return saved
    links = {link[0]: link for link in saved.get("links") or []}
    by_id = {str(node["id"]): node for node in saved.get("nodes") or []}
    targets = dict(text_nodes(saved.get("nodes") or [], links))
    for kind, replace_text, append_text in (
        ("positive", positive, positive_append),
        ("negative", negative, negative_append),
    ):
        key = targets.get(kind)
        if key is None or (kind == "negative" and targets.get("positive") == key):
            continue
        widgets = by_id[key].get("widgets_values_named")
        if not isinstance(widgets, dict) or not isinstance(widgets.get("text"), str):
            continue
        text = _written(widgets["text"], replace_text, append_text)
        if text is not None:
            widgets["text"] = text
    return saved


def _text_encoder_ref(graph: dict[str, Any], kind: str, ref: Any) -> str | None:
    """Walk a conditioning reference down to the TextEncode node it came from."""
    if not isinstance(ref, list) or len(ref) != 2:
        return None
    node = graph.get(str(ref[0]))
    if node is None:
        return None
    if str(node["class_type"]).endswith("TextEncode"):
        return str(ref[0])
    for name, value in node["inputs"].items():
        if name == kind:
            return _text_encoder_ref(graph, kind, value)
    return None


def _prompt_targets(graph: dict[str, Any]) -> dict[str, str]:
    targets: dict[str, str] = {}
    for node in graph.values():
        for name, ref in node["inputs"].items():
            if name in ("positive", "negative") and name not in targets:
                found = _text_encoder_ref(graph, name, ref)
                if found:
                    targets[name] = found
    return targets


def _apply_prompt(graph: dict[str, Any], key: str, replace_text: str | None, append_text: str | None) -> None:
    current = graph[key]["inputs"].get("text")
    if not isinstance(current, str):
        # - the API graph omits untouched widget text, so only a replacement is possible
        if replace_text is None:
            return
        current = ""
    text = _written(current, replace_text, append_text)
    if text is not None:
        graph[key]["inputs"]["text"] = text


def patch_graph_prompts(
    graph: dict[str, Any],
    positive: str | None = None,
    negative: str | None = None,
    positive_append: str | None = None,
    negative_append: str | None = None,
) -> None:
    """Apply the same prompt override to an already-converted API graph."""
    if all(value is None for value in (positive, negative, positive_append, negative_append)):
        return
    targets = _prompt_targets(graph)
    for kind, replace_text, append_text in (
        ("positive", positive, positive_append),
        ("negative", negative, negative_append),
    ):
        key = targets.get(kind)
        if key is None or (kind == "negative" and targets.get("positive") == key):
            continue
        _apply_prompt(graph, key, replace_text, append_text)


class VideoVAE(StrEnum):
    SAVED = "saved"
    DIFFUSION = "diffusion"


class VAEDecode(StrEnum):
    SAVED = "saved"
    TILED = "tiled"
    UNTILED = "untiled"


@dataclass(frozen=True)
class LTXWorkflowOverrides:
    model: str | None = None
    encoder: str | None = None
    prompt: str | None = None
    negative: str | None = None
    prompt_append: str | None = None
    negative_append: str | None = None
    prefix: str | None = None
    seconds: float | None = None
    fps: int | None = None
    resolution: int | None = None
    mode: int | None = None
    spatial_tile: int | None = None
    spatial_overlap: int | None = None
    temporal_tile: int | None = None
    temporal_overlap: int | None = None
    dynamic_vram: bool | None = None
    video_vae: VideoVAE = VideoVAE.SAVED
    vae_decode: VAEDecode = VAEDecode.SAVED

    @property
    def video_vae_filename(self) -> str | None:
        if self.video_vae == VideoVAE.SAVED:
            return None
        return "ltx-2.5-video-vae-bf16.safetensors"

    def _apply_loaders(self, graph: dict[str, Any]) -> None:
        for node in graph.values():
            if node["class_type"].startswith("UnetLoaderGGUF") and self.model is not None:
                node["inputs"]["unet_name"] = self.model
            elif node["class_type"].startswith("CLIPLoaderGGUF") and self.encoder is not None:
                node["inputs"]["clip_name"] = self.encoder
            elif node["class_type"] == "SaveVideo" and self.prefix is not None:
                node["inputs"]["filename_prefix"] = self.prefix

    @staticmethod
    def _apply_dynamic_vram(graph: dict[str, Any], dynamic_vram: bool | None) -> None:
        if dynamic_vram is not None:
            set_dynamic_vram(graph, dynamic_vram)

    def apply(self, graph: dict[str, Any], controls: dict[str, int]) -> None:
        for name in CONTROL_NAMES:
            value = getattr(self, name)
            if value is not None:
                _apply_control(graph, controls, name, value)
        self._apply_loaders(graph)
        self._apply_dynamic_vram(graph, self.dynamic_vram)
        set_video_decode(graph, self.vae_decode)
        if self.video_vae_filename is not None:
            graph["4"]["inputs"]["vae_name"] = self.video_vae_filename
        patch_graph_prompts(graph, self.prompt, self.negative, self.prompt_append, self.negative_append)

    def effective_settings(self, graph: dict[str, Any], controls: dict[str, int]) -> dict[str, Any]:
        """Resolve the supplied workflow's primitive controls and four-mode selectors."""

        def value(source: Any) -> Any:
            if not isinstance(source, list):
                return source
            node = graph[source[0]]
            inputs = node["inputs"]
            if node["class_type"].startswith("Primitive"):
                return inputs["value"]
            expression = inputs["expression"]
            if expression == "a":
                return value(inputs["values.a"])
            if expression == "b if a <= 1 else c if a == 2 else d if a == 3 else e":
                mode = value(inputs["values.a"])
                key = "b" if mode <= 1 else "c" if mode == 2 else "d" if mode == 3 else "e"
                return value(inputs[f"values.{key}"])
            raise ValueError(f"Unsupported settings expression: {expression}")

        resolved = {
            name: value([str(controls[name]), 0])
            for name in (
                "seconds",
                "fps",
                "resolution",
                "mode",
                "spatial_tile",
                "spatial_overlap",
                "temporal_tile",
                "temporal_overlap",
            )
            if name in controls
        }
        resolved.update(
            model=graph["2"]["inputs"]["unet_name"],
            encoder=graph["35"]["inputs"]["clip_name"],
            prefix=graph["23"]["inputs"]["filename_prefix"],
            unet_loader=graph["2"]["class_type"],
            clip_loader=graph["35"]["class_type"],
            video_vae=graph["4"]["inputs"]["vae_name"],
            vae_decode=graph["20"]["class_type"],
        )
        return resolved


def _node_inputs(node: dict[str, Any], links: dict[int, list[Any]], widgets: dict[str, Any]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for field in node.get("inputs", []):
        if field.get("link") is not None:
            link = links[field["link"]]
            inputs[field["name"]] = [str(link[1]), link[2]]
        elif field.get("widget"):
            inputs[field["name"]] = widgets[field["widget"]["name"]]
    return inputs


def _graph_from_saved(saved: dict[str, Any], links: dict[int, list[Any]]) -> dict[str, Any]:
    graph: dict[str, Any] = {}
    for node in saved["nodes"]:
        if node.get("mode", 0) != 0:
            continue
        widgets = node.get("widgets_values_named", {})
        if node.get("widgets_values") and not widgets:
            raise ValueError(f"Node {node['id']} lacks named widgets; save it with the current frontend first")
        graph[str(node["id"])] = {"class_type": node["type"], "inputs": _node_inputs(node, links, widgets)}
    return graph


def _visit_inputs(graph: dict[str, Any], key: str, reachable: set[str]) -> None:
    if key in reachable:
        return
    reachable.add(key)
    for value in graph[key]["inputs"].values():
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
            _visit_inputs(graph, value[0], reachable)


def _reachable(graph: dict[str, Any]) -> set[str]:
    """Only what a SaveVideo node can reach survives conversion."""
    reachable: set[str] = set()
    for key, node in graph.items():
        if node["class_type"] == "SaveVideo":
            _visit_inputs(graph, key, reachable)
    return reachable


def workflow(saved: dict[str, Any], overrides: LTXWorkflowOverrides) -> dict[str, Any]:
    links = {link[0]: link for link in saved["links"]}
    graph = _graph_from_saved(saved, links)
    reachable = _reachable(graph)
    graph = {key: node for key, node in graph.items() if key in reachable}
    overrides.apply(graph, saved.get("extra", {}).get("benchmark_controls", {}))
    return graph


def set_video_decode(graph: dict[str, Any], mode: str) -> None:
    if mode == "saved":
        return
    for node in graph.values():
        if node["class_type"] in {"VAEDecode", "VAEDecodeTiled"}:
            if mode == "untiled":
                node["class_type"] = "VAEDecode"
                node["inputs"] = {k: v for k, v in node["inputs"].items() if k in {"samples", "vae"}}
            else:
                node["class_type"] = "VAEDecodeTiled"
                for name, value in (
                    ("tile_size", 512),
                    ("overlap", 64),
                    ("temporal_size", 64),
                    ("temporal_overlap", 16),
                ):
                    node["inputs"].setdefault(name, value)


DYNAMIC_SUFFIX = "DynamicVRAM"
GGUF_LOADERS = (
    "UnetLoaderGGUF",
    "CLIPLoaderGGUF",
    "DualCLIPLoaderGGUF",
    "TripleCLIPLoaderGGUF",
    "QuadrupleCLIPLoaderGGUF",
)


def set_dynamic_vram(graph: dict[str, Any], enabled: bool) -> None:
    """Switch every GGUF loader node to its DynamicVRAM variant, or back to the plain one."""
    for node in graph.values():
        base = node["class_type"].removesuffix(DYNAMIC_SUFFIX)
        if base in GGUF_LOADERS:
            node["class_type"] = base + (DYNAMIC_SUFFIX if enabled else "")
