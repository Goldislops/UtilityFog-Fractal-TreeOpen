import pytest
from uft_ca import MultiStateGraphLattice

VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR = 0, 1, 2, 3, 4


class TestStateCensus:
    def test_census_all_energy_octahedral(self):
        lattice = MultiStateGraphLattice.octahedral(5, ENERGY)
        census = lattice.census()
        assert census[ENERGY] == 125
        assert census[VOID] == 0
        assert sum(census.values()) == 125

    def test_census_all_void_sierpinski(self):
        lattice = MultiStateGraphLattice.sierpinski(1, VOID)
        census = lattice.census()
        assert census[VOID] == 16
        assert census[ENERGY] == 0

    def test_census_after_step(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        lattice.step()
        census = lattice.census()
        assert sum(census.values()) == 27

    def test_census_total_equals_node_count(self):
        lattice = MultiStateGraphLattice.menger(2, STRUCTURAL)
        census = lattice.census()
        assert sum(census.values()) == lattice.node_count()

    def test_census_mixed_states(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        states = lattice.get_states()
        states[0] = VOID
        states[1] = STRUCTURAL
        states[2] = COMPUTE
        states[3] = SENSOR
        lattice.set_states(states)
        census = lattice.census()
        assert census[VOID] == 1
        assert census[STRUCTURAL] == 1
        assert census[COMPUTE] == 1
        assert census[SENSOR] == 1
        assert census[ENERGY] == 23

    def test_census_keys(self):
        lattice = MultiStateGraphLattice.sierpinski(0, VOID)
        census = lattice.census()
        assert set(census.keys()) == {0, 1, 2, 3, 4}

    def test_census_menger_structural(self):
        lattice = MultiStateGraphLattice.menger(1, STRUCTURAL)
        census = lattice.census()
        assert census[STRUCTURAL] == 20

    def test_census_octahedral_sensor(self):
        lattice = MultiStateGraphLattice.octahedral(4, SENSOR)
        census = lattice.census()
        assert census[SENSOR] == 64


class TestSpatialQueries:
    def test_census_region_full(self):
        lattice = MultiStateGraphLattice.octahedral(5, ENERGY)
        full = lattice.census_region(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        assert full is not None
        assert sum(full.values()) == 125

    def test_census_region_partial(self):
        lattice = MultiStateGraphLattice.octahedral(10, ENERGY)
        half = lattice.census_region(0.0, 0.0, 0.0, 0.49, 1.0, 1.0)
        assert half is not None
        assert sum(half.values()) < 1000
        assert sum(half.values()) > 0

    def test_census_region_empty(self):
        lattice = MultiStateGraphLattice.octahedral(5, ENERGY)
        empty = lattice.census_region(2.0, 2.0, 2.0, 3.0, 3.0, 3.0)
        assert empty is not None
        assert sum(empty.values()) == 0

    def test_census_sphere_center(self):
        lattice = MultiStateGraphLattice.octahedral(10, ENERGY)
        sphere = lattice.census_sphere(0.5, 0.5, 0.5, 0.5)
        assert sphere is not None
        assert sum(sphere.values()) > 0

    def test_census_sphere_tiny(self):
        lattice = MultiStateGraphLattice.octahedral(10, ENERGY)
        tiny = lattice.census_sphere(0.0, 0.0, 0.0, 0.001)
        assert tiny is not None
        assert sum(tiny.values()) <= 1

    def test_census_region_no_coords(self):
        lattice = MultiStateGraphLattice.with_fog_rules([3, 3, 0], [[1, 2], [0, 2], [0, 1]])
        result = lattice.census_region(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        assert result is None

    def test_census_sphere_no_coords(self):
        lattice = MultiStateGraphLattice.with_fog_rules([3, 3, 0], [[1, 2], [0, 2], [0, 1]])
        result = lattice.census_sphere(0.0, 0.0, 0.0, 1.0)
        assert result is None

    def test_has_coords_fractal(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        assert lattice.has_coords()

    def test_has_coords_manual(self):
        lattice = MultiStateGraphLattice.with_fog_rules([3, 3], [[1], [0]])
        assert not lattice.has_coords()

    def test_get_coords_length(self):
        lattice = MultiStateGraphLattice.octahedral(5, ENERGY)
        coords = lattice.get_coords()
        assert coords is not None
        assert len(coords) == 125

    def test_get_coords_menger(self):
        lattice = MultiStateGraphLattice.menger(1, VOID)
        coords = lattice.get_coords()
        assert coords is not None
        assert len(coords) == 20

    def test_get_coords_sierpinski(self):
        lattice = MultiStateGraphLattice.sierpinski(1, VOID)
        coords = lattice.get_coords()
        assert coords is not None
        assert len(coords) == 16

    def test_spatial_after_stepping(self):
        lattice = MultiStateGraphLattice.octahedral(5, ENERGY)
        lattice.step_auto_n(5)
        region = lattice.census_region(0.0, 0.0, 0.0, 0.5, 0.5, 0.5)
        assert region is not None
        assert sum(region.values()) > 0


class TestTimeSeries:
    def test_run_and_record_basic(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        history = lattice.run_and_record(5)
        assert len(history) == 6
        assert all(isinstance(h, dict) for h in history)

    def test_run_and_record_initial_matches_census(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        initial_census = lattice.census()
        lattice2 = MultiStateGraphLattice.octahedral(3, ENERGY)
        history = lattice2.run_and_record(3)
        assert history[0] == initial_census

    def test_run_and_record_totals_preserved(self):
        lattice = MultiStateGraphLattice.menger(1, ENERGY)
        history = lattice.run_and_record(10)
        for h in history:
            assert sum(h.values()) == 20

    def test_run_and_record_advances_state(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        history = lattice.run_and_record(5)
        final_census = lattice.census()
        assert history[-1] == final_census

    def test_run_and_record_flat(self):
        lattice = MultiStateGraphLattice.sierpinski(1, ENERGY)
        history = lattice.run_and_record_flat(3)
        assert len(history) == 4
        assert all(isinstance(h, list) for h in history)
        assert all(len(h) == 5 for h in history)

    def test_run_and_record_flat_sums(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        history = lattice.run_and_record_flat(5)
        for h in history:
            assert sum(h) == 27

    def test_run_and_record_zero_steps(self):
        lattice = MultiStateGraphLattice.sierpinski(0, ENERGY)
        history = lattice.run_and_record(0)
        assert len(history) == 1
        assert history[0][ENERGY] == 4


class TestSnapshot:
    def test_snapshot_round_trip(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        data = lattice.snapshot()
        restored = MultiStateGraphLattice.from_snapshot(data)
        assert restored.get_states() == lattice.get_states()
        assert restored.node_count() == lattice.node_count()

    def test_snapshot_preserves_adjacency(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        original_edges = lattice.edge_count()
        data = lattice.snapshot()
        restored = MultiStateGraphLattice.from_snapshot(data)
        assert restored.edge_count() == original_edges

    def test_snapshot_preserves_coords(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        original_coords = lattice.get_coords()
        data = lattice.snapshot()
        restored = MultiStateGraphLattice.from_snapshot(data)
        restored_coords = restored.get_coords()
        assert restored_coords is not None
        assert len(restored_coords) == len(original_coords)
        for (ox, oy, oz), (rx, ry, rz) in zip(original_coords, restored_coords):
            assert abs(ox - rx) < 1e-10
            assert abs(oy - ry) < 1e-10
            assert abs(oz - rz) < 1e-10

    def test_snapshot_after_stepping(self):
        lattice = MultiStateGraphLattice.menger(1, ENERGY)
        lattice.step_auto_n(5)
        states_before = lattice.get_states()
        data = lattice.snapshot()
        restored = MultiStateGraphLattice.from_snapshot(data)
        assert restored.get_states() == states_before

    def test_snapshot_no_coords(self):
        lattice = MultiStateGraphLattice.with_fog_rules([3, 3, 0], [[1, 2], [0, 2], [0, 1]])
        data = lattice.snapshot()
        restored = MultiStateGraphLattice.from_snapshot(data)
        assert restored.get_states() == [3, 3, 0]
        assert not restored.has_coords()

    def test_snapshot_invalid_data(self):
        with pytest.raises(ValueError):
            MultiStateGraphLattice.from_snapshot([0, 1, 2])

    def test_snapshot_sierpinski(self):
        lattice = MultiStateGraphLattice.sierpinski(2, STRUCTURAL)
        data = lattice.snapshot()
        restored = MultiStateGraphLattice.from_snapshot(data)
        assert restored.node_count() == 64
        assert restored.get_states() == lattice.get_states()
        assert restored.has_coords()

    def test_snapshot_resume_simulation(self):
        lattice = MultiStateGraphLattice.octahedral(5, ENERGY)
        lattice.step_auto_n(3)
        data = lattice.snapshot()
        lattice.step_auto_n(5)
        final_a = lattice.get_states()
        restored = MultiStateGraphLattice.from_snapshot(data)
        restored.step_auto_n(5)
        final_b = restored.get_states()
        assert final_a == final_b


class TestCensusEvolution:
    def test_census_evolves_over_time(self):
        lattice = MultiStateGraphLattice.octahedral(5, ENERGY)
        c0 = lattice.census()
        lattice.step_auto_n(10)
        c10 = lattice.census()
        assert sum(c0.values()) == sum(c10.values())

    def test_energy_decay_curve(self):
        lattice = MultiStateGraphLattice.menger(1, ENERGY)
        history = lattice.run_and_record_flat(20)
        for h in history:
            assert sum(h) == 20

    def test_structural_stability(self):
        lattice = MultiStateGraphLattice.octahedral(3, STRUCTURAL)
        history = lattice.run_and_record(10)
        for h in history:
            assert h[STRUCTURAL] == 27

    def test_void_lattice_stays_void(self):
        lattice = MultiStateGraphLattice.octahedral(3, VOID)
        history = lattice.run_and_record(5)
        for h in history:
            assert h[VOID] == 27
            assert h[ENERGY] == 0
