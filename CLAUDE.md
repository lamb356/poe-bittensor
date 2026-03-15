# PoE -- Proof-of-Evaluation for Bittensor

## What This Is
ZK protocol that cryptographically proves Bittensor validators actually executed their
evaluation functions on miner outputs, rather than copying weights from other validators.

## Architecture
- Noir circuits (Barretenberg UltraHonk backend, no trusted setup)
- Poseidon2 hashing in-circuit, BLAKE3 off-circuit for response hashing
- Rust witness generator bridges Python validator -> Noir prover
- Commitment helper (Noir) computes Poseidon2 commitments for the witness generator
- Three integration paths: validator sidecar -> zkVerify bridge -> Subtensor pallet
- zkVerify API: testnet.kurier.xyz (was horizenlabs.io, rebranded to Kurier)

## Project Structure
- `poe_minimal/` -- Piece 0: 8-miner Lite PoE circuit (toolchain validation, 5,675 gates)
- `poe_circuit/` -- Piece 1: 64-miner Lite PoE circuit (37,443 gates, 5 tests)
- `poe-witness/` -- Piece 2: Rust witness generator + BLAKE3 bridge + roundtrip test
- `commitment_helper/` -- Noir circuit that computes Poseidon2 commitments (used by poe-witness)
- `tla/` -- TLA+ formal verification of PoE protocol (3.1M states, all invariants pass)
- `poe-validator/` -- Piece 4: Python validator integration (19 tests, E2E prove+verify)
- `poe-subnet/` -- Piece 5: Bittensor subnet scaffold (41 tests, axon/dendrite proof roundtrip)
- `poe-zkverify/` -- Piece 6: zkVerify bridge (23 tests, retry with backoff, CLI binary)

## Key Constraints
- Gate budget: 500K-1M gates (2^19 to 2^20) -> 10-20s proving on UltraHonk
- Tempo: 72 minutes. Proof generation must complete in <60s (target <20s)
- UltraHonk verification: ~45ms constant regardless of circuit size
- Poseidon2 for in-circuit hashing. NEVER use SHA-256 or BLAKE3 in-circuit (~20x more expensive)
- NEVER use Field.lt() for range checks in UltraHonk circuits. Use assert_max_bit_size instead. Field.lt() costs ~435 gates per call; assert_max_bit_size costs ~1 gate per 14-bit chunk (UltraHonk lookup tables). This is a 4x+ gate reduction.
- Circuit has 6 public inputs: input_commitment, weight_commitment, score_commitment, epoch, validator_id, challenge_nonce
- Field elements are BN254 scalar field

## Critical Rules
- SN8 eval uses SignedField for negative PnL (magnitude + is_negative bool)
- BLAKE3 is used OFF-circuit only (response hashing). Poseidon2 IN-circuit only.
- All proofs use UltraHonk backend (not UltraPlonk -- 2.5x slower, no benefit)
- Gate count estimates must be verified against `bb gates --scheme ultra_honk` output
- zkVerify requires keccak Fiat-Shamir: use `bb prove --oracle_hash keccak` for proofs destined for zkVerify. Default Poseidon is fine for local/peer verification.
- Proof generation time must be benchmarked on commodity hardware (not just M2 Max)
- When communicating with Bittensor community: accuracy over speed, always verify claims
- BLAKE3 hashing is <1ms for the witness generator workload (64 responses, kilobytes each). Do NOT optimize BLAKE3 in this project -- it's <0.1% of pipeline time. Performance optimization belongs in Piece 6 (zkVerify submission latency, proof aggregation, optional native Poseidon2).

## Measured Gate Counts
| Circuit | Miners | ACIR Opcodes | UltraHonk Gates |
|---------|--------|-------------|-----------------|
| poe_minimal | 8 | 923 | 5,675 |
| poe_circuit | 64 | 662 | 7,845 (optimized + H-01 + C-01 score commitment) |

## Build Order
Piece 0: Minimal circuit (8 miners) -- COMPLETE
Piece 1: Core Lite PoE circuit (64 miners) -- COMPLETE
Piece 2: Rust witness generator -- COMPLETE
Piece 3: Reference evaluation modules (pluggable Noir traits) -- COMPLETE
Piece 4: Python validator integration package -- COMPLETE
Piece 5: Bittensor subnet scaffold -- COMPLETE
Piece 6: zkVerify bridge -- COMPLETE
Piece 7: Testnet campaign
Piece 8: Mainnet launch prep

## Testing
- `cd poe_circuit && nargo test` -- circuit tests (5 tests)
- `cd poe-witness && cargo test` -- witness generator tests (9 tests, includes roundtrip)
- `cd commitment_helper && nargo test` -- commitment computation test
- `cd tla && java -jar ~/.tlaplus/tla2tools.jar -workers auto -deadlock PoE.tla` -- TLA+ verification
- `cd poe-validator && source .venv/bin/activate && pytest tests/` -- validator integration (19 tests)
- `cd poe-subnet && source .venv/bin/activate && PYTHONPATH=. pytest tests/` -- subnet scaffold (41 tests)
- `cd poe-zkverify && cargo test` -- zkVerify bridge (23 tests)

## Toolchain (WSL2)
- Noir: nargo 1.0.0-beta.9 (via noirup)
- Barretenberg: bb 0.82.2 (via bbup)
- Rust: stable (via rustup)
- All Noir/bb commands run in WSL2, not Windows Git Bash

## Bittensor Context
- Yuma Consensus runs in `run_epoch.rs` (8 stages, deterministic, on-chain)
- Weight submission: `set_weights(wallet, netuid, uids, weights, version_key)`
- CR4 uses Drand time-lock encryption. PoE complements CR4.
- Validator permits: top 64 by emissions/stake, min 1,000 stake weight
- Tempo: 360 blocks x 12s = 72 minutes
- Emission split: 18% owner, 41% validators, 41% miners
