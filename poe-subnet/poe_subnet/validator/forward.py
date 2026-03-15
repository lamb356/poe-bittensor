"""Validator forward pass: query miners for proofs, verify, score."""
from __future__ import annotations

import time

import bittensor as bt
import numpy as np

from poe_subnet.config import PoESubnetConfig
from poe_subnet.protocol import ProofSubmission
from poe_subnet.reward import get_rewards
from poe_subnet.utils.uids import get_random_uids


async def forward(validator) -> None:
    """Query miners for PoE proofs and score them.

    Called each step by the validator's main loop.
    """
    config: PoESubnetConfig = validator.poe_subnet_config
    current_block = validator.block

    # Determine current epoch
    epoch = current_block // config.tempo
    epoch_end_time = time.time()

    # Challenge nonce for this epoch
    challenge_nonce = hash(f"poe-challenge-{epoch}") % (2**63)

    # Select miners to query
    miner_uids = get_random_uids(
        validator.metagraph,
        k=config.sample_size,
        exclude={validator.uid},
    )

    if len(miner_uids) == 0:
        bt.logging.warning("No miners available to query")
        return

    bt.logging.info(
        f"Querying {len(miner_uids)} miners for epoch {epoch} proofs"
    )

    # Query miners for proof submissions
    synapse = ProofSubmission(
        epoch=epoch,
        challenge_nonce=challenge_nonce,
        subnet_uid=config.netuid,
    )

    responses = await validator.dendrite.forward(
        axons=[validator.metagraph.axons[uid] for uid in miner_uids],
        synapse=synapse,
        deserialize=False,
        timeout=config.proof_timeout,
    )

    # Verify each proof
    proof_results = []
    for uid, response in zip(miner_uids, responses):
        result = _verify_response(validator, response, config)
        proof_results.append(result)
        status = "valid" if result["proof_valid"] else "invalid/missing"
        bt.logging.debug(f"  UID {uid}: {status}")

    # Score miners
    rewards = get_rewards(proof_results, epoch_end_time, config)
    bt.logging.info(
        f"Rewards: mean={rewards.mean():.3f}, "
        f"valid={np.sum(rewards > 0)}/{len(rewards)}"
    )

    validator.update_scores(rewards, miner_uids)


def _verify_response(
    validator,
    response: ProofSubmission,
    config: PoESubnetConfig,
) -> dict:
    """Verify a single miner's proof submission."""
    if response.proof_b64 is None:
        return {"proof_valid": False, "proof_timestamp": None}

    proof_data = response.proof_bytes
    if len(proof_data) < config.min_proof_size:
        bt.logging.debug(
            f"Proof too small: {len(proof_data)} bytes"
        )
        return {"proof_valid": False, "proof_timestamp": response.proof_timestamp}

    try:
        is_valid = validator.verifier.verify(proof_data)
    except Exception as e:
        bt.logging.warning(f"Proof verification error: {e}")
        is_valid = False

    return {
        "proof_valid": is_valid,
        "proof_timestamp": response.proof_timestamp,
    }
