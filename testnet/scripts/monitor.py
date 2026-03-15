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
    copier_by_strategy: dict[str, dict] = field(default_factory=lambda: {})

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

    def add_copier_by_strategy(self, strategy: str, detected: bool):
        if strategy not in self.copier_by_strategy:
            self.copier_by_strategy[strategy] = {"total": 0, "detected": 0}
        self.copier_by_strategy[strategy]["total"] += 1
        if detected:
            self.copier_by_strategy[strategy]["detected"] += 1

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
            "copier_by_strategy": {
                k: {"total": v["total"], "detected": v["detected"],
                    "detection_rate": v["detected"] / max(v["total"], 1)}
                for k, v in self.copier_by_strategy.items()
            },
        }

    def print_summary(self):
        s = self.summary()
        print("\n" + "=" * 60)
        print("PoE Testnet Campaign \u2014 Summary Report")
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

        # Per-strategy copier metrics
        if self.copier_by_strategy:
            print("\n--- Per-Strategy Detection ---")
            for strategy, data in sorted(self.copier_by_strategy.items()):
                rate = data["detected"] / max(data["total"], 1) * 100
                print(f"  {strategy}: {data['detected']}/{data['total']} detected ({rate:.1f}%)")

        # Check against success criteria with minimum sample requirements
        print("\n--- Success Criteria ---")
        MIN_HONEST = 10
        MIN_COPIER = 10
        criteria = [
            ("Proof gen P95 < 60s", pg["p95_ms"] < 60000 if pg["count"] >= MIN_HONEST else False),
            ("Proof size < 10KB", ps["mean_bytes"] < 10240 if pg["count"] >= MIN_HONEST else False),
            ("Verify < 100ms", v["p95_ms"] < 100 if pg["count"] >= MIN_HONEST else False),
            ("Honest pass rate > 99.9%", d["honest_pass_rate"] > 0.999 if d["honest_total"] >= MIN_HONEST else False),
            ("Copier detection > 99%", d["copier_detection_rate"] > 0.99 if d["copier_total"] >= MIN_COPIER else False),
            ("False positive < 0.1%", d["false_positive_rate"] < 0.001 if d["honest_total"] >= MIN_HONEST else False),
            ("Minimum honest samples", d["honest_total"] >= MIN_HONEST),
            ("Minimum copier samples", d["copier_total"] >= MIN_COPIER),
        ]
        for name, passed in criteria:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {name}")


def read_logs(log_dir: str) -> CampaignMetrics:
    """Read all JSONL log files and aggregate metrics."""
    metrics = CampaignMetrics()
    log_path = Path(log_dir)

    if not log_path.exists():
        print(f"WARNING: Log directory not found: {log_dir}")
        return metrics

    log_files = sorted(log_path.glob("*.jsonl"))
    if not log_files:
        print(f"WARNING: No .jsonl log files found in {log_dir}")
        return metrics

    for log_file in log_files:
        is_copier = "copier" in log_file.name
        is_honest = "honest" in log_file.name or "validator" in log_file.name

        # Extract strategy from filename like "copier_naive.jsonl"
        strategy = "unknown"
        if "naive" in log_file.name:
            strategy = "naive"
        elif "delayed" in log_file.name:
            strategy = "delayed"
        elif "partial" in log_file.name:
            strategy = "partial"

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
                    metrics.add_copier_by_strategy(strategy, detected)
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
