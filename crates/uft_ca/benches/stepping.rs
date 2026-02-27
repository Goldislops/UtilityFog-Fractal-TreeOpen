use criterion::{criterion_group, criterion_main, Criterion, BenchmarkId};
use uft_ca::{GraphState, MultiStateRule};

fn build_ring(n: usize) -> GraphState {
    let mut nodes = vec![0u8; n];
    for i in 0..n {
        nodes[i] = (i % 5) as u8;
    }
    let adjacency: Vec<Vec<usize>> = (0..n)
        .map(|i| vec![(i + n - 1) % n, (i + 1) % n])
        .collect();
    GraphState::new(nodes, adjacency)
}

fn build_grid(side: usize) -> GraphState {
    let n = side * side;
    let mut nodes = vec![0u8; n];
    for i in 0..n {
        nodes[i] = (i % 5) as u8;
    }
    let mut adjacency = Vec::with_capacity(n);
    for y in 0..side {
        for x in 0..side {
            let idx = y * side + x;
            let mut neighbors = Vec::new();
            if x > 0 { neighbors.push(idx - 1); }
            if x + 1 < side { neighbors.push(idx + 1); }
            if y > 0 { neighbors.push(idx - side); }
            if y + 1 < side { neighbors.push(idx + side); }
            adjacency.push(neighbors);
        }
    }
    GraphState::new(nodes, adjacency)
}

fn bench_step_sequential(c: &mut Criterion) {
    let rule = MultiStateRule::utility_fog_default();
    let mut group = c.benchmark_group("step_multi_seq");
    for &size in &[100, 1_000, 10_000, 100_000] {
        let gs = build_ring(size);
        group.bench_with_input(BenchmarkId::new("ring", size), &gs, |b, gs| {
            b.iter(|| gs.step_multi(&rule))
        });
    }
    for &side in &[10, 32, 100, 316] {
        let gs = build_grid(side);
        let label = format!("grid_{}x{}", side, side);
        group.bench_with_input(BenchmarkId::new(&label, side * side), &gs, |b, gs| {
            b.iter(|| gs.step_multi(&rule))
        });
    }
    group.finish();
}

fn bench_step_parallel(c: &mut Criterion) {
    let rule = MultiStateRule::utility_fog_default();
    let mut group = c.benchmark_group("step_multi_par");
    for &size in &[100, 1_000, 10_000, 100_000] {
        let gs = build_ring(size);
        group.bench_with_input(BenchmarkId::new("ring", size), &gs, |b, gs| {
            b.iter(|| gs.step_multi_par(&rule))
        });
    }
    for &side in &[10, 32, 100, 316] {
        let gs = build_grid(side);
        let label = format!("grid_{}x{}", side, side);
        group.bench_with_input(BenchmarkId::new(&label, side * side), &gs, |b, gs| {
            b.iter(|| gs.step_multi_par(&rule))
        });
    }
    group.finish();
}

fn bench_step_comparison(c: &mut Criterion) {
    let rule = MultiStateRule::utility_fog_default();
    let mut group = c.benchmark_group("seq_vs_par");
    for &size in &[100, 1_000, 10_000, 100_000] {
        let gs = build_ring(size);
        group.bench_with_input(BenchmarkId::new("seq", size), &gs, |b, gs| {
            b.iter(|| gs.step_multi(&rule))
        });
        group.bench_with_input(BenchmarkId::new("par", size), &gs, |b, gs| {
            b.iter(|| gs.step_multi_par(&rule))
        });
    }
    group.finish();
}

criterion_group!(benches, bench_step_sequential, bench_step_parallel, bench_step_comparison);
criterion_main!(benches);
