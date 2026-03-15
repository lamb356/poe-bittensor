#!/bin/bash
set -e

echo "=== Compiling ==="
nargo compile

echo ""
echo "=== Gate Count (ACIR) ==="
nargo info

echo ""
echo "=== Gate Count (UltraHonk backend) ==="
bb gates --scheme ultra_honk -b ./target/poe_circuit.json

echo ""
echo "=== Running Tests ==="
nargo test --show-output

echo ""
echo "=== Done ==="
