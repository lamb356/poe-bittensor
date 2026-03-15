use poseidon::poseidon2::Poseidon2;

global NUM_MINERS: u32 = 64;
global MAX_WEIGHT: Field = 65535;
global MIN_WEIGHT_SUM: Field = 65472;
global MAX_PARAMS: u32 = 4;

// Arithmetic eval: score = params[0] * response_hash + params[1]
fn arithmetic_evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field {
    params[0] * response_hash + params[1]
}

fn main(
    input_commitment: pub Field,
    weight_commitment: pub Field,
    epoch: pub Field,
    validator_id: pub Field,
    challenge_nonce: pub Field,
    miner_uids: [Field; NUM_MINERS],
    response_hashes: [Field; NUM_MINERS],
    weights: [Field; NUM_MINERS],
    salt: Field,
    eval_params: [Field; MAX_PARAMS],
) {
    // CONSTRAINT 1: Input commitment
    let mut input_preimage: [Field; 2 * NUM_MINERS + 3] = [0; 2 * NUM_MINERS + 3];
    for i in 0..NUM_MINERS {
        input_preimage[i] = miner_uids[i];
        input_preimage[NUM_MINERS + i] = response_hashes[i];
    }
    input_preimage[2 * NUM_MINERS] = challenge_nonce;
    input_preimage[2 * NUM_MINERS + 1] = epoch;
    input_preimage[2 * NUM_MINERS + 2] = salt;
    let computed_ic = Poseidon2::hash(input_preimage, 2 * NUM_MINERS + 3);
    assert(computed_ic == input_commitment, "Input commitment mismatch");

    // CONSTRAINT 2: Score computation (Full PoE)
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        scores[i] = arithmetic_evaluate(response_hashes[i], eval_params);
    }

    // CONSTRAINT 3: Score-to-weight proportionality
    let mut total_score: Field = 0;
    for i in 0..NUM_MINERS {
        total_score += scores[i];
    }
    assert(total_score != 0, "Total score must be nonzero");
    for i in 0..NUM_MINERS {
        let expected_numerator = scores[i] * MAX_WEIGHT;
        let remainder = expected_numerator - weights[i] * total_score;
        assert(remainder.lt(total_score), "Weight proportionality failed");
    }

    // CONSTRAINT 4: Weight sum range check
    let mut weight_sum: Field = 0;
    for i in 0..NUM_MINERS {
        weight_sum += weights[i];
    }
    assert(!weight_sum.lt(MIN_WEIGHT_SUM), "Weight sum too low");
    assert(weight_sum.lt(MAX_WEIGHT + 1), "Weight sum exceeds 65535");

    // CONSTRAINT 5: Weight commitment
    let mut weight_preimage: [Field; NUM_MINERS + 2] = [0; NUM_MINERS + 2];
    for i in 0..NUM_MINERS {
        weight_preimage[i] = weights[i];
    }
    weight_preimage[NUM_MINERS] = validator_id;
    weight_preimage[NUM_MINERS + 1] = epoch;
    let computed_wc = Poseidon2::hash(weight_preimage, NUM_MINERS + 2);
    assert(computed_wc == weight_commitment, "Weight commitment mismatch");
}
