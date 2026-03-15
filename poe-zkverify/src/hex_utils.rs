//! Hex encoding utilities for zkVerify API.
//!
//! zkVerify expects 0x-prefixed lowercase hex strings.

use crate::types::{Result, ZkVerifyError};

/// Encode raw bytes to 0x-prefixed lowercase hex string.
pub fn bytes_to_hex(data: &[u8]) -> String {
    format!("0x{}", hex::encode(data))
}

/// Decode 0x-prefixed hex string to bytes.
pub fn hex_to_bytes(hex_str: &str) -> Result<Vec<u8>> {
    let stripped = hex_str.strip_prefix("0x").unwrap_or(hex_str);
    hex::decode(stripped).map_err(|e| ZkVerifyError::Hex(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bytes_to_hex_empty() {
        assert_eq!(bytes_to_hex(&[]), "0x");
    }

    #[test]
    fn test_bytes_to_hex_data() {
        assert_eq!(bytes_to_hex(&[0xde, 0xad, 0xbe, 0xef]), "0xdeadbeef");
    }

    #[test]
    fn test_bytes_to_hex_lowercase() {
        let result = bytes_to_hex(&[0xAB, 0xCD]);
        assert_eq!(result, "0xabcd");
    }

    #[test]
    fn test_hex_to_bytes_with_prefix() {
        let result = hex_to_bytes("0xdeadbeef").unwrap();
        assert_eq!(result, vec![0xde, 0xad, 0xbe, 0xef]);
    }

    #[test]
    fn test_hex_to_bytes_without_prefix() {
        let result = hex_to_bytes("cafebabe").unwrap();
        assert_eq!(result, vec![0xca, 0xfe, 0xba, 0xbe]);
    }

    #[test]
    fn test_roundtrip() {
        let original = vec![0u8; 14244]; // Proof-sized
        let hex_str = bytes_to_hex(&original);
        let decoded = hex_to_bytes(&hex_str).unwrap();
        assert_eq!(original, decoded);
    }

    #[test]
    fn test_roundtrip_random_like() {
        let original: Vec<u8> = (0..=255).cycle().take(1000).collect();
        let hex_str = bytes_to_hex(&original);
        assert!(hex_str.starts_with("0x"));
        let decoded = hex_to_bytes(&hex_str).unwrap();
        assert_eq!(original, decoded);
    }

    #[test]
    fn test_invalid_hex() {
        assert!(hex_to_bytes("0xzzzz").is_err());
    }

    #[test]
    fn test_odd_length_hex() {
        assert!(hex_to_bytes("0xabc").is_err());
    }
}
