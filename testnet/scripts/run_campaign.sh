#!/bin/bash
# Orchestrate full PoE testnet campaign.
#
# Launches 1 validator, 3 honest miners, 3 copier agents (all real neurons),
# runs live monitor, and produces final report.
#
# Usage:
#   bash testnet/scripts/run_campaign.sh
#   NETUID=42 bash testnet/scripts/run_campaign.sh

set -euo pipefail

POE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$POE_ROOT/testnet/logs"
PID_FILE="$POE_ROOT/testnet/.pids"
TEMPOS="${TEMPOS:-100}"

# Read NETUID
if [ -n "${NETUID:-}" ]; then
    echo "Using NETUID=$NETUID from environment"
elif [ -f "$POE_ROOT/testnet/.netuid" ]; then
    NETUID=$(cat "$POE_ROOT/testnet/.netuid")
    echo "Using NETUID=$NETUID from testnet/.netuid"
else
    echo "ERROR: NETUID not set and testnet/.netuid not found."
    echo "Run deploy.sh first, or set NETUID=<n>"
    exit 1
fi

NETWORK="${NETWORK:---network test}"

mkdir -p "$LOG_DIR"
> "$PID_FILE"

cleanup() {
    echo ""
    echo "=== Stopping all agents ==="
    while read pid; do
        kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
    echo "All agents stopped."
}
trap cleanup EXIT

echo "=== PoE Testnet Campaign ==="
echo "Netuid: $NETUID"
echo "Network: $NETWORK"
echo "Logs: $LOG_DIR"
echo ""

# Start PoE validator
echo "=== Starting PoE validator ==="
python "$POE_ROOT/poe-subnet/neurons/validator.py" \
    --netuid "$NETUID" --subtensor.network test \
    --wallet.name poe-verifier-1 --wallet.hotkey default \
    --poe_root "$POE_ROOT" --log_dir "$LOG_DIR" &
echo $! >> "$PID_FILE"
echo "  validator: PID $!"

# Start honest miners
echo ""
echo "=== Starting honest miners ==="
PORT=8091
for name in poe-honest-1 poe-honest-2 poe-honest-3; do
    python "$POE_ROOT/poe-subnet/neurons/miner.py" \
        --netuid "$NETUID" --subtensor.network test \
        --wallet.name "$name" --wallet.hotkey default \
        --poe_root "$POE_ROOT" --log_dir "$LOG_DIR" \
        --axon.port "$PORT" &
    echo $! >> "$PID_FILE"
    echo "  $name: PID $! (port $PORT)"
    PORT=$((PORT + 1))
done

# Start copier agents
echo ""
echo "=== Starting copier agents ==="
for strategy in naive delayed partial; do
    python "$POE_ROOT/poe-subnet/neurons/copier.py" \
        --strategy "$strategy" \
        --netuid "$NETUID" --subtensor.network test \
        --wallet.name "poe-copier-$strategy" --wallet.hotkey default \
        --poe_root "$POE_ROOT" --log_dir "$LOG_DIR" \
        --axon.port "$PORT" &
    echo $! >> "$PID_FILE"
    echo "  copier-$strategy: PID $! (port $PORT)"
    PORT=$((PORT + 1))
done

echo ""
echo "=== All agents started. Waiting for campaign... ==="
echo "(Press Ctrl+C to stop)"

# Wait for all background jobs
wait

echo ""
echo "=== Campaign complete. Generating report ==="
python "$POE_ROOT/testnet/scripts/monitor.py" --log-dir "$LOG_DIR"
python "$POE_ROOT/testnet/scripts/monitor.py" --log-dir "$LOG_DIR" --json \
    > "$LOG_DIR/campaign_report.json"
echo "JSON report: $LOG_DIR/campaign_report.json"
