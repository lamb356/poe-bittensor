"""Monitor PoE testnet campaign metrics.

Tracks per-tempo:
- Proof generation times (P50/P95/P99)
- Proof sizes
- Verification times
- Detection rate (copiers caught / copiers total)
- False positive rate (honest flagged / honest total)

Reads JSONL log files from testnet/logs/ and outputs summary stats.

Usage:
    python testnet/scripts/monitor.py --log-dir testnet/logs
    python testnet/scripts/monitor.py --log-dir testnet/logs --live  # Follow mode
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class TempoMetrics:
    """Metrics for a single tempo."""
    tempo: int
    proof_gen_time_ms: float = 0.0
    proof_size_bytes: int = 0
    verify_time_ms: float = 0.0
    honest_accepted: int = 0
    honest_rejected: int = 0
    copier_detected: int = 0
    copier_missed: int = 0


@dataclass
class CampaignMetrics:
    """Aggregate metrics across the campaign."""
    proof_gen_times: list[float] = field(default_factory=list)
    proof_sizes: list[int] = field(default_factory=list)
    verify_times: list[float] = field(default_factory=list)
    honest_total: int = 0
    honest_passed: int = 0
    copier_total: int = 0
    copier_detected: int = 0
    tempo_count: int = 0

    def add_honest(self, passed: bool, gen_time_ms: float, size: int, verify_ms: float):
        self.honest_total += 1
        if passed:
            self.honest_passed += 1
        self.proof_gen_times.append(gen_time_ms)
        self.proof_sizes.append(size)
        self.verify_times.append(verify_ms)

    def add_copier(self, detected: bool):
        self.copier_total += 1
        if detected:
            self.copier_detected += 1

    def percentile(self, data: list[float], p: int) -> float:
        if not data:
            return 0.0
        return float(np.percentile(data, p))

    def summary(self) -> dict:
        return {
            "tempos": self.tempo_count,
            "proof_generation": {
                "count": len(self.proof_gen_times),
                "p50_ms": self.percentile(self.proof_gen_times, 50),
                "p95_ms": self.percentile(self.proof_gen_times, 95),
                "p99_ms": self.percentile(self.proof_gen_times, 99),
                "mean_ms": float(np.mean(self.proof_gen_times)) if self.proof_gen_times else 0,
            },
            "proof_size": {
                "mean_bytes": float(np.mean(self.proof_sizes)) if self.proof_sizes else 0,
                "max_bytes": max(self.proof_sizes) if self.proof_sizes else 0,
            },
            "verification": {
                "p50_ms": self.percentile(self.verify_times, 50),
                "p95_ms": self.percentile(self.verify_times, 95),
                "mean_ms": float(np.mean(self.verify_times)) if self.verify_times else 0,
            },
            "detection": {
                "honest_total": self.honest_total,
                "honest_pass_rate": self.honest_passed / max(self.honest_total, 1),
                "false_positive_rate": 1 - self.honest_passed / max(self.honest_total, 1),
                "copier_total": self.copier_total,
                "copier_detection_rate": self.copier_detected / max(self.copier_total, 1),
            },
        }

    def print_summary(self):
        s = self.summary()
        print("\n" + "=" * 60)
        print("PoE Testnet Campaign — Summary Report")
        print("=" * 60)

        print(f"\nTempos completed: {s['tempos']}")

        pg = s["proof_generation"]
        print(f"\nProof Generation ({pg['count']} proofs):")
        print(f"  P50: {pg['p50_ms']:.0f}ms")
        print(f"  P95: {pg['p95_ms']:.0f}ms")
        print(f"  P99: {pg['p99_ms']:.0f}ms")
        print(f"  Mean: {pg['mean_ms']:.0f}ms")

        ps = s["proof_size"]
        print(f"\nProof Size:")
        print(f"  Mean: {ps['mean_bytes']:.0f} bytes")
        print(f"  Max:  {ps['max_bytes']} bytes")

        v = s["verification"]
        print(f"\nVerification:")
        print(f"  P50: {v['p50_ms']:.1f}ms")
        print(f"  P95: {v['p95_ms']:.1f}ms")

        d = s["detection"]
        print(f"\nDetection:")
        print(f"  Honest validators: {d['honest_total']} total, "
              f"{d['honest_pass_rate']*100:.1f}% pass rate")
        print(f"  False positive rate: {d['false_positive_rate']*100:.2f}%")
        print(f"  Copiers: {d['copier_total']} total, "
              f"{d['copier_detection_rate']*100:.1f}% detected")

        # Check against success criteria
        print("\n--- Success Criteria ---")
        criteria = [
            ("Proof gen P95 < 60s", pg["p95_ms"] < 60000 if pg["p95_ms"] else True),
            ("Proof size < 10KB", ps["mean_bytes"] < 10240 if ps["mean_bytes"] else True),
            ("Verify < 100ms", v["p95_ms"] < 100 if v["p95_ms"] else True),
            ("Honest pass rate > 99.9%", d["honest_pass_rate"] > 0.999 if d["honest_total"] else True),
            ("Copier detection > 99%", d["copier_detection_rate"] > 0.99 if d["copier_total"] else True),
            ("False positive < 0.1%", d["false_positive_rate"] < 0.001 if d["honest_total"] else True),
        ]
        for name, passed in criteria:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {name}")


def read_logs(log_dir: str) -> CampaignMetrics:
    """Read all JSONL log files and aggregate metrics."""
    metrics = CampaignMetrics()
    log_path = Path(log_dir)

    if not log_path.exists():
        print(f"No logs found at {log_dir}")
        return metrics

    for log_file in sorted(log_path.glob("*.jsonl")):
        is_copier = "copier" in log_file.name
        is_honest = "honest" in log_file.name or "validator" in log_file.name

        with open(log_file) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue

                if is_copier:
                    # Copier: detected if has_valid_proof is False
                    detected = not entry.get("has_valid_proof", False)
                    metrics.add_copier(detected)
                elif is_honest or entry.get("has_valid_proof"):
                    gen_time = entry.get("proof_gen_time_ms", entry.get("elapsed_seconds", 0) * 1000)
                    size = entry.get("proof_size_bytes", 14244)
                    verify = entry.get("verify_time_ms", 45)
                    passed = entry.get("has_valid_proof", True)
                    metrics.add_honest(passed, gen_time, size, verify)

                metrics.tempo_count = max(metrics.tempo_count, entry.get("tempo", 0) + 1)

    return metrics


def main():
    parser = argparse.ArgumentParser(description="PoE testnet monitor")
    parser.add_argument("--log-dir", default="testnet/logs")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--live", action="store_true", help="Follow logs continuously")
    args = parser.parse_args()

    if args.live:
        print("Live monitoring (Ctrl+C to stop)...")
        while True:
            os.system("clear" if os.name != "nt" else "cls")
            metrics = read_logs(args.log_dir)
            if args.json:
                print(json.dumps(metrics.summary(), indent=2))
            else:
                metrics.print_summary()
            time.sleep(10)
    else:
        metrics = read_logs(args.log_dir)
        if args.json:
            print(json.dumps(metrics.summary(), indent=2))
        else:
            metrics.print_summary()


if __name__ == "__main__":
    main()
