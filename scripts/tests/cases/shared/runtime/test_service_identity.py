"""A reused service identity must not crash when its process exits between the port probe and the read."""

import unittest
from unittest.mock import MagicMock, patch

from scripts.shared import service_identity


class EndpointIdentityTests(unittest.TestCase):
    def test_a_listening_process_contributes_its_start_time(self):
        process = MagicMock()
        process.create_time.return_value = 12.5
        with (
            patch.object(service_identity.launch_util, "listening_process_ids", return_value={7}),
            patch.object(service_identity.psutil, "Process", return_value=process),
        ):
            self.assertEqual(service_identity.endpoint_identity(8080, "model"), "model:[(7, 12.5)]")

    def test_a_process_that_exits_during_the_check_leaves_no_identity(self):
        with (
            patch.object(service_identity.launch_util, "listening_process_ids", return_value={7}),
            patch.object(service_identity.psutil, "Process", side_effect=service_identity.psutil.NoSuchProcess(7)),
        ):
            self.assertEqual(service_identity.endpoint_identity(8080, "model"), "")

    def test_no_listener_is_an_empty_identity(self):
        with patch.object(service_identity.launch_util, "listening_process_ids", return_value=set()):
            self.assertEqual(service_identity.endpoint_identity(8080, "model"), "")


if __name__ == "__main__":
    unittest.main()
