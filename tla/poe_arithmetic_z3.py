"""Z3 verification of PoE arithmetic invariants.

Verifies:
1. Weight normalization floor division is sound
2. Bounded range check (assert_max_bit_size) preserves Field.lt() semantics
3. UID/weight packing preserves information (no collisions)
"""
from z3 import *

print("=" * 60)
print("PoE Arithmetic Invariants — Z3 Verification")
print("=" * 60)

# BN254 scalar field prime
P = 21888242871839275222246405745257275088548364400416034343698204186575808495617

# ============================================================
# INVARIANT 1: Floor division proportionality
#
# The circuit checks: weight[i] = floor(score[i] * 65535 / total)
# Via: score[i] * 65535 = weight[i] * total + remainder
#      where 0 <= remainder < total
#
# Verify: this uniquely determines weight[i] for any valid scores.
# ============================================================
print("\n--- Invariant 1: Floor division uniqueness ---")

s = Solver()
score, total, weight, remainder = Ints('score total weight remainder')

# Constraints from the circuit
s.add(total > 0)
s.add(score >= 0)
s.add(score * 65535 == weight * total + remainder)
s.add(remainder >= 0)
s.add(remainder < total)

# Try to find a DIFFERENT weight that also satisfies the constraints
weight2, remainder2 = Ints('weight2 remainder2')
s.add(score * 65535 == weight2 * total + remainder2)
s.add(remainder2 >= 0)
s.add(remainder2 < total)
s.add(weight != weight2)  # Must be different

result = s.check()
if result == unsat:
    print("  PASS: Floor division uniquely determines weight")
else:
    print(f"  FAIL: Non-unique weight found: {s.model()}")

# ============================================================
# INVARIANT 2: Bounded range check equivalence
#
# Original: remainder.lt(total)  [Field comparison]
# Optimized: remainder fits in N bits AND (total - remainder - 1) fits in N bits
#
# Verify: for any N-bit bounded total, the two approaches are equivalent.
# ============================================================
print("\n--- Invariant 2: Range check equivalence ---")

N = 48  # TOTAL_SCORE_BITS in the circuit
BOUND = 2**N

s2 = Solver()
rem, tot = Ints('rem tot')

# Assume total is bounded
s2.add(tot > 0)
s2.add(tot < BOUND)

# The optimized check: rem in [0, 2^N) AND (tot - rem - 1) in [0, 2^N)
# Verify this implies rem < tot (the original check)
s2.add(rem >= 0)
s2.add(rem < BOUND)
s2.add(tot - rem - 1 >= 0)
s2.add(tot - rem - 1 < BOUND)

# Try to violate: rem >= tot
s2.add(rem >= tot)

result = s2.check()
if result == unsat:
    print(f"  PASS: Bounded range check (N={N}) equivalent to Field.lt()")
else:
    print(f"  FAIL: Counterexample: {s2.model()}")

# Also verify the reverse: if rem < tot, then the range checks pass
print("\n--- Invariant 2b: Reverse direction ---")
s2b = Solver()
rem2, tot2 = Ints('rem2 tot2')
s2b.add(tot2 > 0)
s2b.add(tot2 < BOUND)
s2b.add(rem2 >= 0)
s2b.add(rem2 < tot2)

# Try to violate: range check fails
s2b.add(Or(
    rem2 >= BOUND,
    rem2 < 0,
    tot2 - rem2 - 1 >= BOUND,
    tot2 - rem2 - 1 < 0,
))

result = s2b.check()
if result == unsat:
    print(f"  PASS: rem < tot implies range checks pass (N={N})")
else:
    print(f"  FAIL: Counterexample: {s2b.model()}")

# ============================================================
# INVARIANT 3: Weight sum bounds
#
# With 64 miners, each weight = floor(score * 65535 / total):
#   sum(weights) >= 65535 - 63  (= 65472, due to floor rounding)
#   sum(weights) <= 65535
#
# Verify: these bounds hold for any valid score distribution.
# ============================================================
print("\n--- Invariant 3: Weight sum bounds ---")

NUM_MINERS = 64
MAX_WEIGHT = 65535

s3 = Solver()
scores = [Int(f's_{i}') for i in range(NUM_MINERS)]
weights = [Int(f'w_{i}') for i in range(NUM_MINERS)]
remainders = [Int(f'r_{i}') for i in range(NUM_MINERS)]
total_score = Int('total_score')

# All scores non-negative, at least one positive
for i in range(NUM_MINERS):
    s3.add(scores[i] >= 0)
s3.add(total_score == Sum(scores))
s3.add(total_score > 0)

# Floor division constraints
for i in range(NUM_MINERS):
    s3.add(scores[i] * MAX_WEIGHT == weights[i] * total_score + remainders[i])
    s3.add(remainders[i] >= 0)
    s3.add(remainders[i] < total_score)
    s3.add(weights[i] >= 0)

weight_sum = Sum(weights)

# Try to violate: weight_sum < 65472 OR weight_sum > 65535
s3.add(Or(weight_sum < MAX_WEIGHT - (NUM_MINERS - 1), weight_sum > MAX_WEIGHT))

result = s3.check()
if result == unsat:
    print(f"  PASS: Weight sum always in [{MAX_WEIGHT - NUM_MINERS + 1}, {MAX_WEIGHT}]")
else:
    m = s3.model()
    ws = sum(m.eval(weights[i]).as_long() for i in range(NUM_MINERS))
    print(f"  FAIL: Weight sum = {ws}")
    print(f"  Model total_score = {m.eval(total_score)}")

# ============================================================
# INVARIANT 4: UID packing preserves information
#
# Pack 15 u16 values into one Field: val = sum(uid[j] * 2^(16*j))
# Verify: different UID vectors produce different packed values.
# ============================================================
print("\n--- Invariant 4: UID packing injectivity ---")

s4 = Solver()
# Two sets of 15 UIDs
uids_a = [BitVec(f'a_{j}', 256) for j in range(15)]
uids_b = [BitVec(f'b_{j}', 256) for j in range(15)]

# Each UID is u16
for j in range(15):
    s4.add(ULE(uids_a[j], BitVecVal(65535, 256)))
    s4.add(ULE(uids_b[j], BitVecVal(65535, 256)))

# Compute packed values
shift = BitVecVal(1, 256)
packed_a = BitVecVal(0, 256)
packed_b = BitVecVal(0, 256)
multiplier = BitVecVal(1, 256)
for j in range(15):
    packed_a = packed_a + uids_a[j] * multiplier
    packed_b = packed_b + uids_b[j] * multiplier
    multiplier = multiplier * BitVecVal(65536, 256)

# Same packed value but different UIDs
s4.add(packed_a == packed_b)
s4.add(Or(*[uids_a[j] != uids_b[j] for j in range(15)]))

result = s4.check()
if result == unsat:
    print("  PASS: Packing 15 u16 values is injective (no collisions)")
else:
    print(f"  FAIL: Collision found: {s4.model()}")

# ============================================================
# INVARIANT 5: Packing fits in BN254 field
#
# 15 u16 values packed: max = sum(65535 * 2^(16*j) for j in 0..14)
# This must be < BN254 prime P.
# ============================================================
print("\n--- Invariant 5: Packed value fits in BN254 field ---")

max_packed = sum(65535 * (2**(16*j)) for j in range(15))
print(f"  Max packed value: {max_packed}")
print(f"  BN254 prime:      {P}")
print(f"  Fits: {max_packed < P}")
if max_packed < P:
    print("  PASS: 15 u16 values always fit in BN254 field")
else:
    print("  FAIL: Overflow possible!")

# ============================================================
# INVARIANT 6: Total score bound
#
# 64 scores, each u64: total <= 64 * 2^64 < 2^70
# Verify: 2^70 < BN254 prime (trivially true but let's confirm)
# ============================================================
print("\n--- Invariant 6: Total score fits in 48-bit bound ---")

# Actually the circuit uses 48-bit bound now
# Max score per miner if bounded to u32: 2^32 - 1
# Max total: 64 * (2^32 - 1) = 64 * 4294967295 = 274877906880
max_total_u32 = 64 * (2**32 - 1)
bound_48 = 2**48
print(f"  Max total (64 * u32): {max_total_u32}")
print(f"  48-bit bound:         {bound_48}")
print(f"  Fits: {max_total_u32 < bound_48}")
if max_total_u32 < bound_48:
    print("  PASS: u32 scores fit in 48-bit total bound")
else:
    print("  FAIL!")

# What about u64 scores?
max_total_u64 = 64 * (2**64 - 1)
bound_70 = 2**70
print(f"\n  Max total (64 * u64): {max_total_u64}")
print(f"  70-bit bound:         {bound_70}")
print(f"  Fits: {max_total_u64 < bound_70}")
if max_total_u64 < bound_70:
    print("  PASS: u64 scores fit in 70-bit total bound")
else:
    print("  FAIL: u64 scores need >70-bit bound")

print("\n" + "=" * 60)
print("Z3 Verification Complete")
print("=" * 60)
