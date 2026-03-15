#!/bin/bash
# Orchestrate full PoE testnet campaign.
#
# Starts 3 honest validators + 3 copier agents, runs 100 tempos,
# collects monitoring data, produces final report.
#
# Usage:
#   bash testnet/scripts/run_campaign.sh [--tempos 100] [--network test]

set -euo pipefail

TEMPOS="${TEMPOS:-100}"
NETWORK="${NETWORK:---network test}"
NETUID="${NETUID:-1}"
POE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$POE_ROOT/testnet/logs"
PID_FILE="$POE_ROOT/testnet/.pids"

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
echo "Tempos: $TEMPOS"
echo "Network: $NETWORK"
echo "Netuid: $NETUID"
echo "Logs: $LOG_DIR"
echo ""

# Start copier agents (background)
echo "=== Starting copier agents ==="

python "$POE_ROOT/testnet/scripts/copier_agents.py" \
    --strategy naive --wallet-name copier-naive \
    --num-tempos "$TEMPOS" --log-dir "$LOG_DIR" &
echo $! >> "$PID_FILE"
echo "  naive copier: PID $!"

python "$POE_ROOT/testnet/scripts/copier_agents.py" \
    --strategy delayed --wallet-name copier-delayed \
    --noise-std 0.02 --num-tempos "$TEMPOS" --log-dir "$LOG_DIR" &
echo $! >> "$PID_FILE"
echo "  delayed copier: PID $!"

python "$POE_ROOT/testnet/scripts/copier_agents.py" \
    --strategy partial --wallet-name copier-partial \
    --honest-fraction 0.1 --num-tempos "$TEMPOS" --log-dir "$LOG_DIR" &
echo $! >> "$PID_FILE"
echo "  partial copier: PID $!"

echo ""
echo "=== Waiting for campaign to complete ==="
echo "(Press Ctrl+C to stop early)"

# Wait for all background jobs
wait

echo ""
echo "=== Campaign complete. Generating report ==="
python "$POE_ROOT/testnet/scripts/monitor.py" --log-dir "$LOG_DIR"

# Save JSON report
python "$POE_ROOT/testnet/scripts/monitor.py" --log-dir "$LOG_DIR" --json \
    > "$LOG_DIR/campaign_report.json"
echo ""
echo "JSON report saved to: $LOG_DIR/campaign_report.json"
