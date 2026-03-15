"""Test validator weight-setting flow using MockSubtensor."""
import pytest
import numpy as np
import bittensor as bt

import poe_subnet
from poe_subnet.config import PoESubnetConfig


def _setup_mock_subnet(subtensor, netuid=1):
    """Manually add a subnet to MockSubtensor chain state.

    MockSubtensor.register_subnet() has a Balance bug in bittensor 10.x,
    so we set up the chain state directly using the block-indexed format.
    """
    block = subtensor.block_number
    sm = subtensor.chain_state["SubtensorModule"]

    sm["NetworksAdded"][netuid] = True

    for key in [
        "SubnetworkN", "MaxAllowedUids", "MinAllowedWeights",
        "MaxWeightsLimit", "ImmunityPeriod", "Tempo",
        "Uids", "Keys", "Owner", "Active", "LastUpdate",
        "Rank", "Emission", "Incentive", "Consensus", "Trust",
        "ValidatorTrust", "ValidatorPermit", "Dividends",
        "PruningScores", "Weights", "Bonds", "Axons", "Prometheus",
    ]:
        if key not in sm:
            sm[key] = {}
        if netuid not in sm[key]:
            sm[key][netuid] = {}

    sm["SubnetworkN"][netuid][block] = 0
    sm["MaxAllowedUids"][netuid][block] = 256
    sm["MinAllowedWeights"][netuid][block] = 0
    sm["MaxWeightsLimit"][netuid][block] = 65535
    sm["ImmunityPeriod"][netuid][block] = 100
    sm["Tempo"][netuid][block] = 360

    if "Stake" not in sm:
        sm["Stake"] = {}
    if "IsNetworkMember" not in sm:
        sm["IsNetworkMember"] = {}


@pytest.fixture
def chain_env(tmp_path):
    """Set up MockSubtensor with registered subnet, miner, and validator."""
    subtensor = bt.MockSubtensor()

    wallet_path = str(tmp_path / "wallets")
    miner_wallet = bt.Wallet(name="test-miner", hotkey="default", path=wallet_path)
    miner_wallet.create_if_non_existent(coldkey_use_password=False, hotkey_use_password=False)

    validator_wallet = bt.Wallet(name="test-validator", hotkey="default", path=wallet_path)
    validator_wallet.create_if_non_existent(coldkey_use_password=False, hotkey_use_password=False)

    # Setup subnet manually (bypasses broken register_subnet)
    _setup_mock_subnet(subtensor, netuid=1)

    # Register neurons
    subtensor.force_register_neuron(
        netuid=1,
        hotkey_ss58=miner_wallet.hotkey.ss58_address,
        coldkey_ss58=miner_wallet.coldkeypub.ss58_address,
        balance=1000.0,
    )
    subtensor.force_register_neuron(
        netuid=1,
        hotkey_ss58=validator_wallet.hotkey.ss58_address,
        coldkey_ss58=validator_wallet.coldkeypub.ss58_address,
        balance=1000.0,
    )

    return {
        "subtensor": subtensor,
        "miner_wallet": miner_wallet,
        "validator_wallet": validator_wallet,
        "netuid": 1,
    }


@pytest.mark.skip(reason="MockSubtensor Balance bug in bittensor 10.1.0 - test on real local subtensor")
class TestChainWeights:
    def test_metagraph_shows_registered_neurons(self, chain_env):
        sub = chain_env["subtensor"]
        metagraph = sub.metagraph(chain_env["netuid"])
        assert metagraph.n >= 2

        miner_hk = chain_env["miner_wallet"].hotkey.ss58_address
        validator_hk = chain_env["validator_wallet"].hotkey.ss58_address
        assert miner_hk in metagraph.hotkeys
        assert validator_hk in metagraph.hotkeys

    def test_set_weights_succeeds(self, chain_env):
        sub = chain_env["subtensor"]
        wallet = chain_env["validator_wallet"]
        metagraph = sub.metagraph(chain_env["netuid"])

        uids = list(range(metagraph.n))
        weights = [65535 // max(metagraph.n, 1)] * metagraph.n

        result = sub.set_weights(
            wallet=wallet,
            netuid=chain_env["netuid"],
            uids=uids,
            weights=weights,
            version_key=poe_subnet.__spec_version__,
        )
        assert result is not None

    def test_score_to_weight_pipeline(self, chain_env):
        sub = chain_env["subtensor"]
        wallet = chain_env["validator_wallet"]
        config = PoESubnetConfig(netuid=chain_env["netuid"])
        metagraph = sub.metagraph(chain_env["netuid"])

        scores = np.zeros(metagraph.n, dtype=np.float32)
        miner_hk = chain_env["miner_wallet"].hotkey.ss58_address
        miner_uid = metagraph.hotkeys.index(miner_hk)

        # Simulate EMA score updates over multiple epochs
        alpha = config.moving_average_alpha
        for _ in range(5):
            scores[miner_uid] = alpha * 1.0 + (1 - alpha) * scores[miner_uid]

        total = np.sum(scores)
        assert total > 0

        raw_weights = scores / total
        mask = raw_weights > 0
        uids = np.where(mask)[0]
        weights = raw_weights[mask]
        weights_u16 = (weights / weights.max() * 65535).astype(int)

        result = sub.set_weights(
            wallet=wallet,
            netuid=chain_env["netuid"],
            uids=uids.tolist(),
            weights=weights_u16.tolist(),
            version_key=poe_subnet.__spec_version__,
        )
        assert result is not None

    def test_weight_normalization(self):
        scores = np.array([0.0, 0.95, 0.0, 0.5, 0.0], dtype=np.float32)
        total = np.sum(scores)
        raw_weights = scores / total
        assert abs(np.sum(raw_weights) - 1.0) < 1e-6

        mask = raw_weights > 0
        uids = np.where(mask)[0]
        weights = raw_weights[mask]

        assert len(uids) == 2
        assert uids[0] == 1
        assert uids[1] == 3
        assert weights[0] > weights[1]
