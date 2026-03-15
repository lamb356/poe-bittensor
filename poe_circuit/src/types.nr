// ============================================================
// Type definitions for PoE circuit
// ============================================================

pub global NUM_MINERS: u32 = 64;
pub global MAX_WEIGHT: Field = 65535;
// Floor division rounding slack: up to NUM_MINERS - 1 = 63
pub global MIN_WEIGHT_SUM: Field = 65472; // 65535 - 63
