# Proof-of-Evaluation (PoE) Protocol for Bittensor

## Status: Design Spec v1.0 — Build-Ready

## Author: Carson (lamb356)

## Date: March 2026

---

## Table of Contents

0. What We're Building (Plain English)
1. Problem Statement
2. Feasibility Analysis
3. Architecture
4. The PoE Circuit
5. Integration Strategy
6. Implementation Plan (9 Pieces)
7. Testnet Validation Plan
8. Dynamic TAO Survival Strategy
9. Governance & Adoption Path
10. Open Research Questions
11. Competitive Landscape
12. Risk Assessment
13. References
14. CLAUDE.md Snippet

---

## 0. What We're Building (Plain English)

Bittensor is a decentralized AI network. Miners do AI work (run models, generate text, pretrain, trade). Validators grade that work and submit scores to the blockchain. The blockchain pays everyone based on those scores.

The problem: validators can cheat. Instead of actually grading miners, they copy the scores that other validators already submitted. They get paid the same — sometimes more — for doing zero work. This is called **weight copying**, and it drains money from every honest participant in the network.

The existing fix (Commit-Reveal) hides scores temporarily, but it doesn't prove anyone actually did the grading. On stable subnets where miner performance doesn't change much, a cheater can still predict what scores should look like and copy them.

**Our fix: Proof-of-Evaluation (PoE)**

We're building a ZK (zero-knowledge) circuit that forces validators to prove they did the work. Before submitting scores, a validator generates a cryptographic proof that says:

> "I received responses from these specific miners, I computed scores from those responses, and here are the weights I derived from those scores — all for this specific epoch."

A cheater can't produce this proof because they never talked to the miners. They don't have the inputs. The proof is mathematically impossible to fake.

**How it works, step by step:**

1. At the start of each 72-minute epoch, the chain publishes a random challenge number (from the Drand beacon)
2. The validator queries miners, who incorporate the challenge into their responses
3. The validator BLAKE3-hashes each response, scores them, and normalizes scores into a weight vector
4. The validator feeds all of this into a Noir ZK circuit that produces a ~7.7 KB proof in under 60 seconds
5. The proof is submitted alongside the weight commitment
6. Other validators (or zkVerify) verify the proof before accepting the weights into consensus
7. Validators without valid proofs get penalized or rejected

The proof uses Poseidon hashing inside the circuit (cheap in ZK, ~240 constraints per hash) and BLAKE3 outside the circuit (fast native hashing for miner responses). The UltraHonk backend means no trusted setup is required — critical for a protocol that needs network-wide adoption.

**What this becomes:**

Phase 1-2: A tool validators install voluntarily. Subnets can choose to require it.

Phase 3: Bridged to zkVerify (a dedicated ZK verification blockchain) for trustless proof checking.

Phase 5: Proposed as a chain-level requirement via Bittensor governance (BIT proposal).

Long-term: Combined with Inference Labs' SN2 (which proves miners computed correctly), this creates an end-to-end verifiable AI pipeline — miners prove their inference, validators prove their evaluation.

---

## 1. Problem Statement

### 1.1 What Weight Copying Is

In Bittensor, validators score miners and submit weight vectors to the chain. Yuma Consensus (YC) rewards agreement among validators via stake-weighted median consensus. This creates a perverse incentive: a validator can skip evaluation entirely, copy the previous epoch's consensus weights, and earn dividends equal to — or exceeding — honest validators.

The economic math is simple. Copiers achieve higher vtrust scores by computing weights that maximize predicted consensus alignment. Higher vtrust means higher dividends per TAO staked, which means higher APY. If copying is more profitable than honest validation, game-theoretic equilibrium drives all rational actors toward copying. The result: fewer validators perform genuine evaluation, subnet quality degrades, and emissions are captured by free-riders.

### 1.2 Why Current Solutions Don't Solve It

**Commit-Reveal v4 (Drand Time-Lock)**

CR4 uses the Drand decentralized random beacon for time-lock encryption. Weights are encrypted on-chain and cannot be decrypted until a designated Drand round. The `commit_reveal_period` hyperparameter controls the number of tempos weights remain concealed. Automatic reveal eliminates the manual reveal step and prevents selective revelation attacks.

CR4 fails when:
- **Static miners**: If miner performance is stable across tempos, stale weights are still accurate. Copiers suffer no penalty.
- **Low churn subnets**: Subnets with few registration/deregistration events give copiers the same information as honest validators after the reveal.
- **Partial copying**: A copier can evaluate 10% of miners (new registrations) and copy the rest from revealed consensus, blending copied and original weights.

**Liquid Alpha 2 (Consensus-Based Weights)**

Changes how the EMA for validator bonds is calculated. Adjusts bond growth rate to penalize late-arriving (likely copied) weights. Can be gamed with delayed but still copied weights — it's a timing heuristic, not a proof of computation.

**Community Proposals (Similarity Tax, Uniqueness Factor)**

Score each validator 0-1 based on correlation with other validators' weight vectors. Penalize high-similarity submissions. Fundamental flaw: this penalizes honest validators who legitimately agree with consensus, not just copiers.

### 1.3 Gap Analysis

| Solution | What It Proves | What It Doesn't Prove |
|---|---|---|
| Commit-Reveal v4 | Weight submission timing | That evaluation was performed |
| Liquid Alpha 2 | Weight freshness via bond penalty | That weights weren't derived from others' weights |
| Similarity Tax | Weight uniqueness | That unique weights came from real evaluation |
| **PoE (this project)** | **Evaluation function was executed on miner outputs** | — |

### 1.4 What PoE Adds

Proof-of-Evaluation requires validators to produce a cryptographic proof that they:

1. **Received** specific miner outputs (input commitment)
2. **Executed** the evaluation function on those outputs (computation proof)
3. **Derived** their weight vector from the evaluation results (output binding)

A weight copier cannot produce this proof because they never received or evaluated the miner outputs. The proof is submitted alongside the weight commitment and verified before weights are accepted into Yuma Consensus.

PoE complements Commit-Reveal — CR4 hides timing, PoE proves computation. Together they form a two-layer defense.

---

## 2. Feasibility Analysis

### 2.1 The Time Budget

- **Tempo**: 360 blocks × 12 seconds = **4,320 seconds (~72 minutes)**
- Validators evaluate miners continuously during a tempo and submit weights near the end
- With CR4, the commit window occupies the last 10 blocks of each tempo
- **Available proving time**: ~5-15 minutes is realistic (validators need the rest for actual evaluation)
- **Target proving time**: < 300 seconds (5 minutes) for the PoE proof

### 2.2 Noir/Barretenberg Proving Performance (UltraHonk)

Benchmarks from noir-benchmarks (Nargo 1.0.0-beta.0, bb 0.63.0, Intel i7-13700HX) and noir-plume (M2 Max):

| Circuit Size (gates) | Prove Time (UltraHonk) | Platform |
|---|---|---|
| 2^14 (~16K) | 0.77s | i7-13700HX |
| 2^16 (~65K) | 1.73s | i7-13700HX |
| 2^17 (~131K) | 2.96s | i7-13700HX |
| 2^18 (~262K) | 5.43s | i7-13700HX |
| 2^19 (~524K) | 10.33s | i7-13700HX |
| 2^20 (~1M) | 20.26s | i7-13700HX |
| 2^21 (~2M) | 39.53s | i7-13700HX |
| 2^22 (~4M) | 77.39s | i7-13700HX |

Key reference points:
- zkFOCIL (BN254 scalar muls): 55K gates → 1.3s prove (UltraHonk, Xeon 8-core)
- Noir PLUME (ECDSA + hashing): 131K ACIR opcodes → 4.7s prove (UltraHonk, M2 Max)
- Noir PLUME: 170K ACIR opcodes → 13.25s prove (UltraHonk, M2 Max)
- Keccak256 × 100: 1.7M gates → 18.3s prove (UltraHonk, i7-13700HX)
- Verification is constant at ~42-49ms regardless of circuit size

**Conclusion**: A PoE circuit at 2^19 to 2^20 gates (500K-1M) proves in 10-20 seconds, well within the 5-minute budget. This is our gate budget.

### 2.3 ZKP System Comparison

| System | 10K Gates | 100K Gates | 1M Gates | Verify | Proof Size | Trusted Setup |
|---|---|---|---|---|---|---|
| Groth16 | 1.4s | 3.2s | 28s | 3.1ms | 192 B | Yes (circuit-specific) |
| PLONK | 2.1s | 4.8s | 42s | 5.2ms | 576 B | Universal |
| STARK | 0.8s | 1.8s | 9.2s | 18ms | 42 KB | No |
| Halo2 | — | 5.4s | — | 12.1ms | 1.2 KB | No |
| Nova | 0.2s/step | 0.4s/step | 1.1s/step | 22ms | 10 KB | No |
| **UltraHonk** | ~0.8s | ~2.9s | ~20s | ~45ms | ~7.7 KB | **No** |

**Decision**: UltraHonk (PLONK family) via Noir/Barretenberg. No trusted setup, sub-KB proof size, sub-50ms verification, mature toolchain. The no-trusted-setup property is critical — a circuit-specific trusted setup for a protocol that must be adopted network-wide is a non-starter politically.

### 2.4 GPU Acceleration Path (ICICLE)

Not needed for Phase 1, but available for complex evaluation circuits hitting 1M+ gates:

| Operation | GPU Speedup | Notes |
|---|---|---|
| MSM (Multi-Scalar Mult.) | 8-10× | Primary bottleneck in CPU provers |
| NTT (Number-Theoretic Transform) | 3-5× | Becomes bottleneck post-MSM optimization |
| Overall proof generation | ~4× | End-to-end with ICICLE backend |

ICICLE supports BLS12-377, BW6-761, and BN254 curves with multi-GPU capability. Requires CUDA 12.0+. At 4× speedup, a 1M-gate circuit drops from 20s to ~5s — keeping even complex evaluation circuits well within budget.

Amdahl's Law constraint: if 80% of prover time is in MSM/NTT (optimizable), maximum theoretical speedup is 5×. Realistic gains are 3-4×.

### 2.5 In-Circuit Hash Costs

| Hash Function | ZK Cost (relative to Poseidon) | R1CS Constraints | Notes |
|---|---|---|---|
| **Poseidon** | **1× (baseline)** | **~240** | **Best established; recommended for PoE** |
| Poseidon2 | ~0.8× | — | Optimized variant; less field-tested |
| Griffin | ~0.4× | 96 | Fewer constraints but less production track record |
| Anemoi | ~Griffin | — | Advantages in PLONKish/AIR systems |
| SHA-256 | ~20× | ~25,000+ | Standard but extremely expensive in ZK |
| BLAKE3 | ~20× vs Poseidon | — | Fast natively; slow in-circuit |

**Decision**: Poseidon for all in-circuit hashing. BLAKE3 is used off-circuit for hashing miner responses — the circuit only needs to commit to the BLAKE3 digest as a Field element, not recompute it. This leverages our BLAKE3 WASM expertise for the off-circuit layer while using the ZK-optimal hash in-circuit.

### 2.6 ZK Cost Trajectory

ZK proving costs have dropped ~40× in three years:

| Year | Cost per Proof | Overhead vs Native |
|---|---|---|
| 2022 | — | ~1,000,000× |
| 2023 | ~$2.00 | 100,000-1,000,000× |
| 2025-2026 | ~$0.05 | 10,000-100,000× |

At $0.05/proof, a validator generating one proof per tempo (~72 min) pays ~$1/day. This is negligible relative to staking returns.

---

## 3. Architecture

### 3.1 System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        VALIDATOR NODE                             │
│                                                                   │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────────┐ │
│  │  Evaluation  │───▶│  PoE Witness │───▶│  Noir Prover         │ │
│  │  Engine      │    │  Generator   │    │  (Barretenberg       │ │
│  │  (Python)    │    │  (Rust bin)  │    │   UltraHonk backend) │ │
│  └─────────────┘    └──────────────┘    └──────────┬───────────┘ │
│        │                                            │             │
│        │ BLAKE3 hashes                    PoE Proof (~7.7 KB)    │
│        │ miner responses                            │             │
│        ▼                                            ▼             │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Weight Submission Pipeline                                  │ │
│  │  commit_weights(encrypted_weights, poe_proof_hash)           │ │
│  │  + publish proof to shared storage (R2/IPFS)                 │ │
│  └───────────────────────────┬─────────────────────────────────┘ │
└──────────────────────────────┼───────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                     ▼
┌──────────────────┐ ┌─────────────────┐ ┌──────────────────────┐
│  SUBTENSOR CHAIN │ │  PEER VALIDATORS │ │  zkVERIFY CHAIN      │
│                  │ │                  │ │  (Phase 2+)          │
│  Stores weight   │ │  Verify proofs   │ │  UltraHonk verifier  │
│  commitments +   │ │  from shared     │ │  Proof aggregation   │
│  proof hashes    │ │  storage         │ │  Merkle root         │
│                  │ │  Penalize non-   │ │  attestations        │
│  Yuma Consensus  │ │  compliant via   │ │                      │
│  (existing)      │ │  incentive mech  │ │  submit_proof →      │
│                  │ │                  │ │  verify_proof →      │
│                  │ │                  │ │  aggregate →         │
│                  │ │                  │ │  Merkle root         │
└──────────────────┘ └─────────────────┘ └──────────────────────┘

          PHASE 1-2                          PHASE 3+
    (No chain changes)              (Bridge to zkVerify or
                                     Subtensor pallet)
```

### 3.2 Yuma Consensus Integration Points

The YC algorithm runs in `run_epoch.rs` through 8 sequential stages. PoE hooks into the pipeline at two points:

**Hook 1: Pre-submission (Validator-side)**
After the validator completes evaluation and before calling `set_weights()`, the PoE prover generates a proof binding the evaluation inputs to the weight vector. The proof hash is included in the weight commitment.

**Hook 2: Post-reveal (Verification)**
When weights are revealed at the Drand unlock, the PoE proof is verified. Weights without valid proofs are either rejected (hard mode) or penalized via reduced vtrust (soft mode).

### 3.3 Key Subtensor Internals

Weight submission uses `set_weights(wallet, netuid, uids, weights, version_key)`. With CR4 enabled, the chain automatically encrypts and commits. Weights are normalized (uid, weight) pairs summing to 1.

Validator permits require top 64 by emissions/stake per subnet and minimum 1,000 stake weight. Stake weight formula:

```
Stake Weight = α + 0.18 × τ
```

Where α = Alpha stake (subnet-specific), τ = TAO stake, 0.18 = TAO weight parameter (adjustable per subnet).

Bonding updates each epoch via EMA:

```
B_ij(t) = α · ΔB_ij + (1 - α) · B_ij(t-1)
```

Emission split: 18% subnet owner, 41% validators (dividends), 41% miners (incentives).

---

## 4. The PoE Circuit

### 4.1 Circuit Interface (Noir)

```noir
// PoE Circuit — proves honest evaluation of miners
// Backend: Barretenberg UltraHonk (no trusted setup)

// Public inputs (visible to verifier, committed on-chain)
struct PoEPublicInputs {
    weight_commitment: Field,       // Poseidon hash of normalized weights
    input_commitment: Field,        // Poseidon hash of all (miner_uid, response_hash) pairs
    epoch: u64,                     // Tempo/epoch number (prevents replay)
    validator_id: Field,            // Poseidon(hotkey_bytes || epoch) — binds proof to identity
    eval_circuit_id: Field,         // Subnet-specific evaluation circuit ID (versioned)
    challenge_nonce: Field,         // Drand-derived nonce for this epoch
}

// Private inputs (known only to prover/validator)
struct PoEPrivateInputs<N> {
    miner_uids: [u16; N],
    response_hashes: [Field; N],    // BLAKE3 hash of each miner's response, cast to Field
    raw_scores: [Field; N],         // Scores before normalization
    weights: [u16; N],              // Normalized weights (u16 per Bittensor format)
    salt: Field,                    // Commitment salt
}
```

### 4.2 Circuit Constraints

```
CONSTRAINT 1: Input Commitment Binding
  input_commitment == Poseidon(
    miner_uids[0] || response_hashes[0] ||
    ... ||
    miner_uids[N-1] || response_hashes[N-1] ||
    challenge_nonce || epoch || salt
  )

  Purpose: Proves the validator had access to specific miner responses
  for this specific epoch. The challenge_nonce ties the commitment to
  an unpredictable Drand output, preventing pre-computation.

CONSTRAINT 2: Score Computation (subnet-specific, pluggable)
  FOR each miner i:
    raw_scores[i] == EvalFunction(response_hashes[i], <subnet_params>)

  This is the pluggable module. Complexity varies by subnet:
    - Arithmetic scoring: ~1-5 gates per miner
    - Comparison scoring: ~10 gates per miner
    - Distance scoring (edit distance, IoU): ~2,000 gates per miner
    - ML-based scoring: INFEASIBLE — use Lite PoE (Section 4.4)

CONSTRAINT 3: Weight Derivation
  total = SUM(raw_scores)
  FOR each miner i:
    weights[i] == (raw_scores[i] * 65535) / total   // u16 normalization

  Purpose: Proves weights are a deterministic function of scores.
  A copier who fabricated scores would need to reverse-engineer
  scores that produce the copied weight vector — computationally
  expensive and detectable via score distribution analysis.

CONSTRAINT 4: Weight Commitment Binding
  weight_commitment == Poseidon(
    weights[0] || weights[1] || ... || weights[N-1] ||
    validator_id || epoch
  )

  Purpose: Cryptographically binds the proof to a specific weight
  vector. Changing even one weight invalidates the proof.

CONSTRAINT 5: Validator Identity
  validator_id == Poseidon(hotkey_bytes || epoch)

  Purpose: Binds proof to a specific validator. Prevents proof
  sharing between validators (a validator can't use another's proof).
```

### 4.3 Gate Count Estimates

**Simple evaluation (arithmetic scoring):**

| Constraint | Gates/Miner | 64 Miners | 256 Miners |
|---|---|---|---|
| Input commitment (Poseidon) | ~300 | ~19K | ~77K |
| Simple score computation | ~20 | ~1.3K | ~5K |
| Weight normalization | ~50 | ~3.2K | ~13K |
| Weight commitment (Poseidon) | ~300 | ~19K | ~77K |
| Validator identity | — | ~300 | ~300 |
| Challenge nonce binding | — | ~240 | ~240 |
| **TOTAL** | | **~43K** | **~172K** |
| **Proving time (UltraHonk)** | | **~1s** | **~3s** |

**Medium evaluation (edit distance, IoU):**

| Constraint | Gates/Miner | 64 Miners | 256 Miners |
|---|---|---|---|
| Input commitment | ~300 | ~19K | ~77K |
| Edit distance scoring | ~2,000 | ~128K | ~512K |
| Weight normalization | ~50 | ~3.2K | ~13K |
| Weight commitment | ~300 | ~19K | ~77K |
| Identity + challenge | — | ~540 | ~540 |
| **TOTAL** | | **~170K** | **~680K** |
| **Proving time (UltraHonk)** | | **~3s** | **~10s** |

Both are well within the 5-minute budget. Even 256-miner medium-complexity circuits prove in 10 seconds.

### 4.4 Lite PoE (for Complex Subnets)

Subnets like Templar (SN3) where evaluation involves ML inference, or subnets that call external APIs, cannot prove the full scoring function in a ZK circuit. Lite PoE proves a weaker but still valuable statement:

**"I received specific miner outputs for this epoch and derived my weights from scores I computed."**

```
LITE POE CONSTRAINTS:
  1. Input commitment binding (same as full PoE — Constraint 1)
  2. Weight commitment binding (same as full PoE — Constraint 4)
  3. Score-to-weight consistency:
     - Prove weights are a valid normalization of SOME set of scores
     - Prove scores are ordered consistently with weights
  4. Validator identity + challenge nonce (Constraints 5, nonce from 1)
  5. NO score computation constraint (Constraint 2 skipped)

Gate count: ~40K for 64 miners → <1s proving
```

This prevents pure weight copying — a copier has no miner responses to commit to and cannot produce a valid input commitment for the current epoch's challenge nonce. It doesn't prevent a validator from fabricating scores, but it forces them to at least query miners and construct a plausible score vector, which is meaningful work.

### 4.5 Challenge-Response Protocol

```
1. EPOCH START (block N):
   Chain emits challenge nonce from Drand beacon:
   challenge_nonce = Drand_output(round_for_block_N)

2. EVALUATION PHASE (blocks N to N+350):
   Validator queries miners. Requests include challenge_nonce.
   Miner responses incorporate challenge_nonce (hash of response includes it).
   Validator evaluates and scores miners.
   Validator BLAKE3-hashes each miner response → response_hashes[].

3. PROOF GENERATION (blocks N+350 to N+358):
   Validator generates PoE proof via Rust prover binary.
   Proof's input_commitment includes challenge_nonce.
   Proves weights derived from responses tied to THIS epoch's challenge.
   Target: <60s for proof generation.

4. SUBMISSION (blocks N+358 to N+360):
   Validator submits: (encrypted_weights, poe_proof_hash) via commit_weights.
   CR4 time-lock encrypts the weights (existing mechanism).
   Full proof published to shared storage (R2/IPFS).
   Proof hash on-chain enables verification.

5. VERIFICATION (next tempo):
   When weights are revealed (Drand unlock):
   - Peer validators fetch proof from shared storage
   - Verify proof against on-chain proof hash
   - Verify public inputs match revealed weights
   - Non-compliant validators: penalized via incentive mechanism
```

The challenge_nonce from Drand is unpredictable, so a copier cannot pre-compute proofs before the epoch starts. The BLAKE3 response hashing ties the proof to actual miner responses.

---

## 5. Integration Strategy

### 5.1 Three Integration Paths

**Path A: Validator Sidecar (Phases 1-2, no chain changes)**

Validators verify each other's PoE proofs via shared storage. Non-compliant validators penalized through the subnet's incentive mechanism. This is the pragmatic first step — zero chain modifications, can be adopted per-subnet.

Pattern:
- Proof published to R2/S3/IPFS alongside weight hash
- Peer validators verify proofs before scoring each other
- Validators without valid PoE proofs receive reduced trust scores
- Subnet owner configures PoE enforcement level (advisory → required)

**Path B: zkVerify Bridge (Phase 3)**

zkVerify is a purpose-built Substrate chain for ZK proof verification, live on mainnet since September 2025. It provides production-grade verifier pallets including UltraHonk (the exact backend we're using).

Architecture flow:
```
Validator → submit_proof(UltraHonk proof) → zkVerify chain
zkVerify → verify_proof → insert_into_queue → try_aggregate
zkVerify → Merkle root attestation → readable from Subtensor
```

Advantages over Path A:
- Verification is trustless (not validator-checking-validator)
- Proof aggregation reduces per-proof on-chain cost
- 2-second block time, millisecond verification latency
- Fee model: `total_price / aggregation_size` — amortized cost decreases with batch

No Subtensor chain changes required. The PoE subnet reads zkVerify attestations to confirm proof validity.

**Path C: Subtensor Pallet (Phase 5, long-term)**

Add a native ZK verification pallet to Subtensor. The pallet-encointer-offline-payment crate provides a complete Groth16-on-Substrate reference pattern:

- Stack: Pure Rust arkworks circuit (ark-r1cs-std), Poseidon hash (ark-crypto-primitives), Groth16 prover (ark-groth16), sp-crypto-ec-utils for Substrate integration
- Pattern: Validator commits evaluation hash → generates ZK proof → submits to pallet → on-chain verification
- Anti-replay: Nullifier system prevents proof reuse

For UltraHonk (our backend), we'd port the Barretenberg verifier to a Substrate pallet, or leverage zkVerify's existing UltraHonk verifier pallet as reference code.

Verification cost: ~50ms per proof × 64 validators = 3.2 seconds per tempo. Feasible but requires governance approval.

### 5.2 Recommended Progression

```
Phase 1-2: Path A (Validator Sidecar)
  → Zero chain risk, prove the concept, build adoption

Phase 3:   Path B (zkVerify Bridge)
  → Trustless verification, no Subtensor changes needed
  → Run sidecar + zkVerify in parallel for redundancy

Phase 5:   Path C (Subtensor Pallet) via governance proposal
  → Tightest integration, proof required for weight acceptance
  → Only pursue after testnet proves value and community demands it
```

### 5.3 Governance Process for Path C

Subtensor governance operates through a bicameral structure:
- **Triumvirate**: 3 members with execution authority
- **Senate**: Top 12 validators by delegated TAO
- **Approval**: 50%+1 Senate approval + Triumvirate close

BIT (Bittensor Improvement Template) process:
1. Fork `opentensor/bits` repo
2. Create `BIT-XXXX.md` with proposal
3. Submit PR → Review → Discussion → Last Call → Finalization
4. Implementation merged into `opentensor/subtensor`

Political strategy: build validator support during Phases 1-3 by demonstrating copier detection. Validators who benefit from honest evaluation will champion the governance proposal. Target Senate members directly.

---

## 6. Implementation Plan (9 Pieces)

### Piece 0: Minimal Circuit — Toolchain Validation (Week 0)

**Goal**: Validate the Noir/Barretenberg toolchain and get **real gate counts** before committing to the full circuit design. This is a stripped-down 8-miner Lite PoE circuit that tests every constraint in isolation. The gate counts from `nargo info` either validate or invalidate the scaling estimates in Section 4.3.

**Status**: COMPLETE. Code in `poe_minimal/`.

**Tech stack**:
- Noir v1.0.0-beta.9 + Barretenberg bb CLI (UltraHonk backend)
- Poseidon2 for variable-length hashing (external dep: `noir-lang/poseidon v0.1.1`)
- 8 miners — intentionally small so compilation and testing are instant

**What the circuit proves** (5 constraints):
1. **Input commitment** — Poseidon2 hash of (miner_uids, response_hashes, epoch, salt) matches public commitment. A copier who never queried miners can't produce this.
2. **Score-to-weight proportionality** — Each weight is the correct floor division of (score × 65535 / total_score). Uses integer division identity in Field arithmetic to avoid expensive range checks.
3. **Weight sum** — Weights sum to 65528-65535 (allowing floor-division rounding slack of up to NUM_MINERS-1).
4. **Weight commitment** — Poseidon2 hash of (weights, validator_id, epoch) matches public commitment. Changing even one weight invalidates the proof.
5. **Validator identity** — validator_id is a public input included in the weight commitment. Different validator = different commitment = proof can't be reused.

**Tests** (4 tests, all must pass):
- `test_honest_validator` — correct inputs produce valid proof
- `test_wrong_weights_rejected` — tampered weights → weight commitment mismatch
- `test_wrong_responses_rejected` — fabricated response hashes → input commitment mismatch
- `test_replay_different_epoch_rejected` — proof from epoch 42 replayed in epoch 43 → fails

**How to run**:
```bash
cd poe_minimal
noirup -v 1.0.0-beta.9 && bbup
chmod +x build.sh && ./build.sh
```

**What to record**:
- Gate count from `nargo info` (expected: 10-20K for 8 miners)
- If gates < 20K → scaling math is validated, proceed to Piece 1 (64 miners)
- If gates > 30K → investigate which constraint is expensive, optimize before scaling

**Deliverables**:
```
poe_minimal/
  Nargo.toml           — Project config + poseidon v0.1.1 dependency
  src/main.nr          — Circuit (5 constraints) + 4 tests (366 lines)
  build.sh             — Compile + gate count + test in one command
  README.md            — Usage and scaling plan
  CLAUDE.md            — Claude Code context
```

### Piece 1: Core Lite PoE Circuit (Week 1-2)

**Goal**: Scale Piece 0 from 8 miners to 64 miners, add Drand challenge nonce binding, split into proper module files, and harden for production use. Gate count targets are calibrated from Piece 0 measurements.

**Prerequisite**: Piece 0 gate counts recorded. If 8-miner circuit was N gates, expect 64-miner circuit to be roughly 8×N (linear scaling from Poseidon2 sponge hashing + per-miner constraints).

**Measured Results** (completed, optimized):
- 64-miner circuit: 374 ACIR opcodes, 5,621 UltraHonk gates
- **85.0% gate reduction** from 37,443 via bounded range checks + UID/weight packing
- Proves in <0.5s on commodity hardware
- All 54 circuit tests pass (including 20 fuzz + 8 adversarial tests)
- Proof size: 14,244 bytes, verification: ~45ms constant

**Optimization Notes** (critical finding for all Noir/UltraHonk circuits):

Field.lt() costs ~435 gates per call in UltraHonk (full 254-bit field decomposition).
assert_max_bit_size::<N>() costs ~ceil(N/14) gates (UltraHonk lookup tables do 14-bit
range checks in 1 gate). Replacing 66 Field.lt() calls with bounded range checks saved ~28K gates.
Packing 64 u16 UIDs into 5 Field elements (and 64 weights into 5) reduced
Poseidon2 preimage from 131+66=197 elements to 72+7=79 elements, saving another ~3K gates. This is the single most impactful optimization for Noir circuits on
UltraHonk backend.

Pattern: Instead of `remainder.lt(bound)`, use:
  1. Constrain the bound to N bits: `bound.assert_max_bit_size::<N>()`
  2. Prove remainder < bound via two range checks:
     - `remainder.assert_max_bit_size::<N>()` (proves 0 <= remainder < 2^N)
     - `(bound - remainder - 1).assert_max_bit_size::<N>()` (proves remainder < bound)

**Scaling projections** (updated with optimized gate counts):
| Miners | Estimated Gates | Proving Time | Notes |
|--------|----------------|-------------|-------|
| 8      | ~1,100         | <0.1s       | Piece 0 minimal |
| 64     | 5,621          | <0.3s       | Piece 1 (measured) |
| 128    | ~11,000        | <0.5s       | Linear extrapolation |
| 256    | ~22,000        | <0.8s       | Full validator capacity |
| 512    | ~44,000        | <1.5s       | Extended capacity |

All within the 500K-1M gate budget with massive headroom. The 72-minute tempo
constraint is trivially met even at 512 miners.

**Tech stack**:
- Noir (latest stable) with Barretenberg UltraHonk backend
- Poseidon for all in-circuit hashing (~240 constraints per hash)
- Target: 64 miners, ~40K gates, <1s proving

**Deliverables**:
```
poe-circuit/
  Nargo.toml
  src/
    main.nr              — Circuit entry point
    types.nr             — PoEPublicInputs, PoEPrivateInputs structs
    commitment.nr        — Input/weight Poseidon commitment logic
    normalization.nr     — Score → weight u16 normalization
    challenge.nr         — Challenge nonce verification
    identity.nr          — Validator hotkey binding
  tests/
    test_commitment.nr   — Commitment correctness
    test_normalization.nr — Weight derivation correctness
    test_full_flow.nr    — End-to-end Lite PoE
    test_replay.nr       — Replay attack prevention (different epoch = different proof)
    test_identity.nr     — Different validator = different proof
```

**Tests**:
- Honest validator produces valid proof
- Modified weight vector → proof fails verification
- Wrong epoch → proof fails
- Wrong validator ID → proof fails
- Wrong challenge nonce → proof fails
- Gate count ≤ 50K for 64 miners
- Proving time ≤ 2s on commodity hardware

**Claude Code entry**: `cd poe-circuit && nargo check && nargo test`

### Piece 2: Rust Witness Generator (Week 2-3)

**Goal**: Rust binary that takes evaluation data (miner UIDs, BLAKE3 response hashes, scores) and produces Noir-compatible witness inputs. This is the bridge between the Python validator and the Noir circuit.

**Tech stack**:
- Rust with blake3 crate for response hashing
- serde + serde_json for witness serialization
- Noir witness format (TOML or JSON depending on Nargo version)

**Deliverables**:
```
poe-witness/
  Cargo.toml
  src/
    lib.rs               — Core witness generation logic
    types.rs             — Rust equivalents of Noir structs
    poseidon.rs          — Native Rust Poseidon (for commitment verification)
    blake3_bridge.rs     — BLAKE3 hash → Field element conversion
    main.rs              — CLI: poe-witness generate --input eval.json --output witness.toml
  tests/
    integration.rs       — Round-trip: generate witness → prove → verify
```

**Interface**:
```rust
pub struct EvaluationData {
    pub miner_uids: Vec<u16>,
    pub responses: Vec<Vec<u8>>,      // Raw miner responses
    pub raw_scores: Vec<f64>,         // Scores before normalization
    pub epoch: u64,
    pub hotkey_bytes: [u8; 32],
    pub challenge_nonce: [u8; 32],    // From Drand beacon
}

pub fn generate_witness(data: &EvaluationData) -> Result<NoirWitness, Error> {
    // 1. BLAKE3 hash each response → response_hashes[]
    // 2. Convert scores to Field elements
    // 3. Normalize scores → u16 weights
    // 4. Compute Poseidon commitments (input + weight)
    // 5. Compute validator_id = Poseidon(hotkey || epoch)
    // 6. Package as Noir witness format
}
```

**Tests**:
- Witness generation produces valid Noir input
- BLAKE3 hash matches between Rust and WASM implementations
- Poseidon commitment matches between Rust native and Noir in-circuit
- Field element encoding is correct for BN254 scalar field

### Piece 3: Reference Evaluation Modules (Week 3-4)

**Goal**: 2-3 pluggable evaluation circuits demonstrating the Full PoE pattern for real subnet types.

**Deliverables**:
```
poe-circuit/
  eval_modules/
    eval_interface.nr     — Trait/interface for pluggable eval functions
    arithmetic_eval.nr    — Portfolio return scoring (SN8-style, ~20 gates/miner)
    distance_eval.nr      — Edit distance + IoU scoring (OCR-style, ~2K gates/miner)
    threshold_eval.nr     — Binary threshold scoring (simple, ~10 gates/miner)
  tests/
    test_arithmetic.nr
    test_distance.nr
    test_threshold.nr
    test_pluggable.nr     — Verify modules plug into main circuit correctly
```

**Key design**: The `eval_interface.nr` defines a Noir trait that subnet developers implement. The PoE shell circuit calls the trait's `evaluate()` method. This is the composability pattern that makes PoE work across subnets.

```noir
// eval_interface.nr — Subnet developers implement this
trait EvalFunction {
    fn evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field;
}
```

#### Subnet PoE Compatibility Matrix| Subnet | Scoring Type | ML Required? | ZK Feasibility | PoE Mode ||--------|-------------|-------------|----------------|----------|| SN2 (Omron) | ZK proof verification + throughput | No | ALREADY ZK | Reference architecture (Proof of Weights in production) || SN8 (Taoshi/PTN) | PnL + risk metrics (arithmetic) | No | HIGH | Full PoE (with price oracle attestation) || SN1 (Apex) | GAN k/N split + legacy ML rewards | Current: No (API) | PARTIAL | Lite PoE (k/N provable; ML scoring needs zkML) || SN9 (Pretraining) | Cross-entropy loss + pairwise win-rate | Yes (3B-14B forward pass) | LOW | Lite PoE only (producing logits infeasible in ZK) || SN19 (Nineteen) | Quality comparison vs reference inference | Yes (32B LLM + SD) | VERY LOW | Lite PoE only (80GB+ model inference) |**Key finding**: SN2 (Omron/Inference Labs) already implements Proof of Weights -- a ZK proof that the scoring function was computed correctly over batches of 1024 events. Their architecture (JSTprove/Expander on BN254) is the direct precursor to PoE. Key patterns to adopt: batch scoring in-circuit, asymmetric decay rates (40% penalty / 10% recovery), and ZK-proven scores overriding incremental scores to close the manipulation loop.**SN8 is the best first Full PoE target**: pure arithmetic scoring (PnL, Sharpe, Sortino -- all standard math), no ML inference required. The only external dependency is a price oracle (Pyth, Chainlink). With attested price data, the entire SN8 scoring pipeline is provable in a Noir circuit.

#### SN8 exp() Approximation Limitations

The SN8 PnL evaluation circuit uses a degree-4 Taylor polynomial to approximate `exp(-0.075*t)` for time-decay weights. This introduces bounded approximation error:

| Day | x = 0.075*t | Taylor Weight | Real Weight | Error |
|-----|-------------|---------------|-------------|-------|
| 0   | 0.000       | 1.000         | 1.000       | 0.0%  |
| 7   | 0.525       | 0.607         | 0.591       | 0.5%  |
| 13  | 0.975       | 0.423         | 0.377       | 1.9%  |
| 20  | 1.500       | 0.273         | 0.223       | 22%   |
| 27+ | >= 2.0      | clamped 0.045 | 0.150       | N/A   |

**Why this is acceptable**: Days 0-13 carry ~75% of total scoring weight in SN8's decay formula, and those are within 2% error. Days 20+ contribute minimal weight regardless of approximation quality.

**When this breaks**: If SN8 changes `decay_rate` from 0.075 to a smaller value (weighting older days more heavily), the Taylor approximation degrades significantly for the now-important late days. V2 should use a piecewise polynomial or lookup table for x in [1.5, 3.0].
### Piece 4: Python Validator Integration Package (Week 4-6)

**Goal**: Python package that validators install alongside their subnet code. Wraps the Rust prover binary and hooks into the Bittensor validator lifecycle.

**Deliverables**:
```
poe-validator/
  poe/
    __init__.py
    prover.py            — Python wrapper around Rust prover binary (subprocess)
    verifier.py          — Verification logic for peer validators
    hooks.py             — Bittensor validator lifecycle hooks
    challenge.py         — Drand challenge nonce fetching
    storage.py           — R2/IPFS proof publishing and retrieval
    config.py            — PoE configuration (enforcement level, storage backend)
  rust/
    (compiled binary from Piece 2, distributed as platform-specific wheels)
  setup.py
  pyproject.toml
```

**Integration with Bittensor SDK**:
```python
# In validator's forward() function — after scoring miners
from poe import PoEProver

prover = PoEProver(
    circuit_path="poe-circuit/target/poe.json",
    hotkey=self.wallet.hotkey,
)

# Collect evaluation evidence during scoring loop
for uid, response in miner_responses.items():
    prover.add_evaluation(
        miner_uid=uid,
        response_bytes=response.serialize(),   # BLAKE3 hashed internally
        raw_score=scores[uid],
    )

# Generate proof (~1-20s depending on circuit complexity)
proof = prover.prove(
    epoch=self.metagraph.block // self.config.tempo,
    challenge_nonce=get_drand_nonce(current_block),
)

# Publish proof to shared storage
proof_hash = prover.publish(proof, bucket=self.config.poe_r2_bucket)

# Set weights as normal — proof_hash included in commitment
self.set_weights(...)
```

**Verification flow for peer validators**:
```python
from poe import PoEVerifier

verifier = PoEVerifier(circuit_vk_path="poe-circuit/target/vk.bin")

for peer_validator in self.metagraph.validators:
    proof = verifier.fetch_proof(peer_validator.hotkey, epoch)
    if proof is None or not verifier.verify(proof, peer_validator.revealed_weights):
        # Penalize: reduce this validator's trust score
        peer_trust[peer_validator.uid] *= POE_PENALTY_FACTOR
```

### Piece 5: Bittensor Subnet Scaffold (Week 6-7)

**Goal**: Fork `opentensor/bittensor-subnet-template` and build the PoE subnet. This is the vehicle for mainnet deployment and emission capture.

**Subnet design**:
- **Miners** = Validators from other subnets who generate PoE proofs
- **Validators** = PoE proof verifiers who check proof validity
- **Incentive**: Miners rewarded for producing valid proofs consistently; penalized for missing proofs or invalid proofs
- **Revenue model**: Other subnets opt-in to PoE verification; the PoE subnet charges for verification service via cross-subnet incentive alignment

**Deliverables**:
```
poe-subnet/
  neurons/
    miner.py             — PoE proof generator (wraps Rust binary)
    validator.py          — PoE proof verifier
  poe/
    (symlink or copy from Piece 4)
  protocol.py            — Synapse definitions for proof submission/verification
  reward.py              — Incentive mechanism (proof validity × timeliness)
  requirements.txt
  setup.py
```

**Alternative deployment**: Instead of a standalone subnet, PoE operates as a service layer. Subnet owners add PoE verification to their validator code directly. Both paths are supported — the subnet scaffold provides the infrastructure for either.

### Piece 6: zkVerify Bridge (Week 7-9)

**Goal**: Integrate with zkVerify for trustless proof verification. Replace the peer-validator verification model with on-chain attestations.

**Architecture**:
```
Validator generates proof (Piece 2)
  → Submit to zkVerify via their submission API
  → zkVerify verifies UltraHonk proof (native verifier pallet)
  → Proof inserted into aggregation queue
  → Merkle root published on zkVerify chain
  → PoE subnet reads Merkle root attestation
  → Validator's proof confirmed valid without peer trust
```

**Deliverables**:
```
poe-zkverify/
  src/
    bridge.rs            — zkVerify submission client
    attestation.rs       — Merkle root attestation reader
    types.rs             — zkVerify API types
  Cargo.toml
```

**Key integration point**: zkVerify's fee model is `total_price / aggregation_size`. Batching 64 validator proofs per tempo amortizes cost significantly. At current rates, this is likely <$0.01 per proof after aggregation.
**Performance optimization target**: This is where pipeline latency actually matters. The BLAKE3 hashing (<1ms) and proof generation (~800ms) are negligible compared to network round-trips for proof submission and attestation reading. Optimization focus for Piece 6: minimize zkVerify submission latency, batch proof aggregation to amortize fees, and evaluate replacing the commitment_helper nargo subprocess with native Rust Poseidon2 (zkhash crate) to eliminate the shell-out overhead. If proof generation needs to drop below 800ms at scale, ICICLE GPU acceleration (8-10x MSM speedup) is the path — not hashing optimization.

### Piece 7: Testnet Campaign (Week 9-11)

**Goal**: Deploy on Bittensor testnet, recruit validators, run 100+ tempos, collect data.

**Deliverables**:
- Testnet deployment scripts
- Monitoring dashboard (proof generation times, verification rates, detection rates)
- Simulated copier agents (automated weight copiers for detection testing)
- Performance report with P50/P95/P99 metrics
- Community feedback document

See Section 7 for detailed testnet plan.

### Piece 8: Mainnet Launch Preparation (Week 11-14)

**Goal**: Prepare for mainnet subnet registration. This includes economic modeling, governance outreach, and documentation.

**Deliverables**:
- Economic model: emission projections, staking demand requirements, deregistration risk analysis
- Governance strategy: identify sympathetic Senate members, prepare BIT draft
- Documentation: validator onboarding guide, subnet owner integration guide, API reference
- Marketing: technical blog post, Bittensor Discord campaign, demo video
- Mainnet registration (requires ~1,000 TAO lock, ~$207-238K at current prices)

---

## 7. Testnet Validation Plan

### 7.1 Local Testing (Pieces 1-4)

```bash
# 1. Spin up local subtensor
git clone https://github.com/opentensor/subtensor.git
cd subtensor && cargo run --release -- --dev

# 2. Register a test subnet
btcli subnet create --wallet.name owner \
  --subtensor.chain_endpoint ws://127.0.0.1:9946

# 3. Register miner + validator
btcli subnet recycle_register --netuid 1 --wallet.name miner \
  --subtensor.chain_endpoint ws://127.0.0.1:9946
btcli subnet recycle_register --netuid 1 --wallet.name validator \
  --subtensor.chain_endpoint ws://127.0.0.1:9946

# 4. Run miner (simple echo miner for testing)
python neurons/miner.py --netuid 1 \
  --subtensor.chain_endpoint ws://127.0.0.1:9946 \
  --wallet.name miner

# 5. Run validator with PoE enabled
python neurons/validator.py --netuid 1 \
  --subtensor.chain_endpoint ws://127.0.0.1:9946 \
  --wallet.name validator --poe.enabled true
```

### 7.2 Testnet Deployment (Pieces 5-7)

1. Deploy on Bittensor testnet (free test TAO from faucet)
2. Recruit 3-5 validators from Bittensor Discord to run PoE-enabled validators
3. Deploy 2-3 simulated copier agents with varying sophistication:
   - **Naive copier**: Copy previous epoch's consensus weights verbatim
   - **Delayed copier**: Copy weights with 1-tempo delay and small perturbations
   - **Partial copier**: Evaluate 10% of miners honestly, copy the rest
4. Run for 100+ tempos measuring all success criteria
5. Publish results and iterate

### 7.3 Success Criteria

| Metric | Target | Rationale |
|---|---|---|
| Proof generation time (P95) | < 60 seconds | Well within 72-min tempo |
| Proof size | < 10 KB | Feasible for shared storage; on-chain if needed |
| Verification time (UltraHonk) | < 100 ms | 64 proofs per tempo < 7 seconds |
| Honest validator pass rate | > 99.9% | Cannot penalize honest validators |
| Naive copier detection rate | > 99% | Must catch pure copiers reliably |
| Partial copier detection rate | > 90% | Harder but critical |
| False positive rate | < 0.1% | Critical for validator adoption |
| Proof generation cost | < $0.10 | Must be negligible vs staking returns |

---

## 8. Dynamic TAO Survival Strategy

Under Dynamic TAO, emissions depend on staking demand and market value of the subnet's alpha token. The subnet with the lowest EMA price gets pruned when a new registration occurs. PoE must maintain sustained utility to avoid deregistration.

### 8.1 Value Proposition for Stakers

Stakers earn returns from subnet emissions. PoE's value proposition to stakers:

1. **Direct utility**: PoE protects the integrity of every subnet that adopts it. If weight copying diverts X% of emissions network-wide, PoE recovers that value for honest participants.
2. **Network effect**: As more subnets adopt PoE, the subnet becomes more valuable — each additional integration increases the verification workload and emission share.
3. **Monopoly position**: ZK proof verification is technically complex. Once PoE is established, competitors face a high barrier to entry.

### 8.2 Staking Demand Drivers

- **Subnet owner partnerships**: Get 3-5 high-value subnets (SN1, SN2, SN8, SN9) to commit to PoE adoption before mainnet launch. Their endorsement drives initial staking demand.
- **Validator economic alignment**: Honest validators benefit from PoE (copiers are penalized, honest validators earn more). Target large staking pools.
- **Emission capture**: If PoE captures even 1% of network attention, the alpha token has sustainable demand.

### 8.3 Deregistration Defense

- **Immunity period**: New subnets receive an immunity period (visible on taostats). Use this window to demonstrate value and build staking base.
- **EMA price floor**: Maintain active engagement and utility to keep EMA price above the deregistration threshold.
- **Fallback**: If mainnet subnet economics are unfavorable, pivot to the service-layer model (PoE as a library that subnet owners integrate directly, no standalone subnet needed).

---

## 9. Governance & Adoption Path

### 9.1 Phased Adoption

**Phase 1-2 (No governance needed)**:
PoE operates entirely as a validator-side tool. Subnet owners can recommend it, individual validators can adopt it. Zero coordination required.

**Phase 3 (Soft governance)**:
PoE subnet registers on mainnet. Cross-subnet incentive alignment means subnets that use PoE verification benefit from higher validation quality. Market forces drive adoption.

**Phase 5 (Hard governance — BIT proposal)**:
If the community demands chain-level PoE enforcement, submit a BIT:

1. Fork `opentensor/bits`
2. Create `BIT-XXXX.md`: "Proof-of-Evaluation: ZK Verification of Validator Computation"
3. Contents: problem statement, protocol spec, benchmark data from testnet, economic analysis
4. Submit PR → community review → discussion period
5. Senate vote: 50%+1 of top 12 validators + Triumvirate close
6. If approved: merge PoE pallet into `opentensor/subtensor`

### 9.2 Political Strategy

- **Build allies during testnet**: Honest high-stake validators who lose emissions to copiers are natural allies. Identify them, give them early access, let them see the copier detection data.
- **Don't fight validators who copy**: Frame PoE as "raising the floor" not "punishing bad actors." The incentive shift should make honest validation more profitable, not make copying more painful. Carrots, not sticks.
- **Demonstrate value with data**: Publish copier detection statistics from testnet. Show how much emission is captured by non-evaluating validators. Make the problem undeniable.

---

## 10. Open Research Questions

### Q1: Composable Evaluation Circuits

Can subnet owners write their evaluation logic in a Noir DSL and have it automatically composed with the PoE shell circuit?

Requirements:
- A Noir trait/interface for evaluation functions (Piece 3 starts this)
- A compilation step that merges the eval circuit with the PoE circuit
- Gate budget management per-subnet
- Versioned circuit IDs so upgrades don't break existing proofs

**Verdict: FEASIBLE.** Noir's numeric generics allow parameterizing the circuit by subnet. Add `subnet_id` as a public input. Subnet owners register their VK on-chain; verifiers look up the correct VK by subnet. No dynamic dispatch needed — each subnet compiles its own circuit variant.

### Q2: Non-Deterministic Evaluation

Some evaluation functions use randomness (e.g., sampling a subset of batches for Templar gradient eval).

Options:
- Commit to the random seed and prove evaluation used that seed
- Accept Lite PoE for non-deterministic subnets
- Define a "deterministic core" (provable) and "stochastic shell" (not provable)

**Verdict: SOLVED.** Commit to a Drand beacon round as the random seed. Derive per-miner randomness via Poseidon PRNG seeded with `Poseidon2(drand_round || miner_uid)`. This is deterministic given the beacon, verifiable in-circuit, and costs ~60K gates for 100 random samples.

**Nonce design note:** For the challenge nonce specifically, we chose deterministic BLAKE3 (`BLAKE3(b"poe-challenge" || epoch_be8)`) over Drand. Rationale: the input commitment already cryptographically binds to actual miner responses, so challenge unpredictability is not needed for security. A copier who predicts the challenge still cannot produce a valid proof without the miner response data. BLAKE3 is simpler (no network dependency, no failure mode from beacon unavailability) and fully deterministic across all nodes. If future analysis shows challenge prediction enables a novel attack vector, switching to Drand is a one-line change in `challenge.py`.

### Q3: External API Calls in Evaluation

Some validators call external APIs (LLM inference, web search) as part of evaluation. The API response is not reproducible.

Options:
- Commit to the API response hash as a private input
- Prove score derivation FROM the API response, not the response itself
- This is Lite PoE with extra commitment granularity

**Verdict: SOLVED (hybrid).** Default to commit-reveal: hash the API response as a private input, prove score derivation from that hash. On random challenge (1-in-k epochs), require the validator to reveal the full API response for spot-check verification. This avoids proving the API call itself while still catching fabrication. Estimated cost: ~390K gates for the score-derivation circuit with response commitment.

### Q4: Recursive Proof Aggregation

Instead of one proof per tempo, validators could produce incremental proofs per miner evaluation and aggregate via recursive verification.

Noir supports recursive proof verification at ~257K gates per verify_proof call. This spreads proving cost over the entire tempo instead of a burst at the end. Worth exploring if per-tempo burst proving becomes a bottleneck for complex circuits.

**Verdict: DO NOT PURSUE.** Benchmarking shows 2,957x overhead vs. direct proving for our current circuit size (~5.8K gates). Recursive verification only becomes viable when the inner circuit exceeds ~200K gates (where the 257K recursive overhead becomes proportionally small). For now, use parallel proving (multiple tempos in flight) and zkVerify's Merkle batching to amortize verification cost. Revisit if circuit complexity grows past 200K gates.

### Q5: ProxyZKP Approach

The ProxyZKP paper (Nature Scientific Reports) proposes polynomial proxy models for verifiable decentralized ML. Instead of proving the full evaluation function, train a small polynomial approximation and prove THAT.

This could dramatically reduce circuit complexity for ML-heavy evaluation functions (SN3, SN9). Worth investigating after the core protocol ships.

**Verdict: NICHE.** Only viable for SN3 gradient integrity checks where a degree-4 polynomial proxy achieves acceptable accuracy. For general evaluation functions, proxy fitting introduces 10-15% accuracy loss that compounds with the approximation errors already present in time-weight decay (see SN8 eval module). Not recommended as a general strategy.

### Q6: ZKVM Alternative (RISC Zero / SP1)

Instead of writing evaluation functions as Noir circuits, run the evaluation function in a ZKVM (RISC Zero or SP1). The ZKVM produces a proof that arbitrary Rust/C code executed correctly.

Tradeoff: ZKVM proofs are larger and slower but support arbitrary computation without circuit design. Could be the path for complex evaluation functions that resist circuit decomposition.

zkVerify already has production verifier pallets for both RISC Zero and SP1, so the verification infrastructure exists.

**Verdict: RECOMMENDED as hybrid strategy.** Use Noir for simple-to-medium evaluation functions (linear scoring, weighted averages, threshold checks — up to ~50K gates). Use SP1 for complex evaluation functions that resist circuit decomposition (ML inference verification, multi-step API pipelines). zkVerify provides unified verification for both proof types, so the on-chain verifier doesn't need to know which prover was used.

### 10.1: Research-Informed Roadmap

Based on the research verdicts above, the following phased roadmap emerges:

**Phase 1 — Current (Testnet Prep)**
- Numeric generics for subnet-parameterized circuits (Q1)
- `subnet_id` as public input for per-subnet VK binding
- On-chain VK registry design (compatible with zkVerify attestation model)

**Phase 2 — Testnet**
- Commit-reveal protocol for API-dependent subnets (Q3)
- Merkle tree for proof batching (replaces per-proof on-chain verification)
- Parallel proving pipeline with zkVerify batching (Q4 alternative)

**Phase 3 — Post-Testnet**
- SP1 prover prototype for complex evaluation functions (Q6)
- Proof-type-agnostic verification layer (Noir + SP1 through zkVerify)
- Drand-seeded Poseidon PRNG for non-deterministic evaluation subnets (Q2)

---

## 11. Competitive Landscape

| Project | What It Does | Limitation | Relationship to PoE |
|---|---|---|---|
| **Commit-Reveal v4** | Temporal hiding via Drand time-lock | Doesn't prove evaluation happened | Complementary — CR4 hides, PoE proves |
| **Liquid Alpha 2** | Bond growth penalty for late weights | Heuristic, doesn't catch sophisticated copiers | Complementary |
| **Inference Labs SN2** | ZK proofs for inference outputs | Proves miners, not validators | Complementary — SN2 proves inference, PoE proves evaluation |
| **Apollo ZKP Subnet** | Collaborative ZK proving cluster | General proving service | Could provide proving infrastructure for PoE |
| **SN1 Apex** | GAN-style evaluation with discriminators | Addresses eval quality, not provability | Orthogonal |
| **SN9 Pretraining** | Continuous benchmark evaluation | PoE could layer on top | Integration target |
| **Reddit "uniqueness tax"** | Similarity penalty | Punishes honest agreement | Replaced by PoE |
| **ZKP-FedEval** (academic) | ZK-verified federated evaluation | Circom-based, not Bittensor-specific | Theoretical validation of PoE approach |

**End-to-end vision**: SN2 proves miners computed inference correctly. PoE proves validators evaluated miners honestly. Together: fully verifiable AI computation pipeline.

---

## 12. Risk Assessment

| Risk | Severity | Probability | Mitigation |
|---|---|---|---|
| Circuit too large for complex eval functions | High | Medium | Lite PoE fallback; pluggable eval modules; ZKVM escape hatch |
| Validator hardware can't run prover | Medium | Low | UltraHonk is CPU-only, no GPU needed; 64GB RAM sufficient for 1M gates |
| Adoption resistance from validators | High | Medium | Start optional; demonstrate copier detection with data; align incentives |
| Subtensor governance rejects chain changes | Medium | Medium | Operate as sidecar/subnet first; Path C is optional, not required |
| Proving backend bugs (Barretenberg) | Low | Low | Well-audited by Aztec; use stable releases; fuzz testing |
| Miner response non-determinism | Medium | Medium | Hash-based commitment; prove derivation, not reproduction |
| Dynamic TAO deregistration | High | Medium | Build staking demand before immunity expires; fallback to service-layer model |
| Mainnet registration cost (~$207-238K) | High | — | Secure backing before registration; testnet proves value first |
| ICICLE GPU acceleration needed but unavailable | Low | Low | CPU proving sufficient for target gate counts; GPU is optimization, not requirement |
| Copiers adapt (partial copying, score fabrication) | Medium | High | Full PoE (not just Lite) catches score fabrication; continuous circuit evolution |

---

## 13. References

### Core Bittensor
- Subtensor Source: https://github.com/opentensor/subtensor
- run_epoch.rs (YC Implementation): https://github.com/opentensor/subtensor/blob/main/pallets/subtensor/src/epoch/run_epoch.rs
- Bittensor SDK: https://github.com/opentensor/bittensor
- Bittensor Documentation: https://docs.learnbittensor.org
- Yuma Consensus Docs: https://docs.learnbittensor.org/learn/yuma-consensus
- Commit-Reveal Docs: https://docs.learnbittensor.org/concepts/commit-reveal
- Weight Copying Docs: https://docs.learnbittensor.org/concepts/weight-copying-in-bittensor
- Weight Copying Blog: https://blog.bittensor.com/weight-copying-in-bittensor-422585ab8fa5
- Consensus-Based Weights Blog: https://blog.bittensor.com/consensus-based-weights-1c5bbb4e029b
- Governance Docs: https://docs.learnbittensor.org/governance
- BITs Repository: https://github.com/opentensor/bits
- Subnet Template: https://github.com/opentensor/bittensor-subnet-template
- TaoStats: https://taostats.io/subnets

### ZK Toolchains & Libraries
- Noir Language: https://noir-lang.org
- Barretenberg (Aztec Backend): https://github.com/AztecProtocol/barretenberg
- ICICLE (GPU Acceleration): https://github.com/ingonyama-zk/icicle
- noir-plume Benchmarks: https://github.com/distributed-lab/noir-plume/blob/main/BENCHMARK.md
- StealthCloud ZKP Benchmarks: https://stealthcloud.ai/data/zero-knowledge-proof-performance-benchmarks/
- zkVerify Documentation: https://docs.zkverify.io/architecture/core-architecture
- pallet-encointer-offline-payment: https://lib.rs/crates/pallet-encointer-offline-payment
- ZK-Plus Hash Benchmarks: https://zk-plus.github.io/tutorials/basics/hashing-algorithms-benchmarks
- TACEO Hash Function Guide: https://core.taceo.io/articles/how-to-choose-your-zk-friendly-hash-function/

### Existing Bittensor Projects
- Inference Labs SN2 Docs: https://sn2-docs.inferencelabs.com/proof-of-inference
- SN2 Technical Roadmap: https://sn2-docs.inferencelabs.com/technical-roadmap
- SN1 Apex (Macrocosmos): https://macrocosmosai.substack.com/p/sn1-apex-introducing-gan-style-activity
- SN9 Pretraining: https://github.com/macrocosm-os/pretraining

### Academic Papers
- ZKP-FedEval: https://arxiv.org/html/2507.11649v1
- ProxyZKP (Nature): https://www.nature.com/articles/s41598-024-79798-x
- ZK Consensus for Blockchain: https://arxiv.org/html/2503.13255v1
- ZKVM Federated Learning: https://pmc.ncbi.nlm.nih.gov/articles/PMC10670442/
- ZKML Survey: https://www.semanticscholar.org/paper/A-Survey-of-Zero-Knowledge-Proof-Based-Verifiable-Peng-Wang/d1bc1ebaf08519f6456686f1e4317adcf978524d
- ZKProphet GPU Analysis: https://arxiv.org/html/2509.22684v1
- Mopro Metal MSM v2: https://zkmopro.org/blog/metal-msm-v2/
- IOTA Architecture (SN9): https://arxiv.org/abs/2507.17766

### Community
- Reddit Weight-Copying Discussion: https://www.reddit.com/r/bittensor_/comments/1rnbg23/possible_solution_for_weight_copying/
- Bittensor Subnet Example: https://github.com/nanlabs/bittensor-subnet-example

---

## 14. CLAUDE.md Snippet

Paste this into the project's CLAUDE.md for Claude Code context:

```markdown
# PoE — Proof-of-Evaluation for Bittensor

## What This Is
ZK protocol that cryptographically proves Bittensor validators actually executed their
evaluation functions on miner outputs, rather than copying weights from other validators.

## Architecture
- Noir circuits (Barretenberg UltraHonk backend, no trusted setup)
- Poseidon hashing in-circuit (~240 constraints/hash), BLAKE3 off-circuit for response hashing
- Rust witness generator bridges Python validator → Noir prover
- Three integration paths: validator sidecar → zkVerify bridge → Subtensor pallet

## Project Structure
- `poe-circuit/` — Noir circuits (Lite PoE + Full PoE + eval modules)
- `poe-witness/` — Rust witness generator + BLAKE3 bridge
- `poe-validator/` — Python package for Bittensor validator integration
- `poe-subnet/` — Bittensor subnet scaffold (fork of subnet-template)
- `poe-zkverify/` — zkVerify bridge client

## Key Constraints
- Gate budget: 500K-1M gates (2^19 to 2^20) → 10-20s proving on UltraHonk
- Tempo: 72 minutes. Proof generation must complete in <60s (target <20s)
- UltraHonk verification: ~45ms constant regardless of circuit size
- Poseidon for in-circuit hashing. NEVER use SHA-256 or BLAKE3 in-circuit (~20x more expensive)
- Field elements are BN254 scalar field

## Build Order
Piece 1: Core Lite PoE circuit (Noir)
Piece 2: Rust witness generator
Piece 3: Reference evaluation modules (pluggable Noir traits)
Piece 4: Python validator integration package
Piece 5: Bittensor subnet scaffold
Piece 6: zkVerify bridge
**TLA+ Formal Verification Results** (completed):
- Model checked with 3 validators, 3 miners, 3 epochs
- 3.1 million states explored, all invariants pass:
  - WeightIntegrity: copiers cannot produce valid proofs
  - Liveness: honest validators always generate valid proofs
  - No deadlocks detected
- TLA+ spec at `tla/PoE.tla`

Piece 7: Testnet campaign
Piece 8: Mainnet launch prep

## Testing
- `cd poe-circuit && nargo test` — circuit tests
- `cd poe-witness && cargo test` — witness generator tests
- `cd poe-validator && pytest` — Python integration tests
- Local subtensor: `cargo run --release -- --dev` in subtensor repo

## Bittensor Context
- Yuma Consensus runs in `run_epoch.rs` (8 stages, deterministic, on-chain)
- Weight submission: `set_weights(wallet, netuid, uids, weights, version_key)`
- CR4 uses Drand time-lock encryption. PoE complements CR4.
- Validator permits: top 64 by emissions/stake, min 1,000 stake weight
- Tempo: 360 blocks × 12s = 72 minutes
- Emission split: 18% owner, 41% validators, 41% miners

## Rules
- BLAKE3 is used OFF-circuit only (response hashing). Poseidon IN-circuit only.
- All proofs use UltraHonk backend (not UltraPlonk — 2.5x slower, no benefit)
- Gate count estimates must be verified against `nargo info` output
- Proof generation time must be benchmarked on commodity hardware (not just M2 Max)
- When communicating with Bittensor community: accuracy over speed, always verify claims
```
