#!/bin/bash
# Setup local subtensor chain for PoE integration testing.
#
# Prerequisites:
#   - subtensor built at ~/subtensor/target/release/node-subtensor
#   - btcli installed (pip install bittensor-cli)
#
# Usage:
#   1. Start subtensor: ~/subtensor/target/release/node-subtensor --dev --tmp
#   2. In another terminal: bash scripts/setup_local_chain.sh
#   3. Then run: PYTHONPATH=. python scripts/test_integration.py

set -euo pipefail

CHAIN="ws://127.0.0.1:9944"

echo "=== Creating wallets ==="
btcli wallet create --wallet-name owner --wallet-hotkey default --no-password 2>/dev/null || true
btcli wallet create --wallet-name miner --wallet-hotkey default --no-password 2>/dev/null || true
btcli wallet create --wallet-name validator --wallet-hotkey default --no-password 2>/dev/null || true

echo ""
echo "=== Creating subnet ==="
btcli subnet create --wallet-name owner --network "$CHAIN" --no-prompt || true

echo ""
echo "=== Registering miner on netuid 1 ==="
btcli subnet register --netuid 1 --wallet-name miner --wallet-hotkey default \
    --network "$CHAIN" --no-prompt || true

echo ""
echo "=== Registering validator on netuid 1 ==="
btcli subnet register --netuid 1 --wallet-name validator --wallet-hotkey default \
    --network "$CHAIN" --no-prompt || true

echo ""
echo "=== Setup complete ==="
echo "Now run: PYTHONPATH=. python scripts/test_integration.py"
