# PoE Economic Model

## The Cost of Weight Copying

### Current State

Weight copying diverts validator emissions from honest evaluators to free-riders. Estimating the scale:

- **Bittensor daily emissions**: ~7,200 TAO/day (1 TAO/block * 7200 blocks/day)
- **Validator share**: 41% = ~2,952 TAO/day
- **If 20% of validators copy**: ~590 TAO/day diverted from honest validators
- **Annual impact**: ~215,000 TAO (~$44-51M at current prices)

Even if the copying rate is lower (5-10%), the annual drain is $11-25M in validator rewards going to non-evaluating validators.

### PoE's Value Capture

PoE eliminates copying, redistributing that value back to honest validators. The value proposition is direct: if you're an honest validator, PoE increases your earnings by removing free-riders from your reward pool.

## Registration Cost

### Subnet Registration

| Parameter | Value |
|-----------|-------|
| Registration lock | ~1,000 TAO (varies by market) |
| At $207-238/TAO | ~$207,000-238,000 |
| Lock duration | Permanent (recovered on deregistration) |

### Is It Worth It?

The registration cost is a lock, not a burn. If the subnet generates sufficient staking demand, the locked TAO continues earning staking rewards. The real cost is opportunity cost.

**Break-even analysis**: If the PoE subnet captures just 0.1% of daily network emissions (7.2 TAO/day), validators and miners on the subnet earn ~2,628 TAO/year. At current prices, this is $544K-625K — well above the registration lock.

## Emission Projections

### Bittensor Emission Model

| Component | Share |
|-----------|-------|
| Subnet owner | 18% |
| Validators | 41% |
| Miners | 41% |

### PoE Subnet Emission Scenarios

| Scenario | Network Attention | Daily Emission | Annual | Break-even |
|----------|------------------|----------------|--------|------------|
| Minimum viable | 0.05% | 3.6 TAO | 1,314 TAO | 2.6 years |
| Moderate adoption | 0.1% | 7.2 TAO | 2,628 TAO | 1.3 years |
| Strong adoption | 0.5% | 36 TAO | 13,140 TAO | 28 days |
| High adoption | 1.0% | 72 TAO | 26,280 TAO | 14 days |

"Network attention" = fraction of total TAO staked on the PoE subnet's alpha token.

### Dynamic TAO Survival

Under Dynamic TAO, the subnet with the lowest EMA price gets pruned when a new registration occurs. PoE must maintain staking demand above the deregistration threshold.

**Defense strategies**:
1. **Immunity period**: New subnets have an immunity window. Use it to demonstrate value.
2. **Partnership commitments**: Get 3-5 high-value subnets to publicly adopt PoE before mainnet registration. Their staking demand provides the initial floor.
3. **Fallback**: If standalone subnet economics are unfavorable, pivot to the service-layer model (PoE as a library, no subnet needed).

## Revenue Model

### How PoE Captures Value

PoE's revenue comes from Bittensor emissions, not user fees. The subnet earns emissions proportional to its staking demand.

**Value loop**:
```
Honest validators earn more with PoE
  -> Honest validators stake on PoE subnet
  -> PoE subnet earns more emissions
  -> PoE subnet token price increases
  -> More staking demand
  -> More emissions
```

### Alternative Revenue (Service Layer)

If operating as a library rather than a subnet:
- No registration cost
- No emissions
- Revenue via: consulting fees, custom eval module development, zkVerify verification fees
- Lower risk, lower reward

## Cost of Running PoE

### Per-Validator Costs

| Item | Cost |
|------|------|
| Proof generation (CPU) | ~$0.001/proof (electricity) |
| zkVerify submission | ~$0.01/proof (after aggregation) |
| Storage (local) | Negligible |
| Total per tempo | ~$0.01 |
| Daily (20 tempos) | ~$0.20 |
| Monthly | ~$6.00 |

### At Scale (64 Validators)

| Item | Monthly |
|------|---------|
| 64 validators x $6/month | $384 |
| zkVerify fees | ~$200 |
| Infrastructure | ~$100 |
| **Total** | **~$684/month** |

## Comparison: Cost of Copying vs Cost of PoE

| Metric | Weight Copying | PoE |
|--------|---------------|-----|
| Annual emission drain | $11-51M (5-20% copying rate) | $0 |
| Per-validator cost | $0 (free-riding) | $6/month |
| Network effect | Negative (degrades quality) | Positive (improves trust) |
| Honest validator ROI | Reduced by copiers | Increased (copiers eliminated) |

**Bottom line**: PoE costs $6/month per validator to eliminate $11-51M/year in emission drain. The cost-benefit ratio is overwhelming.

## Sensitivity Analysis

### What If Copying Is Less Common Than Estimated?

Even at a 1% copying rate, annual emission drain is ~$2.5M. PoE's total annual cost (~$8K) is still 300x less than the value it protects.

### What If TAO Price Drops?

All costs are denominated in TAO, not USD. A 50% price drop halves the USD cost of registration AND halves the emission value — the ratio stays the same. The economics are price-invariant in TAO terms.

### What If zkVerify Fees Increase?

PoE works without zkVerify (peer verification mode). zkVerify is an optimization, not a requirement. If fees become prohibitive, fall back to peer verification at zero marginal cost.
