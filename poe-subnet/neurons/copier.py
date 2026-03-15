"""PoE Subnet Copier: dishonest proof-serving agent for testnet campaigns.

Joins the subnet as a real participant but serves dishonest proofs
to test the PoE detection mechanisms.

Strategies:
  naive    -- returns no proof (proof_b64 stays None)
  delayed  -- generates one real proof on first request, then replays
              that stale proof for all future epochs (epoch mismatch)
  partial  -- runs real PoEProver with fabricated random scores

Usage:
    python neurons/copier.py --strategy naive --netuid 1 \
        --subtensor.network test --wallet.name copier-naive \
        --wallet.hotkey default --poe_root ~/poe-bittensor
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
import typing

import bittensor as bt

from poe_subnet.protocol import ProofSubmission


class TelemetryLogger:
    """Minimal JSONL telemetry logger for copier events."""

    def __init__(self, log_dir: str, prefix: str):
        os.makedirs(log_dir, exist_ok=True)
        self._path = os.path.join(log_dir, f"{prefix}.jsonl")
        self._fh = open(self._path, "a")

    def log(self, **kwargs: typing.Any) -> None:
        kwargs["_ts"] = time.time()
        self._fh.write(json.dumps(kwargs, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def get_config() -> bt.Config:
    parser = argparse.ArgumentParser()
    parser.add_argument("--netuid", type=int, required=True)
    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        choices=["naive", "delayed", "partial"],
    )
    parser.add_argument(
        "--poe_root",
        type=str,
        default=os.path.expanduser("~/poe-bittensor"),
    )
    parser.add_argument("--log_dir", type=str, default="testnet/logs")
    bt.Subtensor.add_args(parser)
    bt.Wallet.add_args(parser)
    bt.Axon.add_args(parser)
    bt.logging.add_args(parser)
    return bt.Config(parser)


class Copier:
    """Dishonest proof-serving neuron."""

    def __init__(self, config: bt.Config | None = None):
        self.config = config or get_config()
        bt.logging(config=self.config)

        self.strategy: str = self.config.strategy
        self.wallet = bt.Wallet(config=self.config)
        self.subtensor = bt.Subtensor(config=self.config)
        self.metagraph = bt.Metagraph(
            netuid=self.config.netuid,
            network=self.subtensor.network,
            sync=True,
            subtensor=self.subtensor,
        )

        self.uid = self._get_uid()

        # Delayed strategy: cached proof from first epoch for replay
        self._cached_proof: dict | None = None

        # Prover instance -- created lazily for delayed, eagerly for partial
        self._prover = None
        if self.strategy in ("partial", "delayed"):
            self._init_prover()

        # Telemetry
        wallet_name = self.wallet.name
        self.telemetry = TelemetryLogger(
            self.config.log_dir,
            f"copier_{self.strategy}_{wallet_name}",
        )

        # Axon
        self.axon = bt.Axon(wallet=self.wallet, config=self.config)
        self.axon.attach(
            forward_fn=self.forward,
            blacklist_fn=self.blacklist,
            priority_fn=self.priority,
        )

        bt.logging.info(
            f"Copier initialized: strategy={self.strategy}, UID={self.uid}"
        )

    def _init_prover(self) -> None:
        """Initialize PoEProver from poe_root config."""
        from poe.config import PoEConfig
        from poe.prover import PoEProver

        poe_config = PoEConfig.from_poe_root(self.config.poe_root)
        self._prover = PoEProver(poe_config, validator_id=self.uid)

    def _get_uid(self) -> int:
        hotkey = self.wallet.hotkey.ss58_address
        if hotkey in self.metagraph.hotkeys:
            return self.metagraph.hotkeys.index(hotkey)
        raise RuntimeError(
            f"Hotkey {hotkey} not registered on netuid {self.config.netuid}"
        )

    # ------------------------------------------------------------------
    # Axon handlers
    # ------------------------------------------------------------------

    async def forward(self, synapse: ProofSubmission) -> ProofSubmission:
        """Handle proof request with the configured dishonest strategy."""
        epoch = synapse.epoch

        if self.strategy == "naive":
            return self._strategy_naive(synapse, epoch)
        elif self.strategy == "delayed":
            return self._strategy_delayed(synapse, epoch)
        elif self.strategy == "partial":
            return self._strategy_partial(synapse, epoch)
        return synapse

    # -- naive ---------------------------------------------------------

    def _strategy_naive(
        self, synapse: ProofSubmission, epoch: int
    ) -> ProofSubmission:
        """Return no proof at all."""
        bt.logging.info(f"[naive] Epoch {epoch}: returning no proof")
        self.telemetry.log(
            tempo=epoch,
            strategy="naive",
            wallet=self.wallet.name,
            uid=self.uid,
            has_valid_proof=False,
            action="no_proof",
        )
        return synapse  # proof_b64 stays None

    # -- delayed -------------------------------------------------------

    def _strategy_delayed(
        self, synapse: ProofSubmission, epoch: int
    ) -> ProofSubmission:
        """On first request generate a real proof; replay it stale forever after.

        Epoch N:   generate real proof -> accepted by validator
        Epoch N+k: replay epoch N proof -> rejected (epoch mismatch in proof)
        """
        if self._cached_proof is not None:
            # Replay stale proof from a previous epoch
            bt.logging.info(
                f"[delayed] Epoch {epoch}: replaying proof from epoch "
                f"{self._cached_proof['epoch']}"
            )
            synapse.proof_b64 = self._cached_proof["proof_b64"]
            synapse.public_inputs_json = self._cached_proof.get(
                "public_inputs_json"
            )
            synapse.proof_timestamp = time.time()

            self.telemetry.log(
                tempo=epoch,
                strategy="delayed",
                wallet=self.wallet.name,
                uid=self.uid,
                has_valid_proof=False,
                action="replay_stale",
                original_epoch=self._cached_proof["epoch"],
            )
            return synapse

        # First request: generate one real proof to cache
        if self._prover is None:
            bt.logging.warning(
                f"[delayed] Epoch {epoch}: prover not available, returning empty"
            )
            self.telemetry.log(
                tempo=epoch,
                strategy="delayed",
                wallet=self.wallet.name,
                uid=self.uid,
                has_valid_proof=False,
                action="no_prover",
            )
            return synapse

        bt.logging.info(
            f"[delayed] Epoch {epoch}: generating initial real proof to cache"
        )

        try:
            self._prover.reset()
            for i in range(8):
                self._prover.add_evaluation(
                    i,
                    f"delayed_{epoch}_{i}".encode(),
                    1000 + i * 100,
                )

            proof = self._prover.prove(epoch, synapse.challenge_nonce)
            proof_b64 = ProofSubmission.encode_proof(proof.proof_bytes)
            public_inputs_json = json.dumps(proof.public_inputs)

            # Cache for future replay
            self._cached_proof = {
                "epoch": epoch,
                "proof_b64": proof_b64,
                "public_inputs_json": public_inputs_json,
            }

            # Return the real proof for this first epoch
            synapse.proof_b64 = proof_b64
            synapse.public_inputs_json = public_inputs_json
            synapse.proof_timestamp = time.time()

            self.telemetry.log(
                tempo=epoch,
                strategy="delayed",
                wallet=self.wallet.name,
                uid=self.uid,
                has_valid_proof=True,
                action="initial_real",
                proof_size_bytes=len(proof.proof_bytes),
            )
        except Exception as e:
            bt.logging.error(f"[delayed] Initial proof generation failed: {e}")
            self.telemetry.log(
                tempo=epoch,
                strategy="delayed",
                wallet=self.wallet.name,
                uid=self.uid,
                has_valid_proof=False,
                action="error",
                error=str(e),
            )

        return synapse

    # -- partial -------------------------------------------------------

    def _strategy_partial(
        self, synapse: ProofSubmission, epoch: int
    ) -> ProofSubmission:
        """Generate a real proof but with fabricated scores."""
        if self._prover is None:
            return synapse

        bt.logging.info(
            f"[partial] Epoch {epoch}: generating proof with fake scores"
        )

        try:
            self._prover.reset()
            for i in range(min(8, 64)):  # Only 8 fake evaluations
                fake_response = f"fake_response_{epoch}_{i}".encode()
                fake_score = random.randint(100, 10000)
                self._prover.add_evaluation(i, fake_response, fake_score)

            proof = self._prover.prove(epoch, synapse.challenge_nonce)
            synapse.proof_b64 = ProofSubmission.encode_proof(proof.proof_bytes)
            synapse.public_inputs_json = json.dumps(proof.public_inputs)
            synapse.proof_timestamp = time.time()

            self.telemetry.log(
                tempo=epoch,
                strategy="partial",
                wallet=self.wallet.name,
                uid=self.uid,
                has_valid_proof=False,  # Valid proof but with fabricated data
                action="fake_scores",
                proof_size_bytes=len(proof.proof_bytes),
            )
        except Exception as e:
            bt.logging.error(f"[partial] Proof generation failed: {e}")
            self.telemetry.log(
                tempo=epoch,
                strategy="partial",
                wallet=self.wallet.name,
                uid=self.uid,
                has_valid_proof=False,
                action="error",
                error=str(e),
            )

        return synapse

    # ------------------------------------------------------------------
    # Blacklist / priority
    # ------------------------------------------------------------------

    async def blacklist(
        self, synapse: ProofSubmission
    ) -> typing.Tuple[bool, str]:
        """Allow all registered validators."""
        caller = synapse.dendrite.hotkey
        if caller not in self.metagraph.hotkeys:
            return True, f"Unrecognized hotkey: {caller}"
        return False, ""

    async def priority(self, synapse: ProofSubmission) -> float:
        """Prioritize by caller's stake."""
        caller = synapse.dendrite.hotkey
        if caller in self.metagraph.hotkeys:
            uid = self.metagraph.hotkeys.index(caller)
            return float(self.metagraph.S[uid])
        return 0.0

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main copier loop."""
        bt.logging.info(f"Starting copier axon (strategy={self.strategy})...")
        self.axon.serve(netuid=self.config.netuid, subtensor=self.subtensor)
        self.axon.start()
        bt.logging.info(
            f"Copier serving on {self.axon.external_ip}:{self.axon.external_port}"
        )

        try:
            while True:
                self.metagraph.sync(subtensor=self.subtensor)
                time.sleep(12)
        except KeyboardInterrupt:
            bt.logging.info("Copier shutting down...")
        finally:
            self.axon.stop()
            self.telemetry.close()


if __name__ == "__main__":
    copier = Copier()
    copier.run()
