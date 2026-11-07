"""Repeatable operator, tensor, generation and source checks for an HRX candidate."""

import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.download.frameworks.update_config import hrx_tools
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.benchmarks.llamacpp.hrx import hrx_tensor_probe as probe
from scripts.tests.shared.paths import RunPaths

# - Retained CPU/native golden captures for the fixed Swift model/prompt used by these probes.
REFERENCE = project_cfg.TEST_OUTPUT_DIR / "probes/hrx_performance/inconclusive/20261010-fusion-routing"
PERFORMANCE_REFERENCE = (
    project_cfg.TEST_OUTPUT_DIR / "probes/hrx_performance/unreviewed/1791676838425086600/artifacts/results.json"
)


def build_operator_probe(paths: RunPaths) -> Path:
    source = (probe.LLAMA_SOURCE / "tests/test-backend-ops.cpp").read_text(encoding="utf-8")
    start = source.index("static std::vector<std::unique_ptr<test_case>> make_test_cases_eval() {")
    end = source.index("    return test_cases;", start) + len("    return test_cases;\n}")
    replacement = Path(__file__).with_name("hrx_affected_ops.inc").read_text(encoding="utf-8")
    patched = paths.temp / "affected-ops.cpp"
    patched.write_text(source[:start] + replacement + source[end:], encoding="utf-8")
    directory = probe.HRX_ROOT / "build/llamacpp/tests"
    ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
    tree = ET.parse(directory / "test-backend-ops.vcxproj")
    group = next(g for g in tree.findall("m:ItemDefinitionGroup", ns) if "'Release|x64'" in g.get("Condition", ""))

    def fields(query: str) -> list[str]:
        element = group.find(query, ns)
        if element is None or element.text is None:
            raise RuntimeError(f"Missing generated MSVC setting: {query}")
        return [value for value in element.text.split(";") if not value.startswith("%")]

    includes = fields("m:ClCompile/m:AdditionalIncludeDirectories")
    defines = [
        value for value in fields("m:ClCompile/m:PreprocessorDefinitions") if not value.startswith("CMAKE_INTDIR")
    ]
    libraries = fields("m:Link/m:AdditionalDependencies")
    compiler, env = probe.native_build_environment()
    output = paths.temp / "bin/affected-ops.exe"
    command = [
        str(compiler),
        "/nologo",
        "/std:c++17",
        "/EHsc",
        "/MD",
        "/O2",
        *("/I" + value for value in includes),
        "/I" + str(probe.LLAMA_SOURCE / "tests"),
        *("/D" + value for value in defines),
        str(patched),
        "/Fo:" + str(paths.temp / "bin/affected-ops.obj"),
        "/Fe:" + str(output),
        "/link",
        *libraries,
    ]
    with (paths.logs / "build-ops.log").open("w", encoding="utf-8") as log:
        subprocess.run(command, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    return output


def validate_candidate(paths: RunPaths) -> None:
    if launch_util.llama_server_running() or any(launch_util.backend_running(port) for port in (9950, 9951)):
        raise RuntimeError("A llama-server/probe port is occupied; confirm session safety before validation")
    candidate = paths.temp / "bin"
    operator = build_operator_probe(paths)
    env = os.environ.copy()
    env.update(
        ROCR_VISIBLE_DEVICES="1", ROCR_USE_PM4="1", IREE_HAL_AMDGPU_LIBHSA_PATH=str(candidate / "hsa-runtime64.dll")
    )
    env.pop("HSA_OVERRIDE_GFX_VERSION", None)
    with (paths.logs / "affected-ops.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [str(operator), "test", "-b", "HRX0"],
            cwd=candidate,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=180,
        )
    if "6/6 tests passed" not in (paths.logs / "affected-ops.log").read_text(encoding="utf-8"):
        raise RuntimeError("The six affected operator cases did not all pass")
    evidence: list[dict[str, Any]] = [{"check": "affected-ops.log", "exit_code": 0}]
    print("[OK] Six CPU-reference operators", flush=True)
    for chunk in (None, 3):
        folder = paths.artifacts / f"tensors-latest-{chunk}"
        result = probe.run(
            candidate / "hrx-tensor-probe.exe",
            folder,
            "HRX0",
            "l_out-(0|15|31|47|63)",
            "int add(int a, int b) { return",
            chunk,
        )
        if result["exit_code"]:
            raise RuntimeError(f"Tensor capture failed: chunk={chunk}")
        evidence.append(
            {
                "chunk": chunk,
                "cpu_reference": probe.compare(REFERENCE / f"artifacts/tensors-cpu-{chunk}", folder),
                "previous_checkpoint": probe.compare(REFERENCE / f"artifacts/tensors-no-publish-{chunk}", folder),
            }
        )
        print(f"[OK] Tensor capture: chunk={chunk}", flush=True)
    probe.server_smoke(candidate / "hrx-tensor-probe.exe", paths, "HRX0", 32, runtime=candidate)
    code = json.loads((paths.artifacts / "code-response.json").read_text(encoding="utf-8"))
    chat = json.loads((paths.artifacts / "chat-response.json").read_text(encoding="utf-8"))
    evidence.append(
        {
            "smoke_run": str(paths.root),
            "code_tokens": code["tokens"],
            "code": code["content"],
            "chat": chat["choices"][0]["message"]["content"].strip(),
        }
    )
    (paths.artifacts / "correctness.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    verify_candidate_evidence(paths)


def verify_candidate_evidence(paths: RunPaths) -> dict[str, Any]:
    evidence = json.loads((paths.artifacts / "correctness.json").read_text(encoding="utf-8"))
    for chunk in (None, 3):
        record = next(record for record in evidence if "chunk" in record and record["chunk"] == chunk)
        previous = probe.compare(
            REFERENCE / f"artifacts/tensors-cpu-{chunk}", REFERENCE / f"artifacts/tensors-no-publish-{chunk}"
        )
        rows = record["cpu_reference"]
        if len(rows) != len(previous) or len(rows) < 3:
            raise RuntimeError(f"Incomplete tensor comparison: chunk={chunk}")
        for old, new in zip(previous, rows, strict=True):
            if new.get("status") == "missing" or not new.get("finite", True):
                raise RuntimeError(f"Missing/nonfinite tensor: {new}")
            if new["tensor"] == "logits" and (
                new["reference_top"] != new["actual_top"] or new["max_abs"] > old["max_abs"] + 0.05
            ):
                raise RuntimeError(f"Logit regression: {new}")
    golden = json.loads((REFERENCE / "artifacts/correctness-no-publish.json").read_text(encoding="utf-8"))[-1]
    smoke = evidence[-1]
    if smoke["code_tokens"] != golden["code_tokens"] or smoke["code"] != golden["code"] or smoke["chat"] != "OK":
        raise RuntimeError("Code tokens/text or chat differs from the retained reference")
    if "6/6 tests passed" not in (paths.logs / "affected-ops.log").read_text(encoding="utf-8"):
        raise RuntimeError("Operator results are incomplete")
    run, result = load_performance(paths.logs / "performance.log")
    baseline = json.loads(PERFORMANCE_REFERENCE.read_text(encoding="utf-8"))
    speeds = verify_generation(result, baseline)
    hashes = json.loads((paths.artifacts / "candidate-binaries.json").read_text(encoding="utf-8"))
    for name, expected in hashes.items():
        with (paths.temp / "bin" / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected or result["hashes"].get(name) != expected:
                raise RuntimeError(f"Validated candidate binary changed: {name}")
    if launch_util.llama_server_running() or any(launch_util.backend_running(port) for port in (9950, 9951)):
        raise RuntimeError("Probe server cleanup is incomplete")
    checks = {
        "performance_run": str(run),
        "speeds": speeds,
        "exact_code_match": True,
        "cleanup_port_clear": True,
        "affected_ops_passed": 6,
        "hashes": hashes,
    }
    (paths.artifacts / "final-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    return checks


def load_performance(log: Path) -> tuple[Path, dict[str, Any]]:
    match = re.search(r"\[OUTPUT\] (.+)", log.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError("Performance run evidence is missing")
    run = Path(match[1].strip())
    result = json.loads((run / "artifacts/results.json").read_text(encoding="utf-8"))
    return run, result


def verify_generation(result: dict[str, Any], baseline: dict[str, Any]) -> list[float]:
    for index in (1, 2):
        for field in ("tokens", "content"):
            if result["requests"][index]["response"][field] != baseline["requests"][index]["response"][field]:
                raise RuntimeError("Short generation output differs from the retained reference")
    speeds = [result["requests"][i]["response"]["timings"]["predicted_per_second"] for i in (1, 2)]
    if sum(speeds) / 2 < 0.9 * 14.686 or not result["cleanup_port_clear"]:
        raise RuntimeError(f"Performance/cleanup regression: {speeds}")
    return speeds


def verify_installed_runtime(paths: RunPaths) -> dict[str, Any]:
    run, installed = load_performance(paths.logs / "installed-performance.log")
    _, candidate = load_performance(paths.logs / "performance.log")
    speeds = verify_generation(installed, candidate)
    hashes = json.loads((paths.artifacts / "binaries.json").read_text(encoding="utf-8"))
    runtime = cfg.LLAMACPP_BUILDS["hrx"].bin_dir
    for name, expected in hashes.items():
        with (runtime / name).open("rb") as stream:
            if (
                hashlib.file_digest(stream, "sha256").hexdigest() != expected
                or installed["hashes"].get(name) != expected
            ):
                raise RuntimeError(f"Installed binary differs from validated candidate: {name}")
    if launch_util.llama_server_running() or any(launch_util.backend_running(port) for port in (9950, 9951)):
        raise RuntimeError("Probe server cleanup is incomplete")
    record = {
        "runtime": str(runtime),
        "performance_run": str(run),
        "speeds": speeds,
        "sha256_match": True,
        "file_count": len(hashes),
        "code_tokens_match_candidate": True,
        "owned_ports_clear": True,
    }
    (paths.artifacts / "installed-validation.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def record_sources(paths: RunPaths) -> None:
    records = []
    for tool in hrx_tools():
        source = project_cfg.FRAMEWORKS_DIR / tool.name
        command = ["git", "-c", f"safe.directory={source.as_posix()}", "-C", str(source)]
        upstream = "origin/" + tool.branch
        subprocess.run([*command, "merge-base", "--is-ancestor", upstream, "HEAD"], check=True)
        status = subprocess.check_output([*command, "status", "--porcelain"], text=True).strip()
        if status:
            raise RuntimeError(f"Commit source changes before checkpointing: {source}")
        patch = subprocess.check_output([*command, "diff", "--binary", upstream])
        (paths.artifacts / f"{source.name}.patch").write_bytes(patch)
        records.append(
            {
                "repository": source.name,
                "head": subprocess.check_output([*command, "rev-parse", "HEAD"], text=True).strip(),
                "upstream": subprocess.check_output([*command, "rev-parse", upstream], text=True).strip(),
                "status": status,
                "patch_sha256": hashlib.sha256(patch).hexdigest(),
            }
        )
    (paths.artifacts / "rebuilt-sources.json").write_text(json.dumps({"sources": records}, indent=2), encoding="utf-8")
