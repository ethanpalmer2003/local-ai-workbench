"""The Lite page patch points a no-model instance at the external engine without a dialog."""

import unittest

from scripts.launchers.koboldcpp import kobold_lite


class ExternalSeedTests(unittest.TestCase):
    def test_seed_writes_only_absent_keys_and_selects_the_provider(self):
        script = kobold_lite.external_script("http://192.0.2.110:5001/v1", "character-external")
        self.assertIn("kaihordewebui_custom_oai_endpoint')===null", script)
        self.assertIn("http://192.0.2.110:5001/v1", script)
        self.assertIn("character-external", script)
        # - the same work Lite's own dialog does when answered yes
        self.assertIn("customapidropdown", script)
        self.assertIn("localflag=false", script)

    def test_no_model_dialog_stays_out_of_the_way_when_a_provider_is_configured(self):
        html = (
            "<body>else if(localflag && no_txt_model && !koboldcpp_has_txt2img && "
            "!koboldcpp_has_vision && !koboldcpp_has_whisper && !koboldcpp_has_tts && "
            "!is_using_kcpp_with_admin())\n{}\n</body>"
        )
        patched = kobold_lite.guard_no_model_dialog(html)
        self.assertIn("!localStorage.getItem('kaihordewebui_custom_oai_endpoint'))", patched)


if __name__ == "__main__":
    unittest.main()
