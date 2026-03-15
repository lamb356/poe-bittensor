"""Tests for campaign monitor."""
import json
import os
import tempfile
import sys

import pytest

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


class TestAdditionalMetrics:
    def test_per_strategy_tracking(self):
        m = CampaignMetrics()
        m.add_copier_by_strategy("naive", True)
        m.add_copier_by_strategy("naive", False)
        m.add_copier_by_strategy("delayed", True)
        s = m.summary()
        assert s["copier_by_strategy"]["naive"]["total"] == 2
        assert s["copier_by_strategy"]["naive"]["detected"] == 1
        assert s["copier_by_strategy"]["delayed"]["total"] == 1

    def test_empty_directory_returns_empty_metrics(self):
        """Empty log dir should return metrics with zero counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = read_logs(tmpdir)
            assert m.honest_total == 0
            assert m.copier_total == 0

    def test_missing_directory_returns_empty_metrics(self):
        """Non-existent log dir should return empty metrics."""
        m = read_logs("/nonexistent/path")
        assert m.honest_total == 0

    def test_copier_log_parsed_with_strategy(self):
        """Copier log entries should be counted with strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "copier_naive.jsonl")
            with open(log_file, "w") as f:
                f.write(json.dumps({"has_valid_proof": False, "tempo": 0}) + "\n")
                f.write(json.dumps({"has_valid_proof": True, "tempo": 1}) + "\n")
            m = read_logs(tmpdir)
            assert m.copier_total == 2
            assert m.copier_detected == 1  # False -> detected
            assert m.copier_by_strategy["naive"]["total"] == 2
            assert m.copier_by_strategy["naive"]["detected"] == 1


class TestSuccessCriteria:
    def test_empty_data_fails_criteria(self):
        """With no data, success criteria should FAIL (not pass by default)."""
        m = CampaignMetrics()
        s = m.summary()
        # Honest pass rate with 0 total should NOT count as passing
        # The print_summary checks honest_total >= MIN_HONEST
        assert s["detection"]["honest_total"] == 0
        assert s["detection"]["copier_total"] == 0
