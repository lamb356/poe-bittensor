#!/bin/bash
# Deploy PoE to Bittensor testnet.
#
# Prerequisites:
#   - btcli installed (pip install bittensor-cli)
#   - poe-validator, poe-subnet installed
#   - Noir toolchain (nargo, bb) available
#
# Usage:
#   bash testnet/scripts/deploy.sh [--local]
#     --local: use local subtensor instead of testnet

set -euo pipefail

NETWORK="${1:---network test}"
if [ "${1:-}" = "--local" ]; then
    NETWORK="--network ws://127.0.0.1:9944"
    echo "=== Using local subtensor ==="
else
    echo "=== Deploying to Bittensor testnet ==="
fi

POE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo ""
echo "=== Step 1: Create wallets ==="
for name in poe-owner poe-miner poe-validator-1 poe-validator-2 poe-validator-3; do
    btcli wallet create --wallet-name "$name" --wallet-hotkey default --no-password 2>/dev/null || true
    echo "  Wallet: $name"
done

echo ""
echo "=== Step 2: Fund wallets (testnet faucet) ==="
if [ "$NETWORK" != "--network ws://127.0.0.1:9944" ]; then
    echo "  Visit https://faucet.opentensor.dev/ to get test TAO"
    echo "  Fund these coldkey addresses:"
    for name in poe-owner poe-miner poe-validator-1 poe-validator-2 poe-validator-3; do
        addr=$(btcli wallet overview --wallet-name "$name" --no-prompt 2>/dev/null | grep -oP '5[A-Za-z0-9]{47}' | head -1)
        echo "    $name: $addr"
    done
    echo ""
    read -p "Press Enter after funding wallets..."
fi

echo ""
echo "=== Step 3: Create subnet ==="
btcli subnet create --wallet-name poe-owner $NETWORK --no-prompt || true
echo "  Subnet created (check netuid with: btcli subnet list $NETWORK)"
NETUID="${NETUID:-1}"
echo "  Using netuid: $NETUID"

echo ""
echo "=== Step 4: Register neurons ==="
for name in poe-miner poe-validator-1 poe-validator-2 poe-validator-3; do
    btcli subnet register --netuid "$NETUID" --wallet-name "$name" --wallet-hotkey default \
        $NETWORK --no-prompt || true
    echo "  Registered: $name"
done

echo ""
echo "=== Step 5: Compile circuit ==="
cd "$POE_ROOT/poe_circuit" && nargo compile
echo "  Circuit compiled"

echo ""
echo "=== Step 6: Build witness generator ==="
cd "$POE_ROOT/poe-witness" && cargo build --release
echo "  Witness generator built"

echo ""
echo "=== Deployment complete ==="
echo "Start neurons with:"
echo "  python testnet/scripts/run_campaign.sh --netuid $NETUID $NETWORK"
