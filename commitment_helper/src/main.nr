use poseidon::poseidon2::Poseidon2;

global NUM_MINERS: u32 = 64;

// Pack up to 15 u16 values into a single Field element
// Layout: val[0] + val[1]*2^16 + val[2]*2^32 + ...
// Must match poe_circuit/src/commitment.nr pack_uids()
fn pack_u16s(vals: [Field; NUM_MINERS]) -> [Field; 5] {
    let mut packed: [Field; 5] = [0; 5];
    let shift: Field = 65536; // 2^16
    for chunk in 0..5 {
        let mut val: Field = 0;
        let mut multiplier: Field = 1;
        let base = chunk * 15;
        let count = if chunk < 4 { 15 } else { 4 };
        for j in 0..15 {
            if j < count {
                let idx = base + j;
                if idx < NUM_MINERS {
                    val += vals[idx] * multiplier;
                }
            }
            multiplier *= shift;
        }
        packed[chunk] = val;
    }
    packed
}

// Commitment helper: computes and prints Poseidon2 commitments.
// Uses packed UIDs/weights to match poe_circuit commitment scheme.
fn main(
    miner_uids: [Field; NUM_MINERS],
    response_hashes: [Field; NUM_MINERS],
    scores: [Field; NUM_MINERS],
    weights: [Field; NUM_MINERS],
    challenge_nonce: Field,
    epoch: Field,
    validator_id: Field,
    salt: Field,
) {
    // H-01: Range check UIDs before packing
    for i in 0..NUM_MINERS {
        miner_uids[i].assert_max_bit_size::<16>();
    }
    // Pack UIDs (u16) into 5 Field elements
    let packed_uids = pack_u16s(miner_uids);

    // Input commitment: Poseidon2(packed_uids[5] || hashes[64] || nonce || epoch || salt)
    // Preimage: 5 + 64 + 3 = 72 elements
    let mut input_preimage: [Field; 72] = [0; 72];
    for i in 0..5 {
        input_preimage[i] = packed_uids[i];
    }
    for i in 0..NUM_MINERS {
        input_preimage[5 + i] = response_hashes[i];
    }
    input_preimage[5 + NUM_MINERS] = challenge_nonce;
    input_preimage[5 + NUM_MINERS + 1] = epoch;
    input_preimage[5 + NUM_MINERS + 2] = salt;
    let ic = Poseidon2::hash(input_preimage, 72);

    // H-01: Range check weights before packing
    for i in 0..NUM_MINERS {
        weights[i].assert_max_bit_size::<16>();
    }
    // Pack weights (u16) into 5 Field elements
    let packed_weights = pack_u16s(weights);

    // Weight commitment: Poseidon2(packed_weights[5] || validator_id || epoch)
    // Preimage: 5 + 2 = 7 elements
    let mut weight_preimage: [Field; 7] = [0; 7];
    for i in 0..5 {
        weight_preimage[i] = packed_weights[i];
    }
    weight_preimage[5] = validator_id;
    weight_preimage[6] = epoch;
    let wc = Poseidon2::hash(weight_preimage, 7);

    // Suppress unused variable warning
    let _scores_used = scores[0];

    println(f"input_commitment={ic}");
    println(f"weight_commitment={wc}");
}

#[test]
fn test_commitment_helper() {
    let mut uids: [Field; NUM_MINERS] = [0; NUM_MINERS];
    let mut hashes: [Field; NUM_MINERS] = [0; NUM_MINERS];
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        uids[i] = (i + 1) as Field;
        hashes[i] = (i + 101) as Field;
        scores[i] = (50 + (i * 37) % 300) as Field;
    }

    let mut total: Field = 0;
    for i in 0..NUM_MINERS {
        total += scores[i];
    }
    let mut weights: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        weights[i] = (scores[i] * 65535) / total;
    }

    main(
        uids, hashes, scores, weights,
        77777, 42, 12345, 999,
    );
}
