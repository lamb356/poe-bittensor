import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PoEConfig:
    circuit_dir: str = ""
    commitment_helper_dir: str = ""
    witness_binary: str = ""
    nargo_binary: str = "nargo"
    bb_binary: str = "bb"
    storage_dir: str = ""
    num_miners: int = 64
    max_response_bytes: int = 1_048_576  # 1MB

    @classmethod
    def from_poe_root(
        cls,
        poe_root: str,
        storage_dir: str = "/tmp/poe-proofs",
        build_mode: str = "debug",
        **kwargs,
    ):
        root = Path(poe_root)
        return cls(
            circuit_dir=str(root / "poe_circuit"),
            commitment_helper_dir=str(root / "commitment_helper"),
            witness_binary=str(
                root / "poe-witness" / "target" / build_mode / "poe-witness"
            ),
            nargo_binary=shutil.which("nargo") or "nargo",
            bb_binary=shutil.which("bb") or "bb",
            storage_dir=storage_dir,
            **kwargs,
        )
