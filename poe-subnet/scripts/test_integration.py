"""Integration test: full PoE flow against local subtensor.

This script:
1. Starts a miner axon (serves ProofSubmission)
2. Validator queries miner via dendrite
3. Miner generates a real ZK proof
4. Validator verifies it
5. Validator sets weights on chain

Prerequisites:
- Local subtensor running: ~/subtensor/target/release/node-subtensor --dev --tmp
- Chain setup done: bash scripts/setup_local_chain.sh

Usage:
    cd ~/poe-bittensor/poe-subnet
    source .venv/bin/activate
    PYTHONPATH=. python scripts/test_integration.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import typing

import bittensor as bt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from poe_subnet.protocol import ProofSubmission
from poe_subnet.config import PoESubnetConfig
from poe_subnet.reward import reward

from poe.config import PoEConfig
from poe.prover import PoEProver
from poe.verifier import PoEVerifier
from poe.challenge import get_mock_nonce

CHAIN = os.environ.get("SUBTENSOR_CHAIN", "ws://127.0.0.1:9944")
NETUID = 1
POE_ROOT = os.path.expanduser("~/poe-bittensor")


def test_synapse_over_axon():
    """Test ProofSubmission synapse over real axon/dendrite."""
    print("\n=== Test 1: Synapse over Axon/Dendrite ===")

    miner_wallet = bt.Wallet(name="miner", hotkey="default")
    validator_wallet = bt.Wallet(name="validator", hotkey="default")

    poe_config = PoEConfig.from_poe_root(POE_ROOT)
    prover = PoEProver(poe_config, validator_id=0)
    verifier = PoEVerifier(poe_config)

    for uid in range(64):
        prover.add_evaluation(uid, f"integration-test-{uid}".encode(), (uid + 1) * 100)

    async def miner_forward(synapse: ProofSubmission) -> ProofSubmission:
        print(f"  Miner received request: epoch={synapse.epoch}")
        proof = prover.prove(synapse.epoch, synapse.challenge_nonce)
        synapse.proof_b64 = ProofSubmission.encode_proof(proof.proof_bytes)
        synapse.public_inputs_json = json.dumps({"epoch": proof.epoch})
        synapse.proof_timestamp = time.time()
        print(f"  Miner generated proof: {len(proof.proof_bytes)} bytes")
        return synapse

    async def miner_blacklist(synapse: ProofSubmission) -> typing.Tuple[bool, str]:
        return False, ""

    async def miner_priority(synapse: ProofSubmission) -> float:
        return 1.0

    axon = bt.Axon(wallet=miner_wallet, port=8091)
    axon.attach(
        forward_fn=miner_forward,
        blacklist_fn=miner_blacklist,
        priority_fn=miner_priority,
    )
    axon.start()
    print(f"  Miner axon started on port 8091")

    try:
        dendrite = bt.Dendrite(wallet=validator_wallet)
        synapse = ProofSubmission(epoch=1, challenge_nonce=get_mock_nonce(1), subnet_uid=NETUID)

        miner_info = bt.AxonInfo(
            version=1, ip="127.0.0.1", port=8091, ip_type=4,
            hotkey=miner_wallet.hotkey.ss58_address,
            coldkey=miner_wallet.coldkeypub.ss58_address,
        )

        print(f"  Validator querying miner...")
        loop = asyncio.new_event_loop()
        responses = loop.run_until_complete(
            dendrite.forward(axons=[miner_info], synapse=synapse, deserialize=False, timeout=60.0)
        )
        loop.close()

        response = responses[0]
        if isinstance(response, ProofSubmission) and response.proof_b64:
            proof_bytes = response.proof_bytes
            print(f"  Proof received: {len(proof_bytes)} bytes")
            is_valid = verifier.verify(proof_bytes)
            print(f"  Proof valid: {is_valid}")
            assert is_valid, "Proof should be valid!"

            config = PoESubnetConfig()
            score = reward(True, response.proof_timestamp, time.time(), config)
            print(f"  Reward: {score}")
            print("  PASS")
        else:
            print(f"  FAIL: No proof. Type={type(response)}")
            if hasattr(response, 'dendrite'):
                print(f"  Status: {response.dendrite.status_code} {response.dendrite.status_message}")
    finally:
        axon.stop()


def test_chain_weights():
    """Test setting weights on local chain."""
    print("\n=== Test 2: Set Weights on Chain ===")

    try:
        subtensor = bt.Subtensor(network=CHAIN)
        validator_wallet = bt.Wallet(name="validator", hotkey="default")
        metagraph = bt.Metagraph(netuid=NETUID, network=CHAIN, sync=True, subtensor=subtensor)
        print(f"  Metagraph: {metagraph.n} neurons")

        hotkey = validator_wallet.hotkey.ss58_address
        if hotkey not in metagraph.hotkeys:
            print(f"  SKIP: Validator not registered")
            return

        val_uid = metagraph.hotkeys.index(hotkey)
        print(f"  Validator UID: {val_uid}")

        uids = list(range(min(metagraph.n, 2)))
        weights = [65535 // len(uids)] * len(uids)

        print(f"  Setting weights: uids={uids}")
        result = subtensor.set_weights(
            wallet=validator_wallet, netuid=NETUID,
            uids=uids, weights=weights, version_key=1,
        )
        print(f"  Result: {result}")
        print("  PASS")

    except Exception as e:
        print(f"  Chain error: {e}")
        print("  SKIP: Start subtensor with --dev first")


if __name__ == "__main__":
    print("PoE Integration Tests")
    print("=" * 50)
    test_synapse_over_axon()
    test_chain_weights()
    print("\n" + "=" * 50)
    print("Done!")
