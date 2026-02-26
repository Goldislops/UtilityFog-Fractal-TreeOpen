import pytest

try:
    from uft_ca import MultiStateGraphLattice
    HAS_UFT_CA = True
except ImportError:
    HAS_UFT_CA = False

pytestmark = pytest.mark.skipif(not HAS_UFT_CA, reason="uft_ca not built; run `maturin develop` in crates/uft_ca first")

VOID = 0
STRUCTURAL = 1
COMPUTE = 2
ENERGY = 3
SENSOR = 4


def triangle_adjacency():
    return [[1, 2], [0, 2], [0, 1]]


def quad_adjacency():
    return [[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]]


def line_adjacency():
    return [[1], [0, 2], [1]]


class TestEnergyPhysics:
    def test_energy_powers_compute(self):
        """Energy adjacent to Compute becomes Compute (energy absorbed)."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [ENERGY, COMPUTE, VOID],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == COMPUTE
        assert result[1] == COMPUTE

    def test_isolated_energy_dissipates(self):
        """Energy with only Void neighbors dissipates."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [ENERGY, VOID, VOID],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == VOID

    def test_energy_chain_sustains(self):
        """Adjacent Energy cells sustain each other."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [ENERGY, ENERGY, VOID],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == ENERGY
        assert result[1] == ENERGY

    def test_energy_spreads_into_void(self):
        """Void with 2+ Energy neighbors becomes Energy."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [ENERGY, ENERGY, VOID],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[2] == ENERGY

    def test_energy_does_not_spread_with_one_source(self):
        """Void with only 1 Energy neighbor stays Void."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [ENERGY, VOID, VOID],
            line_adjacency(),
        )
        result = lattice.step()
        assert result[1] == VOID


class TestComputePhysics:
    def test_powered_compute_survives(self):
        """Compute with adjacent Energy stays Compute."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [COMPUTE, ENERGY, VOID],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == COMPUTE

    def test_unpowered_compute_dies(self):
        """Compute with no Energy neighbors dies to Void."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [COMPUTE, VOID, STRUCTURAL],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == VOID


class TestStructuralPhysics:
    def test_structural_cluster_stable(self):
        """Structural cells with Structural neighbors stay stable."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [STRUCTURAL, STRUCTURAL, STRUCTURAL],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result == [STRUCTURAL, STRUCTURAL, STRUCTURAL]

    def test_isolated_structural_decays(self):
        """Structural with no Structural neighbors decays to Void."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [STRUCTURAL, VOID, VOID],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == VOID

    def test_structural_crystallization(self):
        """Void with 3+ Structural neighbors becomes Structural."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [VOID, STRUCTURAL, STRUCTURAL, STRUCTURAL],
            quad_adjacency(),
        )
        result = lattice.step()
        assert result[0] == STRUCTURAL


class TestSensorPhysics:
    def test_sensor_fires_with_compute(self):
        """Sensor with 2+ Compute neighbors fires and becomes Compute."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [SENSOR, COMPUTE, COMPUTE],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == COMPUTE

    def test_sensor_waits_without_enough_compute(self):
        """Sensor with <2 Compute neighbors stays Sensor."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [SENSOR, COMPUTE, VOID],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == SENSOR

    def test_sensor_persists_in_void(self):
        """Sensor surrounded by Void stays Sensor (always waiting)."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [SENSOR, VOID, VOID],
            triangle_adjacency(),
        )
        result = lattice.step()
        assert result[0] == SENSOR


class TestCustomRules:
    def test_custom_transition_table(self):
        """User-defined transitions override the defaults."""
        transitions = [
            (ENERGY, SENSOR, 1, 999, SENSOR),
        ]
        defaults = [
            (ENERGY, VOID),
            (SENSOR, SENSOR),
        ]
        lattice = MultiStateGraphLattice(
            [ENERGY, SENSOR],
            [[1], [0]],
            transitions,
            defaults,
        )
        result = lattice.step()
        assert result[0] == SENSOR
        assert result[1] == SENSOR


class TestMultiStep:
    def test_energy_triangle_stable_over_steps(self):
        """Full Energy triangle should remain stable indefinitely."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [ENERGY, ENERGY, ENERGY],
            triangle_adjacency(),
        )
        result = lattice.step_n(10)
        assert result == [ENERGY, ENERGY, ENERGY]

    def test_energy_propagation_wave(self):
        """Energy pair on a line: spreads then stabilizes."""
        lattice = MultiStateGraphLattice.with_fog_rules(
            [ENERGY, ENERGY, VOID, VOID, VOID],
            [[1], [0, 2], [1, 3], [2, 4], [3]],
        )
        step1 = lattice.step()
        assert step1[0] == ENERGY
        assert step1[1] == ENERGY

    def test_step_n_returns_final_state(self):
        """step_n(3) should equal calling step() three times."""
        adj = triangle_adjacency()
        states = [ENERGY, COMPUTE, VOID]

        lattice_a = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        result_a = lattice_a.step_n(3)

        lattice_b = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        lattice_b.step()
        lattice_b.step()
        result_b = lattice_b.step()

        assert result_a == result_b
