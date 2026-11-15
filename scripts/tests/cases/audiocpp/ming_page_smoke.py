"""Brief Ming clone/stream check through the same running proxy used by the HTML page."""

import json
import wave

import requests

from scripts.benchmarks.shared import reporting
from scripts.benchmarks.shared.reporting import report_run
from scripts.config import models as model_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.tests.cases.audiocpp.audiocpp_transport import measure
from scripts.tests.shared.paths import CasePaths


def main() -> None:
    context = dict(require_native_execution("Ming test-page smoke"))
    root = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}"
    model = cfg.AudiocppModel.MING3_TTS.value
    run = CasePaths(__file__).new_run()
    print(f"[OUTPUT] {run.root}", flush=True)
    with report_run(run, "Ming test page / clone / SSE", "audiocpp", settings={"execution_context": context}) as report:
        # - /test/ redirects to the practice workspace by design; the assets must answer directly
        for path, expected in (
            ("/test/", 307),
            ("/test/comparison.js", 200),
            ("/launchers/audiocpp/pcm_audio.js", 200),
        ):
            response = requests.get(root + path, timeout=5, allow_redirects=False)
            assert response.status_code == expected, f"{path}: {response.status_code}"
            if expected == 200:
                assert response.content, path
        defaults = requests.get(root + "/proxy/config?model=" + model, timeout=10).json()
        assert any(row["id"] == model and row["installed"] for row in defaults["models"])
        assert defaults["streaming"]["pcm_sample_rate"] == 44100
        assert defaults["instruction_option"] == "instruct"
        reporting.record_inputs(report, frameworks=("audiocpp",), models={"tts": model_cfg.path(model)})
        (run.artifacts / "page-defaults.json").write_text(json.dumps(defaults, indent=2), encoding="utf-8")
        cfg.AUDIOCPP_SERVICE.model = model
        cfg.AUDIOCPP_SERVICE.streaming.pcm_sample_rate = 44100
        path = run.artifacts / "ming-clone-stream.wav"
        result = measure("sse", "Good morning.", 1895, 45, path)
        with wave.open(str(path), "rb") as audio:
            assert audio.getframerate() == 44100 and any(audio.readframes(audio.getnframes()))
        result.update(status="completed", limits="One short clone/SSE request; browser listening quality not graded.")
        report.results.append(result)
        print(
            f"[OK] Ming clone SSE: {result['elapsed_s']:.2f}s, {result['audio_s']:.2f}s audio at 44100 Hz", flush=True
        )


if __name__ == "__main__":
    main()
