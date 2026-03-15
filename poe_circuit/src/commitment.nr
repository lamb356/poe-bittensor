use crate::types::NUM_MINERS;
use poseidon::poseidon2::Poseidon2;

// ============================================================
// EXPERIMENT 1: Pack miner UIDs to reduce Poseidon2 preimage size
// UIDs are u16 (0-65535, 16 bits each). Pack 15 UIDs per Field element.
// 64 UIDs -> ceil(64/15) = 5 packed Fields instead of 64.
// Input commitment preimage: 64 hashes + 5 packed UIDs + 3 scalars = 72 elements
// (was: 64 hashes + 64 UIDs + 3 scalars = 131 elements)
// ============================================================

// Pack up to 15 u16 values into a single Field element
// Layout: uid[0] + uid[1]*2^16 + uid[2]*2^32 + ...
fn pack_uids(uids: [Field; NUM_MINERS]) -> [Field; 5] {
    let mut packed: [Field; 5] = [0; 5];
    let shift: Field = 65536; // 2^16
    for chunk in 0..5 {
        let mut val: Field = 0;
        let mut multiplier: Field = 1;
        let base = chunk * 15;
        // Pack up to 15 UIDs (last chunk may have fewer: 64 - 4*15 = 4)
        let count = if chunk < 4 { 15 } else { 4 };
        for j in 0..15 {
            if j < count {
                let idx = base + j;
                if idx < NUM_MINERS {
                    val += uids[idx] * multiplier;
                }
            }
            multiplier *= shift;
        }
        packed[chunk] = val;
    }
    packed
}

pub fn compute_input_commitment(
    miner_uids: [Field; NUM_MINERS],
    response_hashes: [Field; NUM_MINERS],
    challenge_nonce: Field,
    epoch: Field,
    salt: Field,
) -> Field {
    // H-01: Range check UIDs before packing to prevent overflow into adjacent slots
    for i in 0..NUM_MINERS {
        miner_uids[i].assert_max_bit_size::<16>();
    }
    let packed_uids = pack_uids(miner_uids);
    // Preimage: 5 packed UIDs + 64 hashes + 3 scalars = 72 elements
    let preimage_len: u32 = 5 + NUM_MINERS + 3;
    let mut preimage: [Field; 72] = [0; 72];
    for i in 0..5 {
        preimage[i] = packed_uids[i];
    }
    for i in 0..NUM_MINERS {
        preimage[5 + i] = response_hashes[i];
    }
    preimage[5 + NUM_MINERS] = challenge_nonce;
    preimage[5 + NUM_MINERS + 1] = epoch;
    preimage[5 + NUM_MINERS + 2] = salt;
    Poseidon2::hash(preimage, preimage_len)
}

pub fn compute_weight_commitment(
    weights: [Field; NUM_MINERS],
    validator_id: Field,
    epoch: Field,
) -> Field {
    // H-01: Range check weights before packing to prevent overflow into adjacent slots
    for i in 0..NUM_MINERS {
        weights[i].assert_max_bit_size::<16>();
    }
    // Pack weights (u16) same as UIDs: 15 per Field element
    let packed_weights = pack_uids(weights); // same packing function works
    // Preimage: 5 packed weights + validator_id + epoch = 7 elements
    let mut preimage: [Field; 7] = [0; 7];
    for i in 0..5 {
        preimage[i] = packed_weights[i];
    }
    preimage[5] = validator_id;
    preimage[6] = epoch;
    Poseidon2::hash(preimage, 7)
}
