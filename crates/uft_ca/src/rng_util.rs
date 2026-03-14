//\! WASM-safe seedable PRNG using Xoshiro256**.
//\!
//\! On native: seeded from getrandom.
//\! On WASM: seeded from getrandom (crypto.getRandomValues via js feature).

use rand::SeedableRng;
use rand_xoshiro::Xoshiro256StarStar;

pub type CaRng = Xoshiro256StarStar;

/// Create a PRNG with a deterministic seed.
pub fn create_rng(seed: u64) -> CaRng {
    Xoshiro256StarStar::seed_from_u64(seed)
}

/// Create a PRNG seeded from OS/browser entropy.
/// Uses getrandom which maps to crypto.getRandomValues on WASM.
pub fn create_rng_from_entropy() -> CaRng {
    let mut seed = [0u8; 32];
    getrandom::getrandom(&mut seed).unwrap_or_else(|_| {
        // Fallback: use a fixed seed if getrandom fails
        seed = [0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE,
                0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10,
                0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18];
    });
    Xoshiro256StarStar::from_seed(seed)
}
