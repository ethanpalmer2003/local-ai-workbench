"""Network timeout policy: an HTTP call without a bound is rejected, wrapped calls included."""

import tempfile
import unittest
from pathlib import Path

from scripts.review import network_timeouts


class NetworkTimeoutTests(unittest.TestCase):
    def _issues(self, body: str) -> list[str]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "module.py"
            path.write_text(body, encoding="utf-8")
            return network_timeouts.issues(path)

    def test_a_bare_raw_connection_is_rejected(self):
        body = "from http.client import HTTPConnection\nconnection = HTTPConnection('127.0.0.1', 80)\n"
        found = self._issues(body)
        self.assertTrue(any("without a timeout" in issue for issue in found))

    def test_raw_connections_accept_a_timeout(self):
        body = "import http.client\nconnection = http.client.HTTPSConnection('example.test', 443, timeout=30)\n"
        self.assertEqual(self._issues(body), [])

    def test_a_bare_urlopen_is_rejected(self):
        found = self._issues("import urllib.request\nurllib.request.urlopen(request)\n")
        self.assertTrue(any("without a timeout" in issue for issue in found))

    def test_a_timeout_argument_is_accepted(self):
        self.assertEqual(self._issues("import urllib.request\nurllib.request.urlopen(request, timeout=5)\n"), [])

    def test_a_wrapped_call_is_accepted(self):
        body = "import urllib.request\nresponse = urllib.request.urlopen(\n    request,\n    timeout=300,\n)\n"
        self.assertEqual(self._issues(body), [])

    def test_requests_without_a_timeout_is_rejected(self):
        self.assertTrue(self._issues("import requests\nrequests.get('https://example.invalid')\n"))

    def test_the_project_local_wrapper_owns_its_timeout(self):
        body = "from scripts.launchers.asr.shared import requests\nrequests.post(url, body, kind)\n"
        self.assertEqual(self._issues(body), [])


if __name__ == "__main__":
    unittest.main()
