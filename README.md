# Proof-of-Evaluation for Bittensor

Proof-of-Evaluation (PoE) is a ZK protocol that cryptographically proves Bittensor validators actually ran their evaluation functions on miner outputs, rather than copying weights from other validators. It generates a compact UltraHonk proof (~14KB) that binds a validator's identity, the miner responses they evaluated, and the weights they submitted -- all verifiable in ~45ms without seeing the original data.

## Key Numbers

| Metric | Value |
|--------|-------|
| Circuit size | **7,845 UltraHonk gates** (79% optimized from 37,443) |
| Proof size | 14,244 bytes |
| Proving time | <0.5s (64 miners, commodity hardware) |
| Verification time | ~45ms constant |
| Circuit tests | 70 (including 20 fuzz + 8 adversarial) |
| Total tests | 160 across all packages |
| TLA+ states verified | 110M+ (4 honest, 3 copier, 5 miner, 5 epoch model) |

## Project Structure

```
poe-bittensor/
  poe_minimal/         Piece 0: 8-miner circuit (toolchain validation)
  poe_circuit/         Piece 1: 64-miner Lite PoE circuit (7,845 gates, 65 tests)
  commitment_helper/   Noir circuit for Poseidon2 commitment computation
  poe-witness/         Piece 2: Rust witness generator (BLAKE3 + normalization)
  poe-validator/       Piece 4: Python package for Bittensor validator integration
  poe-subnet/          Piece 5: Bittensor subnet scaffold (axon/dendrite proven)
  poe-zkverify/        Piece 6: zkVerify bridge for on-chain attestation
  tla/                 TLA+ formal verification of the PoE protocol
  SPEC.md              Full protocol specification (9 pieces, feasibility analysis)
```

## How It Works

```
Validator's forward() loop
    |
    v
1. Evaluate miners normally (get responses, compute scores)
    |
    v
2. poe-witness: BLAKE3 hash responses, normalize scores to u16 weights,
   compute Poseidon2 commitments
    |
    v
3. nargo execute + bb prove: generate UltraHonk proof (~0.5s)
   - Proves: weights are proportional to scores
   - Proves: responses were actually evaluated (committed via hash)
   - Proves: proof is bound to this validator + this epoch
    |
    v
4. Submit proof to zkVerify for trustless on-chain attestation
   OR publish for peer verification
    |
    v
5. set_weights() as normal -- proof accompanies the weight submission
```

## Quick Start (Validators)

### Prerequisites

- [Noir](https://noir-lang.org/) (nargo >= 1.0.0-beta.9)
- [Barretenberg](https://github.com/AztecProtocol/aztec-packages/tree/master/barretenberg) (bb >= 0.82.2)
- Rust stable
- Python >= 3.10

### Install

```bash
# 1. Clone
git clone https://github.com/lamb356/poe-bittensor.git
cd poe-bittensor

# 2. Compile the circuit
cd poe_circuit && nargo compile && cd ..

# 3. Build the witness generator
cd poe-witness && cargo build && cd ..

# 4. Install the Python package
cd poe-validator && pip install -e '.[dev]' && cd ..

# 5. Run tests
cd poe_circuit && nargo test          # 65 circuit tests (+ 4 minimal, 1 commitment)
cd ../poe-witness && cargo test       # 7 unit tests (+ roundtrip integration)
cd ../poe-validator && pytest tests/  # 19 validator tests (including E2E)
```

### Usage

```python
from poe import PoEProver, PoEConfig

config = PoEConfig.from_poe_root("~/poe-bittensor")
prover = PoEProver(config, validator_id=your_uid)

# In your forward() loop, after scoring each miner:
prover.add_evaluation(uid=miner_uid, response_bytes=response, score=score)

# Before set_weights():
proof = prover.prove(epoch=current_epoch, challenge_nonce=nonce)
# proof.proof_bytes is your 14KB ZK proof
prover.reset()  # Clear for next epoch
```

## Optimization Highlights

The circuit achieved an **79% gate reduction** (37,443 to 7,845) through two techniques:

1. **Range check substitution**: `Field.lt()` costs ~435 gates per call in UltraHonk (254-bit field decomposition). `assert_max_bit_size::<N>()` costs ~ceil(N/14) gates (UltraHonk lookup tables). Replacing 66 `Field.lt()` calls saved ~28K gates.

2. **Preimage packing**: Miner UIDs and weights are u16 values. Packing 15 per Field element reduced Poseidon2 preimage from 197 to 79 elements, saving ~3K gates.

These techniques apply to **any** Noir circuit on the UltraHonk backend.

## Architecture

- **Noir circuits** on Barretenberg UltraHonk (no trusted setup)
- **Poseidon2** for in-circuit hashing, **BLAKE3** for off-circuit response hashing
- **Commit-Reveal v4** compatible weight normalization (sum-normalized u16)
- **zkVerify** integration for trustless on-chain proof attestation
- **TLA+** formally verified: copiers cannot produce valid proofs, honest validators always accepted

## Full Specification

See [SPEC.md](SPEC.md) for the complete protocol specification, including:
- Feasibility analysis and gate budgets
- 9-piece implementation plan
- Subnet compatibility matrix (SN1, SN2, SN8, SN9, SN19)
- Testnet validation plan
- Dynamic TAO survival strategy
