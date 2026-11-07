"""Check that performance runners use the shared timing contract or are classified."""

import json

from scripts.config import project_config as cfg

LEGACY_SCOPES = {
    "koboldcpp/drama3_kobold_compare.py": "deferred by user; migration pending",
    "koboldcpp/kobold_stack_vram.py": "resource/integration probe",
    "llamacpp/hrx/hrx_performance.py": "disabled HRX benchmark, phase import pending",
    "llamacpp/hrx/hrx_tensor_probe.py": "disabled HRX kernel probe",
    "asr/audiocpp_drama3_offload.py": "deferred resource probe",
    "coding_agents/harness_requests.py": "interactive coding-task request capture",
    "inference_engines/benchmark_strata_avalon.py": "paired native-timing screen; both arms report their own server timings",
    "amalgamate_benchmarks.py": "historical artifact aggregation",
}

DELEGATES = {
    "coding_agents/shared/benchmark_backends.py": "Managed setup imported by the shared coding-agent API benchmark",
    "coding_agents/shared/framework_tasks.py": "Task definitions shared by benchmark runners and regression checks",
    "personal/sdcpp/sdcpp_memory_compare.py": "Delegates setup and requests to the sd.cpp backend comparison",
    "inference_engines/engines/base.py": "Normalized result contract; no timing implementation",
}


def inventory() -> list[dict[str, str]]:
    root = cfg.SCRIPTS_DIR / "benchmarks"
    rows = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "audit_timing.py" or path.relative_to(root).parts[0] == "shared":
            continue
        text = path.read_text(encoding="utf-8")
        if path.name.startswith("test_") or not any(
            word in text
            for word in (
                "perf_counter(",
                "monotonic(",
                "tokens_per_second",
                "real_time_factor",
                "BenchmarkLifecycle",
                "ResidentHttp",
                "measure_cold_process",
            )
        ):
            continue
        shared = (
            "from scripts.benchmarks.shared.benchmark import" in text
            or "from scripts.benchmarks.shared.resident_http import" in text
        )
        source = path.relative_to(root).as_posix()
        diagnostic = "measure_cold_process" in text or "workflow_timing" in text
        contract = (
            "shared-diagnostic"
            if shared and diagnostic
            else "shared-lifecycle"
            if shared
            else "shared-delegate"
            if source in DELEGATES
            else "legacy-or-functional"
        )
        rows.append(
            {
                "source": source,
                "contract": contract,
                "scope": "Whole process/workflow; loading split unobservable"
                if shared and diagnostic
                else "resident request contract"
                if shared
                else DELEGATES.get(source, LEGACY_SCOPES.get(source, "UNREVIEWED")),
                "ranking": "requires completed resident_request rows"
                if contract in ("shared-lifecycle", "shared-delegate")
                else "excluded; loading split unavailable"
                if diagnostic and shared
                else "excluded; functional/deferred/disabled probe",
            }
        )
    return rows


def main():
    print(json.dumps(inventory(), indent=2))


if __name__ == "__main__":
    main()
