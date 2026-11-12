"""What kind of thing is parked, so the parked-work page cannot invent a category."""

from enum import Enum


class DeferredKind(str, Enum):
    """A parked thing is a weight, an install, a build, a table row, a platform, or a task."""

    MODEL = "model"
    FRAMEWORK = "framework"
    BUILD = "build"
    ROW = "row"
    RUNTIME = "runtime"
    WORK = "work"
