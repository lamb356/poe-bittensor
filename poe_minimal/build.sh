#!/bin/bash
set -e

echo "=== Compiling ==="
nargo compile

echo ""
echo "=== Gate Count ==="
nargo info

echo ""
echo "=== Running Tests ==="
nargo test --show-output

echo ""
echo "=== Done ==="
