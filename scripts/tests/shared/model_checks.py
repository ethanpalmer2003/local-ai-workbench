"""Model and install checks: one-time facts about downloaded assets, not our code.

They stay out of the default regression run because they assert what a model file, GGUF metadata or an
installed framework declares, so only a download, framework update or machine change can break them.
Run them after one with ``AI_MODEL_CHECKS=1``. Duration is not the reason: a check that asserts
behavior this repository owns stays in the default run however long it takes.
"""

import os
import unittest

ENABLED = os.environ.get("AI_MODEL_CHECKS") == "1"

requires_model_check = unittest.skipUnless(
    ENABLED, "asserts an installed asset or the machine's environment: rerun with AI_MODEL_CHECKS=1"
)
