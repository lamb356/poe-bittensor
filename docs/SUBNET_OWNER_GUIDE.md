# Subnet Owner Guide: Integrating PoE

PoE offers two integration modes depending on your subnet's scoring function.

## Lite PoE (Any Subnet, No Code Changes)

Lite PoE proves that validators:
1. Actually queried miners and received responses
2. Derived weights proportionally from their scores
3. Bound the proof to their identity and the current epoch

**It does NOT prove the scoring function itself.** The scores are private inputs — the circuit trusts them but proves everything downstream is honest.

### When to Use Lite PoE

- Your scoring function involves ML inference (too expensive for ZK)
- You want PoE protection without writing Noir code
- You're on a subnet like SN1, SN9, or SN19

### How It Works

Validators install poe-validator and add 3 lines to their forward() loop. No changes to your subnet code. See the [Validator Guide](VALIDATOR_GUIDE.md).

### What Lite PoE Catches

| Attack | Caught? | Why |
|--------|---------|-----|
| Copy previous weights | Yes | No miner responses to commit |
| Replay proof from old epoch | Yes | Epoch + nonce binding |
| Use another validator's proof | Yes | Validator ID binding |
| Evaluate some miners, copy rest | Yes | ALL 64 response hashes committed |
| Evaluate honestly but lie about scores | No | Scores are private inputs |

## Full PoE (Custom Eval Module)

Full PoE proves the scoring function itself was executed correctly in-circuit. Scores are computed inside the ZK circuit, not provided as private inputs.

### When to Use Full PoE

- Your scoring function is pure arithmetic (no ML)
- You want the strongest possible guarantee
- You're on a subnet like SN8 (PnL scoring)

### How It Works

1. Write a Noir eval module implementing the `EvalFunction` trait:

```noir
use crate::eval_modules::interface::{EvalFunction, MAX_PARAMS};

pub struct MySubnetEval;

impl EvalFunction for MySubnetEval {
    fn evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field {
        // Your scoring logic here
        // params[0], params[1], etc. are subnet-specific parameters
        let score = response_hash * params[0] + params[1];
        score
    }
}
```

2. The circuit calls `MySubnetEval::evaluate()` for each miner, computing scores in-circuit.

3. Weights are derived from these in-circuit scores — no way to lie.

### Existing Eval Modules

| Module | File | What It Proves |
|--------|------|---------------|
| `ArithmeticEval` | `arithmetic_eval.nr` | `score = weight * hash + bias` |
| `ThresholdEval` | `threshold_eval.nr` | `score = hash > threshold ? 1 : 0` |
| `DistanceEval` | `distance_eval.nr` | `score = max(0, max_dist - abs(hash - target))` |
| `SN8PnlEval` | `sn8_pnl_eval.nr` | Time-weighted PnL with drawdown check |

### Writing Your Own Eval Module

```noir
// my_eval.nr
use crate::eval_modules::interface::{EvalFunction, MAX_PARAMS};

pub struct MyEval;

impl EvalFunction for MyEval {
    fn evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field {
        // response_hash = BLAKE3(miner_response) mod BN254
        // params = subnet-specific constants (set by witness generator)
        //
        // Return: score as a Field element
        // Use fixed-point arithmetic (scale factor 10^6) for decimals
        //
        // Available helpers:
        //   field_math::fixed_mul(a, b) -> a*b/SCALE
        //   field_math::fixed_div(a, b) -> a*SCALE/b
        //   field_math::exp_neg(x) -> e^(-x) (Taylor degree-4, x < 2.0)

        response_hash  // placeholder
    }
}
```

### Gate Budget

| Eval Complexity | Estimated Gates | Proving Time |
|----------------|-----------------|-------------|
| Simple arithmetic (add/mul) | ~10 per miner | <0.1s |
| Threshold comparison | ~5 per miner | <0.1s |
| Fixed-point division | ~200 per miner | ~0.5s |
| SN8 PnL (30 checkpoints) | ~400 per miner | ~0.8s |

The base Lite PoE circuit is 5,812 gates. Eval modules add gates on top.

## Subnet Compatibility Matrix

| Subnet | Scoring Type | ML Required? | ZK Feasibility | Recommended Mode |
|--------|-------------|-------------|----------------|-----------------|
| SN2 (Omron) | ZK proof verification | No | Already ZK | Reference architecture |
| SN8 (Taoshi) | PnL + risk metrics | No | High | Full PoE |
| SN1 (Apex) | GAN k/N split | Partial | Partial | Lite PoE |
| SN9 (Pretraining) | Cross-entropy loss | Yes | Low | Lite PoE only |
| SN19 (Nineteen) | LLM quality comparison | Yes | Very Low | Lite PoE only |

**Rule of thumb**: If your scoring function uses only arithmetic (add, multiply, compare, divide), Full PoE is feasible. If it requires ML inference, matrix multiplication, or GPU computation, use Lite PoE.

## Deployment

### Option A: Recommend to Validators

Add to your subnet documentation:

```
Validators are encouraged to run PoE proofs alongside their evaluations.
Install: pip install poe-validator
See: https://github.com/lamb356/poe-bittensor/blob/main/docs/VALIDATOR_GUIDE.md
```

### Option B: Enforce in Your Validator Code

Check for PoE proofs from peer validators and penalize those without:

```python
from poe import PoEVerifier, PoEConfig

config = PoEConfig.from_poe_root("~/poe-bittensor")
verifier = PoEVerifier(config)

for peer in self.metagraph.validators:
    proof = fetch_proof(peer.hotkey, epoch)
    if proof is None or not verifier.verify(proof):
        peer_trust[peer.uid] *= 0.5  # Trust penalty
```
