use crate::types::{MAX_WEIGHT, NUM_MINERS};

/// Normalize scores to u16 weights summing to ~65535.
/// Uses floor(score * 65535 / total) — matches Noir circuit's integer division.
pub fn normalize_scores(scores: &[u64]) -> Vec<u64> {
    assert_eq!(scores.len(), NUM_MINERS, "Expected {} scores", NUM_MINERS);

    let total: u64 = scores.iter().sum();
    assert!(total > 0, "Total score must be nonzero");

    scores
        .iter()
        .map(|&s| ((s as u128) * (MAX_WEIGHT as u128) / (total as u128)) as u64)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_basic() {
        let mut scores = vec![100u64; NUM_MINERS];
        scores[0] = 200; // One miner scores double
        let weights = normalize_scores(&scores);

        // All equal scores should get equal weights
        // Total = 100*63 + 200 = 6500
        // weight for 100: floor(100 * 65535 / 6500) = floor(1008.23) = 1008
        // weight for 200: floor(200 * 65535 / 6500) = floor(2016.46) = 2016
        assert_eq!(weights[0], 2016);
        assert_eq!(weights[1], 1008);

        let sum: u64 = weights.iter().sum();
        // Sum should be in [65472, 65535] (floor rounding slack)
        assert!(sum >= 65535 - 63, "Weight sum {} too low", sum);
        assert!(sum <= 65535, "Weight sum {} too high", sum);
    }

    #[test]
    fn test_normalize_uniform() {
        let scores = vec![100u64; NUM_MINERS];
        let weights = normalize_scores(&scores);

        // All equal: floor(100 * 65535 / 6400) = floor(1023.98) = 1023
        for w in &weights {
            assert_eq!(*w, 1023);
        }
        let sum: u64 = weights.iter().sum();
        assert_eq!(sum, 1023 * 64); // 65472
    }

    #[test]
    fn test_normalize_no_u64_overflow() {
        // Scores large enough that s * MAX_WEIGHT would overflow u64
        // (1 << 50) * 65535 > u64::MAX, but u128 handles it
        let mut scores = vec![0u64; NUM_MINERS];
        scores[0] = 1u64 << 50;
        scores[1] = 1u64 << 50;
        let weights = normalize_scores(&scores);
        // Each active miner should get ~32767
        assert!(weights[0] > 32000, "Weight {} too low", weights[0]);
        assert!(weights[0] < 33000, "Weight {} too high", weights[0]);
        // Inactive miners get 0
        assert_eq!(weights[2], 0);
    }

    #[test]
    #[should_panic(expected = "nonzero")]
    fn test_normalize_zero_total() {
        let scores = vec![0u64; NUM_MINERS];
        normalize_scores(&scores);
    }
}
