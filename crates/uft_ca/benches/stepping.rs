use criterion::{criterion_group, criterion_main, Criterion};

fn bench_stepping(_c: &mut Criterion) {
    // TODO: add graph stepping benchmarks
}

criterion_group!(benches, bench_stepping);
criterion_main!(benches);
