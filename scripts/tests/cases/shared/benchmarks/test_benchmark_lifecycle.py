"""The timing contract is shared by ASR, TTS, LLM and image adapters."""

import unittest

from scripts.benchmarks.shared.benchmark import (
    BenchmarkContractError,
    BenchmarkLifecycle,
    summarize_report,
    summarize_requests,
)


class BenchmarkLifecycleTests(unittest.TestCase):
    now: float = 0.0
    identity: str = ""
    cleaned: bool = False

    def setUp(self):
        self.now = 0.0
        self.identity = "loaded-model:pid-1"
        self.cleaned = False

    def advance(self, duration):
        self.now += duration
        return "result"

    def cleanup(self):
        self.cleaned = True
        self.advance(50)

    def lifecycle(self, resident=True):
        return BenchmarkLifecycle(lambda: self.identity, self.cleanup, resident=resident, clock=lambda: self.now)

    def test_request_excludes_startup_load_warmup_and_cleanup(self):
        with self.lifecycle() as timer:
            timer.prepare(lambda: self.advance(10), lambda: self.advance(20))
            timer.warmup(lambda: self.advance(30))
            result, row = timer.measure(lambda: self.advance(2))
        self.assertEqual(result, "result")
        self.assertEqual(row["request_seconds"], 2)
        self.assertEqual(timer.record()["startup_seconds"], 10)
        self.assertEqual(timer.record()["model_load_seconds"], 20)
        self.assertEqual(timer.record()["warmup_seconds"], 30)
        self.assertTrue(self.cleaned)

    def test_combined_load_is_explicit_and_not_fabricated(self):
        with self.lifecycle() as timer:
            timer.prepare(lambda: self.advance(7), combined=True)
            data = timer.record()
        self.assertIsNone(data["startup_seconds"])
        self.assertIsNone(data["model_load_seconds"])
        self.assertEqual(data["startup_and_model_load_seconds"], 7)

    def test_cold_or_nonresident_requests_cannot_be_ranked(self):
        for resident in (True, False):
            with self.lifecycle(resident) as timer:
                timer.prepare(lambda: None)
                with self.assertRaises(BenchmarkContractError):
                    timer.measure(lambda: None)
                timer.warmup(lambda: None)
                if not resident:
                    with self.assertRaises(BenchmarkContractError):
                        timer.measure(lambda: None)

    def test_identity_change_invalidates_measurement(self):
        with self.lifecycle() as timer:
            timer.prepare(lambda: None)
            timer.warmup(lambda: None)
            with self.assertRaises(BenchmarkContractError), timer.request():
                self.identity = "new-process"
        self.assertEqual(timer.requests[0]["status"], "failed")
        self.assertEqual(summarize_requests(timer.requests)["samples"], 0)

    def test_failed_setup_still_cleans_up(self):
        with self.assertRaisesRegex(ValueError, "load failed"), self.lifecycle() as timer:
            timer.prepare(lambda: None, lambda: (_ for _ in ()).throw(ValueError("load failed")))
        self.assertTrue(self.cleaned)

    def test_first_output_marks_use_request_clock(self):
        with self.lifecycle() as timer:
            timer.prepare(lambda: None)
            timer.warmup(lambda: None)
            with timer.request() as request:
                self.advance(0.2)
                request.mark("first_output")
                self.advance(0.8)
        self.assertEqual(timer.requests[0]["marks_seconds"], {"first_output": 0.2})

    def test_summary_rejects_legacy_wall_times_and_small_p95(self):
        data = summarize_requests(
            [{"seconds": 100}, {"request_seconds": 2, "status": "completed", "timing_scope": "resident_request"}]
        )
        self.assertEqual(data["samples"], 1)
        self.assertEqual(data["excluded_rows"], 1)
        self.assertIsNone(data["p95_seconds"])

    def test_report_uses_lifecycle_once_and_ignores_legacy_metrics(self):
        with self.lifecycle() as timer:
            timer.prepare(lambda: None)
            timer.warmup(lambda: None)
            _, row = timer.measure(lambda: self.advance(2))
        result = summarize_report([{"benchmark": timer.record(), "samples": [row]}, {"seconds": 400}])
        self.assertEqual(result["samples"], 1)
        self.assertEqual(result["p50_seconds"], 2)

    def test_nonfinite_failed_and_negative_samples_cannot_rank(self):
        rows = [
            {"timing_scope": "resident_request", "status": "completed", "request_seconds": value}
            for value in (float("nan"), float("inf"), -1, True)
        ]
        self.assertEqual(summarize_requests(rows)["samples"], 0)

    def test_new_timed_sources_must_use_shared_contract_or_be_reviewed(self):
        from scripts.benchmarks.audit_timing import inventory

        self.assertEqual([row["source"] for row in inventory() if row["scope"] == "UNREVIEWED"], [])

    def test_identity_verification_cost_is_outside_request_time(self):
        def identity():
            self.advance(5)
            return "resident"

        with BenchmarkLifecycle(identity, clock=lambda: self.now) as timer:
            timer.prepare(lambda: None)
            timer.warmup(lambda: None)
            _, timing = timer.measure(lambda: self.advance(2))
        self.assertEqual(timing["request_seconds"], 2)

    def test_backend_error_response_cannot_rank_as_a_success(self):
        with self.lifecycle() as timer:
            timer.prepare(lambda: None)
            timer.warmup(lambda: None)
            value, timing = timer.measure(lambda: {"error": "unsupported"}, accept=lambda row: "error" not in row)
        self.assertEqual(value["error"], "unsupported")
        self.assertEqual(timing["status"], "failed")
        self.assertEqual(summarize_requests(timer.requests)["samples"], 0)

    def test_concurrent_recorders_inherit_warmup_without_repeating_model_load(self):
        with self.lifecycle() as parent:
            parent.prepare(lambda: self.advance(10))
            parent.warmup(lambda: self.advance(20))
            first, second = parent.fork(), parent.fork()
            with first.request():
                _, result = second.measure(lambda: self.advance(2))
            self.assertEqual(result["request_seconds"], 2)
            self.assertEqual(first.prepared_identity, parent.prepared_identity)
            self.assertEqual(second.record()["warmup_seconds"], 0)
            self.assertEqual(len(parent.requests), 0)

    def test_session_acquisition_does_not_invent_original_startup_or_load_time(self):
        with self.lifecycle() as timer:
            timer.adopt_prepared(3, acquisition=True)
        record = timer.record()
        self.assertEqual(record["session_acquisition_seconds"], 3)
        self.assertIsNone(record["startup_seconds"])
        self.assertIsNone(record["model_load_seconds"])
        self.assertIsNone(record["startup_and_model_load_seconds"])

    def test_cold_process_and_dynamic_pipeline_totals_never_rank_as_inference(self):
        from scripts.benchmarks.shared.benchmark import measure_cold_process, workflow_timing

        _, cold = measure_cold_process(lambda: "done")
        with workflow_timing() as pipeline:
            pass
        self.assertEqual(summarize_requests([cold, pipeline])["samples"], 0)
        self.assertIsNone(cold["model_load_seconds"])
        self.assertIsNone(pipeline["request_seconds"])

    def test_audio_identity_tracks_model_changes_but_not_mutable_tone_state(self):
        from scripts.shared.service_identity import audio_model_token

        config = {"model": "breeze", "selected_model": "breeze", "server_session_options": {}}
        token = audio_model_token(config)
        self.assertEqual(token, audio_model_token({**config, "proxy_defaults": {"instruction": "gentle"}}))
        self.assertNotEqual(token, audio_model_token({**config, "selected_model": "ming"}))


if __name__ == "__main__":
    unittest.main()
