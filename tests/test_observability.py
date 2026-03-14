from __future__ import annotations

import logging
import unittest

from runtime.observability import ObservabilityManager, SLOTargets


class ObservabilityTests(unittest.TestCase):
    def _build_manager(self) -> ObservabilityManager:
        return ObservabilityManager(
            logger=logging.getLogger("amaryllis.tests.observability"),
            service_name="amaryllis-test",
            service_version="0.0-test",
            environment="test",
            otel_enabled=False,
            otlp_endpoint=None,
            slo_targets=SLOTargets(
                window_sec=60.0,
                request_availability_target=0.95,
                request_latency_p95_ms_target=100.0,
                run_success_target=0.9,
                min_request_samples=5,
                min_run_samples=3,
                incident_cooldown_sec=1.0,
            ),
        )

    def test_sre_snapshot_and_prometheus_metrics(self) -> None:
        manager = self._build_manager()
        for _ in range(5):
            manager.sre.record_http(
                method="GET",
                path="/models",
                status_code=200,
                duration_ms=40.0,
            )
        for _ in range(3):
            manager.sre.record_run_terminal(status="succeeded")

        snapshot = manager.sre.snapshot()
        self.assertIn("sli", snapshot)
        self.assertGreaterEqual(float(snapshot["sli"]["requests"]["availability"]), 0.99)
        self.assertGreaterEqual(float(snapshot["sli"]["runs"]["success_rate"]), 0.99)

        metrics = manager.sre.render_prometheus_metrics()
        self.assertIn("amaryllis_request_availability_ratio", metrics)
        self.assertIn("amaryllis_run_success_ratio", metrics)

    def test_incident_is_detected_when_slo_is_breached(self) -> None:
        manager = self._build_manager()
        # Breach request availability and latency SLO.
        for _ in range(3):
            manager.sre.record_http(
                method="GET",
                path="/models",
                status_code=500,
                duration_ms=250.0,
            )
        for _ in range(3):
            manager.sre.record_http(
                method="GET",
                path="/models",
                status_code=200,
                duration_ms=250.0,
            )
        # Breach run success SLO.
        manager.sre.record_run_terminal(status="failed")
        manager.sre.record_run_terminal(status="failed")
        manager.sre.record_run_terminal(status="succeeded")

        incidents = manager.sre.list_incidents(limit=50)
        self.assertGreaterEqual(len(incidents), 1)
        incident_types = {str(item.get("type")) for item in incidents}
        self.assertTrue(
            bool({"request_availability", "request_latency_p95", "run_success_rate"} & incident_types)
        )


if __name__ == "__main__":
    unittest.main()

