"""Canonical model registry API; consumers import this package, not category catalogs."""

from pathlib import Path

from .catalog import CATALOG_PATH as CATALOG_PATH
from .catalog import IDS_PATH as IDS_PATH
from .catalog import MODELS as MODELS
from .catalog import destination as destination
from .catalog import filename as filename
from .catalog import get as get
from .catalog import label_for_path as label_for_path
from .catalog import models_for as models_for
from .catalog import path as path
from .ids import ModelId as ModelId
from .types import ModelDownload as ModelDownload
