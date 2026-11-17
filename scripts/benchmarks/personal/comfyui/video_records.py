"""The small records the ComfyUI video benchmark returns from its selection and launch steps."""

from typing import Any, NamedTuple


class SelectedSources(NamedTuple):
    """The model, encoder and preset choices a run resolved, with their sources."""

    models: tuple[str, ...]
    encoders: tuple[str, ...]
    presets: tuple[str, ...]
    sources: dict[str, Any]
    saved_workflows: dict[str, Any]


class LaunchPlan(NamedTuple):
    """The command, graph and metadata a launch needs, plus its overrides."""

    command: list[str]
    graph: dict[str, Any]
    metadata: dict[str, Any]
    overrides: dict[str, str]
