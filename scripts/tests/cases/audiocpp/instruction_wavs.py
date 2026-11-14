"""Generate one WAV per tone instruction so the ear can verify audio.cpp
honors per-request "instruction" (overriding the server.json default).

- Uses an already-running audiocpp server when reachable
  - Tries proxy internal port, then the public port
- Otherwise spawns a temporary server on a test port, kills it when done
- WAVs and server logs use the shared test-run output layout.
"""

import json
import urllib.error
import urllib.request

from scripts.benchmarks.shared.reporting import report_run
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.launch_util import (
    backend_running,
    build_cli_args,
    kill_process_tree,
    launch_process,
    wait_for_backend,
)
from scripts.shared.timing import timed
from scripts.tests.shared.paths import CasePaths

TEST_PORT = 18992
PORT_CANDIDATES = (cfg.AUDIOCPP_SERVICE.internal_port, cfg.AUDIOCPP_SERVICE.port, TEST_PORT)

TEXT = "Well, I suppose I didn't see that coming. Let the weird wash over you, man."

INSTRUCTIONS = [
    "Clear, natural speaking tone and delivery.",
    "Whispering softly",
    "Shouting angrily",
    "Fast and excited",
    "Sad and slow, weary",
]


def main() -> None:
    output = CasePaths(__file__).new_run()
    with report_run(output, "audiocpp/instruction_wavs", "audio-probe") as run:
        port = next((p for p in PORT_CANDIDATES if backend_running(p)), None)
        spawned = None
        if port is None:
            port = TEST_PORT
            cmd = [
                str(project_cfg.AUDIOCPP_SERVER_EXE),
                *build_cli_args({**cfg.AUDIOCPP_SERVER_ARGS, "port": port, "model": cfg.AUDIOCPP_SERVICE.model}),
            ]
            print(f"[instruction-wavs] no server found, spawning on {port}")
            log_path = output.logs / "server.log"
            spawned = launch_process(
                cmd,
                "audio.cpp instruction probe",
                cwd=str(project_cfg.AUDIOCPP_BIN_DIR),
                kill_ports=port,
                mode=cfg.ConsoleTerminalLaunchMode.MERGE,
                log_file=str(log_path),
            )
            if not wait_for_backend(port, 240):
                kill_process_tree(spawned.pid)
                spawned.wait(timeout=15)
                raise TimeoutError(f"Audio server did not become ready; see {log_path}")
        else:
            print(f"[instruction-wavs] using running server on {port}")

        try:
            output.artifacts.mkdir(parents=True, exist_ok=True)
            for i, instruction in enumerate(INSTRUCTIONS):
                payload = json.dumps(
                    {"input": TEXT, "model": cfg.AUDIOCPP_SERVICE.model, "options": {"instruction": instruction}}
                ).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/v1/audio/speech",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=300) as resp:
                        audio = resp.read()
                except urllib.error.HTTPError as error:
                    run.status = "failed"
                    detail = error.read().decode("utf-8", "replace")
                    print(f"[FAIL] {instruction!r}: HTTP {error.code}: {detail[:500]}")
                    continue
                name = f"instruction_{i:02d}_{instruction.replace(' ', '_').lower()}.wav"
                (output.artifacts / name).write_bytes(audio)
                print(f"[OK] {name} ({len(audio)} bytes)")
        finally:
            if spawned is not None:
                kill_process_tree(spawned.pid)
                spawned.wait(timeout=15)
                print("[instruction-wavs] temporary server stopped")

        print(f"WAVs written to {output.artifacts} - listen and compare delivery.")


if __name__ == "__main__":
    with timed("audiocpp/instruction_wavs"):
        main()
