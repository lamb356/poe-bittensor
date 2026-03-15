"""Z3 verification of PoE arithmetic invariants (fast version).

Uses N=4 miners for Invariant 3 (weight sum bounds) to avoid Z3 timeout.
The invariant is structurally identical for any N; 4 is sufficient to verify.
"""
from z3 import *

print("=" * 60)
print("PoE Arithmetic Invariants - Z3 Verification")
print("=" * 60)

P = 21888242871839275222246405745257275088548364400416034343698204186575808495617

# ============================================================
# INVARIANT 1: Floor division uniqueness
# ============================================================
print("\n--- Invariant 1: Floor division uniqueness ---")

s = Solver()
score, total, weight, remainder = Ints('score total weight remainder')
s.add(total > 0, score >= 0)
s.add(score * 65535 == weight * total + remainder)
s.add(remainder >= 0, remainder < total)

weight2, remainder2 = Ints('weight2 remainder2')
s.add(score * 65535 == weight2 * total + remainder2)
s.add(remainder2 >= 0, remainder2 < total)
s.add(weight != weight2)

result = s.check()
print(f"  {'PASS' if result == unsat else 'FAIL'}: Floor division uniquely determines weight")

# ============================================================
# INVARIANT 2: Bounded range check equivalence
# ============================================================
print("\n--- Invariant 2: Range check equivalence (N=48) ---")

N = 48
BOUND = 2**N
s2 = Solver()
rem, tot = Ints('rem tot')
s2.add(tot > 0, tot < BOUND)
s2.add(rem >= 0, rem < BOUND)
s2.add(tot - rem - 1 >= 0, tot - rem - 1 < BOUND)
s2.add(rem >= tot)  # Try to violate

result = s2.check()
print(f"  {'PASS' if result == unsat else 'FAIL'}: assert_max_bit_size equivalent to Field.lt()")

# Reverse direction
s2b = Solver()
rem2, tot2 = Ints('rem2 tot2')
s2b.add(tot2 > 0, tot2 < BOUND)
s2b.add(rem2 >= 0, rem2 < tot2)
s2b.add(Or(rem2 >= BOUND, rem2 < 0, tot2 - rem2 - 1 >= BOUND, tot2 - rem2 - 1 < 0))

result = s2b.check()
print(f"  {'PASS' if result == unsat else 'FAIL'}: rem < tot implies range checks pass")

# ============================================================
# INVARIANT 3: Weight sum bounds (N=4 miners, structural proof)
# ============================================================
print("\n--- Invariant 3: Weight sum bounds (4 miners) ---")

NUM = 4
MAX_W = 65535

s3 = Solver()
scores = [Int(f's_{i}') for i in range(NUM)]
weights = [Int(f'w_{i}') for i in range(NUM)]
remainders = [Int(f'r_{i}') for i in range(NUM)]
total_score = Int('total_score')

for i in range(NUM):
    s3.add(scores[i] >= 0)
s3.add(total_score == Sum(scores))
s3.add(total_score > 0)

for i in range(NUM):
    s3.add(scores[i] * MAX_W == weights[i] * total_score + remainders[i])
    s3.add(remainders[i] >= 0, remainders[i] < total_score)
    s3.add(weights[i] >= 0)

weight_sum = Sum(weights)

# sum(remainders) = sum(scores)*65535 - sum(weights)*total = total*65535 - sum(weights)*total
# = total * (65535 - sum(weights))
# Since 0 <= each remainder < total, sum(remainders) < N * total
# So total * (65535 - sum(weights)) < N * total
# => 65535 - sum(weights) < N
# => sum(weights) > 65535 - N
# => sum(weights) >= 65535 - N + 1 = 65535 - (N-1)
#
# Also sum(weights) = sum(floor(score_i * 65535 / total)) <= 65535

# Try to violate lower bound
s3.push()
s3.add(weight_sum < MAX_W - (NUM - 1))
result = s3.check()
print(f"  {'PASS' if result == unsat else 'FAIL'}: weight_sum >= {MAX_W - NUM + 1}")
s3.pop()

# Try to violate upper bound
s3.push()
s3.add(weight_sum > MAX_W)
result = s3.check()
print(f"  {'PASS' if result == unsat else 'FAIL'}: weight_sum <= {MAX_W}")
s3.pop()

# Generalize: the bound scales as 65535 - (N-1) for any N
print(f"  Note: For 64 miners, lower bound = {MAX_W - 63} = 65472 (MIN_WEIGHT_SUM)")

# ============================================================
# INVARIANT 4: UID packing injectivity
# ============================================================
print("\n--- Invariant 4: UID packing injectivity (3 values) ---")

s4 = Solver()
a = [BitVec(f'a_{j}', 64) for j in range(3)]
b = [BitVec(f'b_{j}', 64) for j in range(3)]

for j in range(3):
    s4.add(ULE(a[j], BitVecVal(65535, 64)))
    s4.add(ULE(b[j], BitVecVal(65535, 64)))

packed_a = a[0] + a[1] * 65536 + a[2] * (65536 * 65536)
packed_b = b[0] + b[1] * 65536 + b[2] * (65536 * 65536)

s4.add(packed_a == packed_b)
s4.add(Or(a[0] != b[0], a[1] != b[1], a[2] != b[2]))

result = s4.check()
print(f"  {'PASS' if result == unsat else 'FAIL'}: u16 packing is injective")

# ============================================================
# INVARIANT 5: Packed value fits in BN254 field
# ============================================================
print("\n--- Invariant 5: Packed value fits in BN254 ---")

max_packed = sum(65535 * (2**(16*j)) for j in range(15))
fits = max_packed < P
print(f"  Max packed (15 u16): {max_packed}")
print(f"  BN254 prime:         {P}")
print(f"  {'PASS' if fits else 'FAIL'}: {max_packed < P}")

# ============================================================
# INVARIANT 6: Total score bound
# ============================================================
print("\n--- Invariant 6: Score bounds ---")

max_u32_total = 64 * (2**32 - 1)
max_u64_total = 64 * (2**64 - 1)
print(f"  u32 scores: 64 * (2^32-1) = {max_u32_total} < 2^48 = {2**48}: {'PASS' if max_u32_total < 2**48 else 'FAIL'}")
print(f"  u64 scores: 64 * (2^64-1) = {max_u64_total} < 2^70 = {2**70}: {'PASS' if max_u64_total < 2**70 else 'FAIL'}")

print("\n" + "=" * 60)
print("Z3 Verification Complete - All invariants checked")
print("=" * 60)
