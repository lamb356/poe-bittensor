"""Structured JSONL telemetry for PoE testnet campaigns."""
from __future__ import annotations

import json
import os
import time


class TelemetryLogger:
    """Append-only JSONL logger for structured telemetry.

    Each log entry is a single JSON line with an auto-added timestamp.
    Used by miners, validators, and copier agents to emit data that
    monitor.py consumes for campaign reporting.
    """

    def __init__(self, log_dir: str, name: str):
        os.makedirs(log_dir, exist_ok=True)
        self._path = os.path.join(log_dir, f"{name}.jsonl")
        self._file = open(self._path, "a")

    def log(self, **kwargs) -> None:
        """Write one JSONL entry with auto-added timestamp."""
        kwargs["timestamp"] = time.time()
        self._file.write(json.dumps(kwargs) + "\n")
        self._file.flush()

    def close(self) -> None:
        """Close the underlying file."""
        self._file.close()

    @property
    def path(self) -> str:
        return self._path
