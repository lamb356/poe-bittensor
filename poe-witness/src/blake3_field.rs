use num_bigint::BigUint;

/// BN254 scalar field modulus (approximately 2^254)
/// p = 21888242871839275222246405745257275088548364400416034343698204186575808495617
const BN254_MODULUS_HEX: &str = "30644e72e131a029b85045b68181585d2833e84879b9709143e1f593f0000001";

/// BLAKE3 hash raw bytes using XOF mode for 512-bit output, then reduce to BN254 field element.
/// Using 512 bits (double the ~254-bit modulus) ensures modular reduction bias < 2^-250.
/// Returns the field element as a decimal string.
pub fn hash_response_to_field(response: &[u8]) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(response);
    let mut xof = hasher.finalize_xof();
    let mut wide_bytes = [0u8; 64]; // 512 bits
    xof.fill(&mut wide_bytes);

    // Interpret 64 bytes as big-endian unsigned integer
    let hash_int = BigUint::from_bytes_be(&wide_bytes);

    // Reduce modulo BN254 scalar field
    let modulus = BigUint::parse_bytes(BN254_MODULUS_HEX.as_bytes(), 16).unwrap();
    let field_element = hash_int % modulus;

    field_element.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hash_deterministic() {
        let r1 = hash_response_to_field(b"hello miner");
        let r2 = hash_response_to_field(b"hello miner");
        assert_eq!(r1, r2);
    }

    #[test]
    fn test_hash_different_inputs() {
        let r1 = hash_response_to_field(b"response A");
        let r2 = hash_response_to_field(b"response B");
        assert_ne!(r1, r2);
    }

    #[test]
    fn test_hash_within_field() {
        let result = hash_response_to_field(b"test data");
        let val = result.parse::<BigUint>().unwrap();
        let modulus = BigUint::parse_bytes(BN254_MODULUS_HEX.as_bytes(), 16).unwrap();
        assert!(val < modulus);
    }
}
