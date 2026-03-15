# BIT-XXXX: Proof-of-Evaluation — ZK Verification of Validator Computation

- **BIT Number:** XXXX
- **Title:** Proof-of-Evaluation (PoE)
- **Author(s):** Carson (@lamb356)
- **Discussions-to:** https://github.com/opentensor/bits/discussions
- **Status:** Draft
- **Type:** Core
- **Created:** 2026-03-14
- **Updated:** 2026-03-14

## Abstract

Proof-of-Evaluation (PoE) is a zero-knowledge protocol that cryptographically proves Bittensor validators actually executed their evaluation functions on miner outputs. Validators generate a compact UltraHonk proof (~14KB, <0.5s) that binds their identity, the miner responses they evaluated, and the weights they submitted. This proof is verifiable in ~45ms without revealing the underlying data. PoE eliminates weight copying — the practice of validators submitting weights derived from other validators' evaluations rather than their own — which currently diverts emissions from honest validators.

## Motivation

Weight copying is Bittensor's most persistent incentive alignment problem. A validator can observe consensus weights from previous epochs and submit similar weights without ever querying miners. This:

1. **Diverts emissions**: Copiers earn validator rewards without performing computation, diluting rewards for honest validators who spend resources on actual evaluation.

2. **Degrades network quality**: If copying is profitable, rational validators are incentivized to copy rather than evaluate, leading to a race to the bottom where fewer validators actually check miner quality.

3. **Undermines subnet integrity**: Subnet owners invest in designing evaluation functions that measure miner performance. Copiers bypass these functions entirely, making the evaluation meaningless.

Existing mitigations (Commit-Reveal v4 with Drand time-lock encryption) address weight *visibility* but not weight *provenance*. CR4 prevents validators from seeing each other's weights before submission, but a copier can still use stale consensus data or partial observations. PoE closes this gap by requiring cryptographic proof that evaluation actually occurred.

### Evidence of the Problem

- Multiple subnet owners have reported weight copying behavior on Bittensor Discord
- Analysis of weight correlation between validators shows suspicious clustering patterns
- Yuma Consensus is designed for honest evaluation — copiers exploit the gap between design and enforcement

## Specification

### Protocol Overview

PoE operates in the validator's forward() loop, between miner evaluation and weight submission:

```
1. Validator queries miners and receives responses
2. Validator scores responses using subnet evaluation function
3. Validator normalizes scores to u16 weights (CR4 sum-normalization)
4. PoE witness generator:
   a. BLAKE3 hashes each miner response -> response_hash[i]
   b. Normalizes scores to u16 weights
   c. Computes Poseidon2 commitments:
      - input_commitment = Poseidon2(packed_uids || response_hashes || nonce || epoch || salt)
      - weight_commitment = Poseidon2(packed_weights || validator_id || epoch)
5. Noir circuit proves:
   a. Input commitment matches the committed data (binding)
   b. Weights are proportional to scores (correctness)
   c. Weight sum is in valid range [65472, 65535] (normalization)
   d. Weight commitment matches the committed weights (binding)
   e. Proof is bound to this validator and this epoch (identity + freshness)
6. Validator submits weights + proof
7. Verifier checks proof in ~45ms
```

### Circuit Specification

| Parameter | Value |
|-----------|-------|
| Backend | UltraHonk (Barretenberg, no trusted setup) |
| Field | BN254 scalar field |
| Circuit size | 5,621 UltraHonk gates (374 ACIR opcodes) |
| Proof size | 14,244 bytes |
| Proving time | <0.5s (64 miners, commodity hardware) |
| Verification time | ~45ms constant |
| In-circuit hash | Poseidon2 (sponge construction) |
| Off-circuit hash | BLAKE3 (response hashing) |

### Public Inputs (5 fields)

1. `input_commitment`: Poseidon2 hash binding miner UIDs, response hashes, challenge nonce, epoch, and salt
2. `weight_commitment`: Poseidon2 hash binding weights, validator ID, and epoch
3. `epoch`: Current epoch number (freshness)
4. `validator_id`: Validator's UID (identity binding)
5. `challenge_nonce`: Unpredictable nonce from Drand beacon (prevents pre-computation)

### Verification Paths

1. **Peer verification**: Other validators check proofs via the `bb verify` CLI (~45ms)
2. **zkVerify attestation**: Proofs submitted to zkVerify chain for trustless on-chain verification
3. **Subtensor pallet** (future): Native PoE pallet in the Subtensor runtime

### Subnet Compatibility

| Subnet | Scoring Type | PoE Mode |
|--------|-------------|----------|
| SN2 (Omron) | ZK proof verification | Reference (already ZK) |
| SN8 (Taoshi) | PnL + risk metrics | Full PoE |
| SN1 (Apex) | GAN k/N split | Lite PoE |
| SN9 (Pretraining) | Cross-entropy loss | Lite PoE only |
| SN19 (Nineteen) | LLM quality comparison | Lite PoE only |

**Lite PoE** proves the weight derivation pipeline (hash responses -> normalize scores -> compute weights). Works for any subnet without modifying the scoring function.

**Full PoE** additionally proves the scoring function itself was executed correctly in-circuit. Requires a Noir eval module per subnet.

## Rationale

### Why ZK Proofs?

Alternative approaches considered:

1. **Trusted execution (TEE/SGX)**: Requires hardware support, centralized trust in Intel/AMD. Single hardware vulnerability compromises the entire system.
2. **Commit-reveal (CR4)**: Already deployed. Prevents weight *visibility* but not weight *provenance*. Copiers use stale data.
3. **Statistical detection**: Heuristic-based, high false positive rate, easily gamed by sophisticated copiers who add noise.
4. **Reputation systems**: Slow convergence, subjective, vulnerable to sybil attacks.

ZK proofs provide the strongest guarantee: mathematical certainty that evaluation occurred, without revealing the evaluation data. The proof is:
- **Sound**: A cheating prover cannot generate a valid proof (computational assumption: discrete log hardness on BN254)
- **Zero-knowledge**: The proof reveals nothing about the miner responses or scores
- **Succinct**: Fixed-size proof (~14KB) regardless of the number of miners evaluated

### Why UltraHonk?

- No trusted setup (unlike Groth16)
- Fast proving (<0.5s for 5,621 gates)
- Constant verification time (~45ms)
- Native support on zkVerify chain
- 2.5x faster than UltraPlonk with equivalent security

### Key Optimization: assert_max_bit_size

The circuit achieved an 85% gate reduction (37,443 to 5,621) by replacing `Field.lt()` comparisons with bounded range checks via `assert_max_bit_size`. This technique exploits UltraHonk's lookup tables: a 14-bit range check costs 1 gate (lookup), while `Field.lt()` costs ~435 gates (254-bit field decomposition). This optimization applies to any Noir circuit on UltraHonk.

## Backwards Compatibility

PoE is fully backwards compatible:

1. **Phase 1 (opt-in)**: Validators install poe-validator package and generate proofs alongside their normal weight submissions. No chain changes required. Non-PoE validators continue operating normally.

2. **Phase 2 (soft enforcement)**: Subnet owners can configure their validators to check PoE proofs from peers and apply trust penalties to validators without valid proofs. This uses existing Bittensor trust/vtrust mechanisms.

3. **Phase 3 (hard enforcement)**: If adopted via BIT, a Subtensor pallet validates PoE proofs on-chain. The `set_weights` extrinsic would accept an optional proof parameter. During a transition period, proofs would be optional (no penalty for missing proofs). After the transition, validators without proofs would receive reduced emissions.

No existing validator code breaks at any phase. PoE is additive.

## Reference Implementation

Complete implementation: https://github.com/lamb356/poe-bittensor

| Component | Location | Tests |
|-----------|----------|-------|
| Noir circuit (5,621 gates) | `poe_circuit/` | 54 tests |
| Rust witness generator | `poe-witness/` | 9 tests |
| Python validator package | `poe-validator/` | 19 tests |
| Bittensor subnet scaffold | `poe-subnet/` | 37 tests |
| zkVerify bridge | `poe-zkverify/` | 22 tests |
| Testnet campaign tools | `testnet/` | 15 tests |
| TLA+ formal verification | `tla/` | 110M states, 0 violations |
| Z3 arithmetic proofs | `tla/` | 6 invariants, all PASS |

**Total: 156+ tests, all passing.**

## Security Considerations

### Proof Soundness

PoE relies on the computational soundness of UltraHonk proofs over BN254. Breaking soundness requires solving the discrete logarithm problem on BN254, which is computationally infeasible with current technology (128-bit security level).

### Adversary Models

The TLA+ spec verifies safety against three copier strategies:
- **Naive copier**: Copies previous consensus weights. Caught because they lack miner response hashes.
- **Replay attack**: Resubmits a proof from a previous epoch. Caught because the proof is bound to the current epoch via challenge_nonce.
- **Proof sharing**: Uses another validator's proof. Caught because the proof is bound to the validator's ID via weight_commitment.

### Potential Attack Vectors

1. **Selective evaluation**: Validator evaluates a subset of miners and fabricates responses for the rest. Mitigated by: response hashes committed via BLAKE3, which is collision-resistant.
2. **Timing attacks**: Validator observes other validators' weights before generating their own proof. Mitigated by: CR4 time-lock encryption hides weights until after the commitment window.
3. **Proof generation DoS**: Attacker submits computationally expensive inputs to slow down proof generation. Mitigated by: circuit is fixed-size (5,621 gates), proving time is bounded.

## Copyright

This document is licensed under [The Unlicense](https://unlicense.org/).
