"""Image-session settings; native APIs own model-management schemas."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageOnDemandStartupSettings:
    image_recipe: str = "sdxl-checkpoint"
    transition_timeout_seconds: float = 180
    busy_retry_seconds: float = 0.25
    native_request_timeout_seconds: float = 30


SETTINGS = ImageOnDemandStartupSettings()
