# Validator Guide: Integrating PoE

This guide shows how to add Proof-of-Evaluation to your Bittensor validator in under 10 minutes.

## Prerequisites

### 1. Noir Toolchain

```bash
# Install noirup (Noir version manager)
curl -L https://raw.githubusercontent.com/noir-lang/noirup/main/install | bash
noirup -v 1.0.0-beta.9

# Install bbup (Barretenberg version manager)
curl -L https://raw.githubusercontent.com/AztecProtocol/aztec-packages/master/barretenberg/bbup/install | bash
bbup -v 0.82.2

# Verify
nargo --version  # >= 1.0.0-beta.9
bb --version     # >= 0.82.2
```

### 2. Rust (for witness generator)

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

## Installation

```bash
# Clone the PoE repository
git clone https://github.com/lamb356/poe-bittensor.git
cd poe-bittensor

# Compile the circuit
cd poe_circuit && nargo compile && cd ..

# Build the witness generator
cd poe-witness && cargo build --release && cd ..

# Install the Python package
cd poe-validator && pip install -e '.[dev]' && cd ..

# Verify everything works
cd poe-validator && pytest tests/test_pipeline.py -v
# Should output: 2 passed
```

## Integration (3 Lines of Code)

Add PoE to your validator's `forward()` function:

```python
from poe import PoEProver, PoEConfig
from poe.challenge import get_mock_nonce  # Use get_drand_nonce in production

# Initialize once (in __init__ or startup)
poe_config = PoEConfig.from_poe_root("/path/to/poe-bittensor")
prover = PoEProver(poe_config, validator_id=self.uid)


# In your forward() loop, after scoring each miner:
def forward(self):
    for uid, response in miner_responses.items():
        score = self.score(response)

        # === ADD THIS LINE ===
        prover.add_evaluation(uid, response.serialize(), score)

        scores[uid] = score

    # Before set_weights:
    # === ADD THESE 2 LINES ===
    nonce = get_mock_nonce(self.current_epoch)  # or get_drand_nonce()
    proof = prover.prove(self.current_epoch, nonce)
    prover.reset()

    # proof.proof_bytes is your ~14KB ZK proof
    # Store it, publish it, or submit to zkVerify
    self.set_weights(...)
```

That's it. Three lines: `add_evaluation`, `prove`, `reset`.

## Configuration

```python
from poe import PoEConfig

# Auto-detect paths from project root
config = PoEConfig.from_poe_root("~/poe-bittensor")

# Or configure manually
config = PoEConfig(
    circuit_dir="/path/to/poe_circuit",
    commitment_helper_dir="/path/to/commitment_helper",
    witness_binary="/path/to/poe-witness/target/release/poe-witness",
    nargo_binary="/home/user/.nargo/bin/nargo",
    bb_binary="/home/user/.bb/bb",
    storage_dir="/tmp/poe-proofs",
    num_miners=64,
)
```

## Proof Storage

By default, proofs are stored locally:

```python
from poe import Storage

storage = Storage(config)
path = storage.publish(proof, epoch=current_epoch)
# Saves to: /tmp/poe-proofs/epoch_42/proof_<validator_id>

# Retrieve later
proof_bytes = storage.retrieve(validator_id=self.uid, epoch=42)
```

## zkVerify Submission (Optional)

For trustless on-chain attestation:

```python
from poe.zkverify import ZkVerifySubmitter, ZkVerifyConfig

zkv_config = ZkVerifyConfig(
    zkverify_binary="/path/to/poe-zkverify/target/release/poe-zkverify",
    api_key="your-zkverify-api-key",
)

submitter = ZkVerifySubmitter(poe_config, zkv_config)

# Generate proof with keccak mode (required for zkVerify)
proof = prover.prove(epoch, nonce, keccak_mode=True)

# Submit (retries automatically within tempo window)
result = submitter.submit_proof(proof.proof_bytes)
print(f"Job ID: {result.job_id}")
```

## Verification

Check your setup:

```bash
cd poe-bittensor

# Run all tests
cd poe_circuit && nargo test          # 54 circuit tests
cd ../poe-witness && cargo test       # 9 witness tests
cd ../poe-validator && pytest tests/  # 19 tests (including E2E prove+verify)
```

## Performance

| Metric | Value |
|--------|-------|
| Proof generation | <0.5s per tempo |
| Proof size | 14,244 bytes |
| Verification | ~45ms |
| Memory | ~200MB peak during proving |
| CPU | Single core, no GPU required |

## Troubleshooting

**"nargo execute failed"**: Circuit not compiled. Run `cd poe_circuit && nargo compile`.

**"bb prove failed"**: Check that `bb` is in your PATH. Run `bb --version`.

**"poe-witness failed"**: Build with `cd poe-witness && cargo build --release`.

**Proof verification fails**: If submitting to zkVerify, use `keccak_mode=True` in `prove()`. zkVerify requires keccak Fiat-Shamir, not the default Poseidon.
