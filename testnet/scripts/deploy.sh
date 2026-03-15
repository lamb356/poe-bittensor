#!/bin/bash
# Deploy PoE to Bittensor testnet.
set -euo pipefail

NETWORK="${1:---network test}"
if [ "${1:-}" = "--local" ]; then
    NETWORK="--network ws://127.0.0.1:9944"
    echo "=== Using local subtensor ==="
else
    echo "=== Deploying to Bittensor testnet ==="
fi

POE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

preflight() {
    echo ""
    echo "=== Preflight: Checking prerequisites ==="

    command -v btcli >/dev/null 2>&1 || { echo "ERROR: btcli not found. Install with: pip install bittensor-cli"; exit 1; }
    command -v nargo >/dev/null 2>&1 || { echo "ERROR: nargo not found. Install from noir-lang.org"; exit 1; }
    command -v cargo >/dev/null 2>&1 || { echo "ERROR: cargo not found. Install from rustup.rs"; exit 1; }

    echo "  All prerequisites found"

    echo ""
    echo "=== Preflight: Creating wallets ==="
    for name in poe-owner poe-miner poe-validator-1 poe-validator-2 poe-validator-3; do
        if btcli wallet overview --wallet-name "$name" --no-prompt 2>/dev/null | grep -q '5[A-Za-z0-9]'; then
            echo "  Wallet exists: $name"
        else
            echo "  Creating wallet: $name"
            btcli wallet create --wallet-name "$name" --wallet-hotkey default --no-password
        fi
    done

    echo ""
    echo "=== Preflight: Fund wallets ==="
    if [ "$NETWORK" != "--network ws://127.0.0.1:9944" ]; then
        echo "  Visit https://faucet.opentensor.dev/ to get test TAO"
        echo "  Fund these coldkey addresses:"
        for name in poe-owner poe-miner poe-validator-1 poe-validator-2 poe-validator-3; do
            addr=$(btcli wallet overview --wallet-name "$name" --no-prompt 2>/dev/null | grep -oP '5[A-Za-z0-9]{47}' | head -1)
            echo "    $name: ${addr:-UNKNOWN}"
        done
        echo ""
        read -p "Press Enter after funding wallets..."
    fi
}

deploy() {
    echo ""
    echo "=== Deploy: Create subnet ==="
    btcli subnet create --wallet-name poe-owner $NETWORK --no-prompt

    # Resolve the actual netuid from the created subnet
    if [ -z "${NETUID:-}" ]; then
        echo "  ERROR: NETUID not set. After creating the subnet, find it with:"
        echo "    btcli subnet list $NETWORK"
        echo "  Then re-run with: NETUID=<n> bash $0 $@"
        exit 1
    fi
    echo "  Using netuid: $NETUID"

    echo ""
    echo "=== Deploy: Register neurons ==="
    for name in poe-miner poe-validator-1 poe-validator-2 poe-validator-3; do
        echo "  Registering: $name"
        btcli subnet register --netuid "$NETUID" --wallet-name "$name" --wallet-hotkey default \
            $NETWORK --no-prompt
        echo "  Registered: $name"
    done

    echo ""
    echo "=== Deploy: Compile circuit ==="
    cd "$POE_ROOT/poe_circuit" && nargo compile
    echo "  Circuit compiled"

    echo ""
    echo "=== Deploy: Build witness generator ==="
    cd "$POE_ROOT/poe-witness" && cargo build --release
    echo "  Witness generator built"

    echo ""
    echo "=== Deployment complete ==="
    echo "Start campaign with:"
    echo "  NETUID=$NETUID bash testnet/scripts/run_campaign.sh"
}

preflight
deploy
