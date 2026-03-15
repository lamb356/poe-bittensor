"""Tests for campaign monitor."""
import json
import os
import tempfile
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from monitor import CampaignMetrics, read_logs


class TestCampaignMetrics:
    def test_empty_metrics(self):
        m = CampaignMetrics()
        s = m.summary()
        assert s["tempos"] == 0
        assert s["detection"]["honest_total"] == 0

    def test_honest_metrics(self):
        m = CampaignMetrics()
        m.add_honest(True, 500, 14244, 45)
        m.add_honest(True, 600, 14244, 50)
        m.add_honest(True, 700, 14244, 40)
        s = m.summary()
        assert s["detection"]["honest_total"] == 3
        assert s["detection"]["honest_pass_rate"] == 1.0
        assert s["detection"]["false_positive_rate"] == 0.0

    def test_copier_detection(self):
        m = CampaignMetrics()
        for _ in range(99):
            m.add_copier(True)   # detected
        m.add_copier(False)       # missed
        s = m.summary()
        assert s["detection"]["copier_total"] == 100
        assert s["detection"]["copier_detection_rate"] == 0.99

    def test_percentiles(self):
        m = CampaignMetrics()
        for i in range(100):
            m.add_honest(True, float(i * 10), 14244, 45)
        s = m.summary()
        assert s["proof_generation"]["p50_ms"] == 495.0
        assert 975 < s["proof_generation"]["p99_ms"] < 995


class TestReadLogs:
    def test_read_copier_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "copier_naive_test.jsonl")
            with open(log_file, "w") as f:
                for i in range(10):
                    f.write(json.dumps({
                        "tempo": i,
                        "strategy": "naive",
                        "has_valid_proof": False,
                    }) + "\n")

            metrics = read_logs(tmpdir)
            assert metrics.copier_total == 10
            assert metrics.copier_detected == 10  # All detected (no valid proof)

    def test_read_honest_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "honest_validator_1.jsonl")
            with open(log_file, "w") as f:
                for i in range(5):
                    f.write(json.dumps({
                        "tempo": i,
                        "has_valid_proof": True,
                        "proof_gen_time_ms": 500,
                        "proof_size_bytes": 14244,
                        "verify_time_ms": 45,
                    }) + "\n")

            metrics = read_logs(tmpdir)
            assert metrics.honest_total == 5
            assert metrics.honest_passed == 5
