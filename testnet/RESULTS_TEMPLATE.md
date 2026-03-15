# PoE Testnet Campaign Results

## Campaign Configuration

| Parameter | Value |
|-----------|-------|
| Network | testnet / local |
| Netuid | |
| Tempos run | |
| Honest validators | |
| Copier agents | |
| Start time | |
| End time | |

## Success Criteria (from SPEC Section 7.3)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Proof generation time (P95) | < 60 seconds | | |
| Proof size | < 10 KB | | |
| Verification time (P95) | < 100 ms | | |
| Honest validator pass rate | > 99.9% | | |
| Naive copier detection rate | > 99% | | |
| Partial copier detection rate | > 90% | | |
| False positive rate | < 0.1% | | |
| Proof generation cost | < $0.10 | | |

## Proof Generation Performance

| Percentile | Time (ms) |
|------------|-----------|
| P50 | |
| P95 | |
| P99 | |
| Mean | |

## Detection Results

### Naive Copier (copies previous epoch verbatim)

| Metric | Value |
|--------|-------|
| Total tempos | |
| Detected | |
| Missed | |
| Detection rate | |

### Delayed Copier (1-tempo delay + noise)

| Metric | Value |
|--------|-------|
| Total tempos | |
| Detected | |
| Missed | |
| Detection rate | |

### Partial Copier (10% honest, 90% copied)

| Metric | Value |
|--------|-------|
| Total tempos | |
| Detected | |
| Missed | |
| Detection rate | |

## Observations

### What worked well
-

### Issues encountered
-

### Recommendations for mainnet
-

## Raw Data

Campaign report JSON: `testnet/logs/campaign_report.json`
Per-agent logs: `testnet/logs/copier_*.jsonl`, `testnet/logs/honest_*.jsonl`
