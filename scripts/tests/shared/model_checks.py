"""Model and install checks: one-time facts about downloaded assets, not our code.

They stay out of the default regression run because they assert what a model file, GGUF metadata or an
installed framework declares. Run them after a download or an update with ``AI_MODEL_CHECKS=1``.
"""

import os
import unittest

ENABLED = os.environ.get("AI_MODEL_CHECKS") == "1"

requires_model_check = unittest.skipUnless(ENABLED, "model/install check: rerun with AI_MODEL_CHECKS=1")
