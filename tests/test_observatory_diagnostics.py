"""Observatory snapshot diagnostics and machine-readable reporting.

Scope: `vis.observatory.diagnostics` — the ordered runtime-data-contract checks
behind `doctor`, the shared statistics both `info` renderings are built from,
and the JSON documents. CLI dispatch, exit statuses and end-to-end reachability
live in `tests/test_observatory_cli.py`.

These checks describe the Observatory's *runtime data contract*, not scientific
validity. An all-void lattice, an all-zero channel and a zero fitness are legal
snapshots and must pass — asserted explicitly below, because a diagnostic that
fails healthy data is worse than none.
"""

from __future__ import annotations

import inspect
import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("matplotlib")

from vis.observatory import diagnostics
from vis.observatory.constants import CHANNEL_NAMES, NUM_CHANNELS, STATE_NAMES
from vis.observatory.loader import ObservatorySnapshot

SHAPE = (2, 3, 4)


def _snapshot(lattice=None, memory=None, generation=7, ca_step=11,
              best_fitness=0.5, source="/fake/snap.npz"):
    if lattice is None:
        lattice = np.zeros(SHAPE, dtype=np.uint8)
        lattice[0, 0, 0] = 1
        lattice[1, 1, 1] = 2
    if memory is None:
        memory = np.zeros((NUM_CHANNELS,) + lattice.shape, dtype=np.float32)
        memory[0] = 1.5
    return ObservatorySnapshot(
        lattice=lattice,
        memory_grid=memory,
        generation=generation,
        ca_step=ca_step,
        best_fitness=best_fitness,
        source_path=source,
    )


def _named(checks):
    return {c.name: c for c in checks}


# ---------------------------------------------------------------------------
# Positive controls -- healthy data must pass
# ---------------------------------------------------------------------------


def test_valid_snapshot_passes_every_check():
    checks = diagnostics.diagnose(_snapshot())
    assert diagnostics.all_ok(checks)
    assert diagnostics.summarize(checks)["failed"] == 0


@pytest.mark.parametrize(
    "mutate, why",
    [
        pytest.param(lambda s: dict(lattice=np.zeros(SHAPE, dtype=np.uint8)),
                     "all-void lattice", id="all-void"),
        pytest.param(lambda s: dict(
            memory=np.zeros((NUM_CHANNELS,) + SHAPE, dtype=np.float32)),
            "all-zero memory", id="all-zero-memory"),
        pytest.param(lambda s: dict(best_fitness=0.0), "zero fitness", id="zero-fitness"),
        pytest.param(lambda s: dict(best_fitness=-12.5),
                     "negative but finite fitness", id="negative-fitness"),
        pytest.param(lambda s: dict(generation=0, ca_step=0),
                     "zero counters", id="zero-counters"),
        pytest.param(lambda s: dict(
            memory=np.full((NUM_CHANNELS,) + SHAPE, 1e30, dtype=np.float32)),
            "large but finite values", id="large-finite"),
    ],
)
def test_unusual_but_legal_snapshots_still_pass(mutate, why):
    """Not scientific validity: these are legal snapshots."""
    checks = diagnostics.diagnose(_snapshot(**mutate(None)))
    failed = [c.name for c in checks if not c.ok]
    assert failed == [], f"{why} should not fail: {failed}"


@pytest.mark.parametrize("state_id", sorted(STATE_NAMES))
def test_every_vocabulary_state_is_accepted(state_id):
    lattice = np.full(SHAPE, state_id, dtype=np.uint8)
    checks = _named(diagnostics.diagnose(_snapshot(lattice=lattice)))
    assert checks["lattice_states_known"].ok


# ---------------------------------------------------------------------------
# Source route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, route",
    [("/x/snap.npz", "npz"), ("/x/genome.json", "portable-genome JSON")],
    ids=["npz", "portable-genome"],
)
def test_source_route_check_names_the_public_route(source, route):
    check = _named(diagnostics.diagnose(_snapshot(source=source)))["source_loadable"]
    assert check.ok
    assert route in check.detail


@pytest.mark.parametrize("source", ["/x/SNAP.NPZ", "/x/genome.JSON"])
def test_source_route_check_is_case_sensitive_like_the_loader(source):
    """The check must not be more permissive than the route it describes.

    `loader.load_snapshot` compares `path.suffix == ".npz"` exactly, and the
    CLI rejects any other suffix before loading, so an upper-cased extension is
    NOT loadable. Reporting it as loadable would be a check that fails open.
    """
    check = _named(diagnostics.diagnose(_snapshot(source=source)))["source_loadable"]
    assert not check.ok


def test_source_route_check_is_reported_first():
    """Self-describing reports: a reader sees the provenance before the
    contract findings that depend on it."""
    assert diagnostics.diagnose(_snapshot())[0].name == "source_loadable"


@pytest.mark.parametrize(
    "source", ["/x/snap.txt", "/x/snap", "/x/snap.npy", "/x/snap.json.gz"]
)
def test_unsupported_source_suffix_fails(source):
    check = _named(diagnostics.diagnose(_snapshot(source=source)))["source_loadable"]
    assert not check.ok
    assert "not a public load route" in check.detail


def test_snapshot_without_a_source_fails_the_route_check():
    """An in-memory snapshot did not come through a public route."""
    check = _named(diagnostics.diagnose(_snapshot(source=None)))["source_loadable"]
    assert not check.ok
    assert "no source path" in check.detail


def test_source_route_check_does_not_reopen_the_file(tmp_path):
    """Side-effect-free: the row reports the route the snapshot names, it does
    not re-read the source. A path that no longer exists still passes."""
    missing = tmp_path / "deleted.npz"
    assert not missing.exists()
    checks = _named(diagnostics.diagnose(_snapshot(source=str(missing))))
    assert checks["source_loadable"].ok
    assert not missing.exists()


# ---------------------------------------------------------------------------
# Individual contract failures
# ---------------------------------------------------------------------------


def test_non_array_lattice_fails_without_raising():
    # `memory` is supplied explicitly: the helper's default derives the memory
    # shape from `lattice.shape`, which a plain list does not have.
    memory = np.zeros((NUM_CHANNELS,) + SHAPE, dtype=np.float32)
    checks = _named(diagnostics.diagnose(_snapshot(lattice=[[[1]]], memory=memory)))
    assert not checks["lattice_is_array"].ok
    # Dependent checks report their own failure rather than exploding.
    assert not checks["lattice_rank_is_three"].ok
    assert not checks["lattice_states_known"].ok


@pytest.mark.parametrize(
    "shape", [(8,), (2, 4), (2, 2, 2, 2)], ids=["rank-1", "rank-2", "rank-4"]
)
def test_non_three_dimensional_lattice_fails(shape):
    lattice = np.zeros(shape, dtype=np.uint8)
    memory = np.zeros((NUM_CHANNELS,) + shape, dtype=np.float32)
    checks = _named(diagnostics.diagnose(_snapshot(lattice=lattice, memory=memory)))
    assert not checks["lattice_rank_is_three"].ok
    assert str(len(shape)) in checks["lattice_rank_is_three"].detail


@pytest.mark.parametrize("shape", [(0, 2, 2), (2, 0, 2), (2, 2, 0)])
def test_zero_size_dimension_fails(shape):
    lattice = np.zeros(shape, dtype=np.uint8)
    memory = np.zeros((NUM_CHANNELS,) + shape, dtype=np.float32)
    checks = _named(diagnostics.diagnose(_snapshot(lattice=lattice, memory=memory)))
    assert not checks["lattice_dimensions_positive"].ok


def test_memory_spatial_mismatch_fails():
    memory = np.zeros((NUM_CHANNELS, 9, 9, 9), dtype=np.float32)
    checks = _named(diagnostics.diagnose(_snapshot(memory=memory)))
    assert not checks["memory_shape_matches_lattice"].ok
    assert "expected" in checks["memory_shape_matches_lattice"].detail


@pytest.mark.parametrize("channels", [3, 5, 7, 9])
def test_wrong_channel_count_fails(channels):
    """Reaches the seam when a snapshot is built directly; the loader
    normalizes legacy counts before this point on the file routes."""
    memory = np.zeros((channels,) + SHAPE, dtype=np.float32)
    checks = _named(diagnostics.diagnose(_snapshot(memory=memory)))
    assert not checks["memory_shape_matches_lattice"].ok


def test_non_array_memory_fails_without_raising():
    checks = _named(diagnostics.diagnose(_snapshot(memory=[0.0])))
    assert not checks["memory_is_array"].ok
    assert not checks["memory_shape_matches_lattice"].ok
    assert not checks["memory_values_finite"].ok


@pytest.mark.parametrize(
    "value, label",
    [(np.nan, "nan"), (np.inf, "+inf"), (-np.inf, "-inf")],
)
def test_non_finite_memory_values_fail(value, label):
    memory = np.zeros((NUM_CHANNELS,) + SHAPE, dtype=np.float32)
    memory[3, 0, 0, 0] = value
    checks = _named(diagnostics.diagnose(_snapshot(memory=memory)))
    assert not checks["memory_values_finite"].ok
    assert "1 non-finite" in checks["memory_values_finite"].detail


def test_multiple_non_finite_values_are_counted():
    memory = np.zeros((NUM_CHANNELS,) + SHAPE, dtype=np.float32)
    memory[0, 0, 0, 0] = np.nan
    memory[1, 0, 0, 1] = np.inf
    memory[2, 0, 0, 2] = -np.inf
    checks = _named(diagnostics.diagnose(_snapshot(memory=memory)))
    assert "3 non-finite" in checks["memory_values_finite"].detail


@pytest.mark.parametrize(
    "state_id", [5, 6, 200, 255], ids=["just-above", "6", "200", "wraparound-255"]
)
def test_state_id_outside_the_vocabulary_fails(state_id):
    """255 matters: uint8 arithmetic wraps, so an out-of-range id can appear as
    a large value rather than a negative one."""
    lattice = np.zeros(SHAPE, dtype=np.uint8)
    lattice[0, 0, 0] = state_id
    checks = _named(diagnostics.diagnose(_snapshot(lattice=lattice)))
    assert not checks["lattice_states_known"].ok
    assert str(state_id) in checks["lattice_states_known"].detail


def test_wrong_lattice_dtype_fails():
    lattice = np.zeros(SHAPE, dtype=np.int16)
    checks = _named(diagnostics.diagnose(_snapshot(lattice=lattice)))
    assert not checks["lattice_dtype"].ok


def test_wrong_memory_dtype_fails():
    memory = np.zeros((NUM_CHANNELS,) + SHAPE, dtype=np.float64)
    checks = _named(diagnostics.diagnose(_snapshot(memory=memory)))
    assert not checks["memory_dtype"].ok


@pytest.mark.parametrize("field", ["generation", "ca_step"])
@pytest.mark.parametrize(
    "value", [-1, -100], ids=["minus-one", "minus-hundred"]
)
def test_negative_counters_fail(field, value):
    checks = _named(diagnostics.diagnose(_snapshot(**{field: value})))
    assert not checks[f"{field}_non_negative_int"].ok
    assert "negative" in checks[f"{field}_non_negative_int"].detail


@pytest.mark.parametrize("field", ["generation", "ca_step"])
@pytest.mark.parametrize(
    "value", [1.0, "3", None, True], ids=["float", "str", "none", "bool"]
)
def test_non_integer_counters_fail(field, value):
    checks = _named(diagnostics.diagnose(_snapshot(**{field: value})))
    assert not checks[f"{field}_non_negative_int"].ok


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "inf", "-inf"],
)
def test_non_finite_fitness_fails(value):
    checks = _named(diagnostics.diagnose(_snapshot(best_fitness=value)))
    assert not checks["best_fitness_finite"].ok


@pytest.mark.parametrize("value", ["0.5", None], ids=["str", "none"])
def test_non_numeric_fitness_fails(value):
    checks = _named(diagnostics.diagnose(_snapshot(best_fitness=value)))
    assert not checks["best_fitness_finite"].ok


def test_several_failures_are_all_reported_together():
    """No short-circuit: a broken snapshot yields every failure at once."""
    lattice = np.zeros((2, 2), dtype=np.int16)
    lattice[0, 0] = 99
    memory = np.zeros((3, 2, 2), dtype=np.float64)
    memory[0, 0, 0] = np.nan
    checks = diagnostics.diagnose(
        _snapshot(lattice=lattice, memory=memory, generation=-1, best_fitness=np.inf)
    )
    failed = {c.name for c in checks if not c.ok}
    assert {
        "lattice_rank_is_three", "lattice_dtype", "lattice_states_known",
        "memory_shape_matches_lattice", "memory_dtype", "memory_values_finite",
        "generation_non_negative_int", "best_fitness_finite",
    } <= failed
    assert diagnostics.summarize(checks)["failed"] == len(failed)


# ---------------------------------------------------------------------------
# Determinism and ordering
# ---------------------------------------------------------------------------


def test_check_order_is_stable_regardless_of_outcome():
    healthy = [c.name for c in diagnostics.diagnose(_snapshot())]
    broken = [c.name for c in diagnostics.diagnose(
        _snapshot(lattice=np.zeros((2, 2), dtype=np.int16), generation=-5)
    )]
    assert healthy == broken
    assert len(healthy) == len(set(healthy)), "check names must be unique"


def test_summary_counts_match_the_checks():
    checks = diagnostics.diagnose(_snapshot(generation=-1))
    counts = diagnostics.summarize(checks)
    assert counts["total"] == len(checks)
    assert counts["passed"] + counts["failed"] == counts["total"]
    assert counts["failed"] == sum(1 for c in checks if not c.ok)
    assert diagnostics.all_ok(checks) is False


# ---------------------------------------------------------------------------
# JSON safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), np.float32("nan")],
)
def test_json_number_maps_non_finite_to_none(value):
    assert diagnostics.json_number(value) is None


@pytest.mark.parametrize("value", [0, -1.5, 2, 1e30])
def test_json_number_passes_finite_values_through(value):
    assert diagnostics.json_number(value) == pytest.approx(float(value))


def test_json_number_preserves_none():
    assert diagnostics.json_number(None) is None


def _dumps(report):
    return json.dumps(report, sort_keys=True, allow_nan=False, separators=(",", ":"))


@pytest.mark.parametrize("builder", ["info", "doctor"])
def test_reports_serialize_under_strict_json(builder):
    """`allow_nan=False` is the assertion: a leaked NaN/Infinity raises."""
    snap = _snapshot()
    report = (diagnostics.info_report(snap, "s") if builder == "info"
              else diagnostics.doctor_report(snap, "s", diagnostics.diagnose(snap)))
    text = _dumps(report)
    assert json.loads(text) == report
    assert "NaN" not in text and "Infinity" not in text


def test_reports_with_non_finite_data_still_serialize_strictly():
    memory = np.zeros((NUM_CHANNELS,) + SHAPE, dtype=np.float32)
    memory[0] = np.nan
    memory[1] = np.inf
    snap = _snapshot(memory=memory, best_fitness=float("nan"))
    for report in (diagnostics.info_report(snap, "s"),
                   diagnostics.doctor_report(snap, "s", diagnostics.diagnose(snap))):
        text = _dumps(report)          # would raise if a non-finite leaked
        assert "NaN" not in text and "Infinity" not in text
    assert diagnostics.info_report(snap, "s")["best_fitness"] is None


def test_source_is_the_only_intentionally_variable_field():
    a = diagnostics.info_report(_snapshot(), "/one.npz")
    b = diagnostics.info_report(_snapshot(), "/two.npz")
    assert a["source"] != b["source"]
    a.pop("source")
    b.pop("source")
    assert _dumps(a) == _dumps(b)


def test_repeated_serialization_is_stable():
    snap = _snapshot()
    first = _dumps(diagnostics.doctor_report(snap, "s", diagnostics.diagnose(snap)))
    second = _dumps(diagnostics.doctor_report(snap, "s", diagnostics.diagnose(snap)))
    assert first == second


# ---------------------------------------------------------------------------
# Report schema
# ---------------------------------------------------------------------------


def test_info_report_schema():
    report = diagnostics.info_report(_snapshot(), "/s.npz")
    assert report["schema"] == diagnostics.REPORT_SCHEMA
    assert report["kind"] == "info"
    assert report["ok"] is True
    assert report["source"] == "/s.npz"
    assert report["shape"] == list(SHAPE)
    assert report["total_cells"] == 2 * 3 * 4
    assert report["generation"] == 7 and report["ca_step"] == 11
    assert len(report["state_counts"]) == len(STATE_NAMES)
    assert len(report["channels"]) == NUM_CHANNELS
    assert [c["name"] for c in report["channels"]] == list(CHANNEL_NAMES)
    assert [s["id"] for s in report["state_counts"]] == sorted(STATE_NAMES)


def test_doctor_report_schema():
    snap = _snapshot()
    checks = diagnostics.diagnose(snap)
    report = diagnostics.doctor_report(snap, "/s.npz", checks)
    assert report["schema"] == diagnostics.REPORT_SCHEMA
    assert report["kind"] == "doctor"
    assert report["ok"] is True
    assert [c["name"] for c in report["checks"]] == [c.name for c in checks]
    assert report["summary"] == diagnostics.summarize(checks)
    assert report["snapshot"]["shape"] == list(SHAPE)


def test_doctor_report_ok_is_false_when_a_check_fails():
    snap = _snapshot(generation=-1)
    checks = diagnostics.diagnose(snap)
    report = diagnostics.doctor_report(snap, "/s.npz", checks)
    assert report["ok"] is False
    assert report["summary"]["failed"] >= 1
    assert any(c["ok"] is False for c in report["checks"])


def test_report_values_are_ordinary_json_types():
    snap = _snapshot()
    report = diagnostics.doctor_report(snap, "/s.npz", diagnostics.diagnose(snap))

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert type(key) is str, f"non-str key {key!r}"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        else:
            assert type(node) in (str, int, float, bool, type(None)), (
                f"non-JSON value {node!r} of type {type(node).__name__}"
            )

    walk(report)


# ---------------------------------------------------------------------------
# Shared statistics -- one implementation, not two
# ---------------------------------------------------------------------------


def test_statistics_state_counts_sum_to_total_cells():
    stats = diagnostics.snapshot_statistics(_snapshot())
    assert sum(s["count"] for s in stats["state_counts"]) == stats["total_cells"]


def test_statistics_match_snapshot_helpers():
    """Parity with the domain object the human output has always used."""
    snap = _snapshot()
    stats = diagnostics.snapshot_statistics(snap)
    assert stats["non_void_count"] == snap.non_void_count
    for entry in stats["state_counts"]:
        assert entry["count"] == snap.state_count(entry["id"])


def test_channel_statistics_are_over_non_void_cells():
    lattice = np.zeros(SHAPE, dtype=np.uint8)
    lattice[0, 0, 0] = 1
    memory = np.zeros((NUM_CHANNELS,) + SHAPE, dtype=np.float32)
    memory[0] = 5.0            # everywhere
    memory[0, 0, 0, 0] = 2.0   # the single non-void cell
    stats = diagnostics.snapshot_statistics(_snapshot(lattice=lattice, memory=memory))
    channel0 = stats["channels"][0]
    assert channel0["populated"] is True
    assert channel0["min"] == pytest.approx(2.0)
    assert channel0["max"] == pytest.approx(2.0)


def test_all_void_lattice_reports_unpopulated_channels():
    lattice = np.zeros(SHAPE, dtype=np.uint8)
    stats = diagnostics.snapshot_statistics(_snapshot(lattice=lattice))
    for channel in stats["channels"]:
        assert channel["populated"] is False
        assert channel["min"] is None
        assert channel["max"] is None
        assert channel["mean"] is None


# ---------------------------------------------------------------------------
# Human formatting
# ---------------------------------------------------------------------------


def test_human_output_lists_every_check_in_order():
    checks = diagnostics.diagnose(_snapshot())
    lines = diagnostics.format_doctor(checks, "/s.npz")
    body = [ln for ln in lines if ln.startswith("  [")]
    assert len(body) == len(checks)
    for line, check in zip(body, checks):
        assert check.name in line
        assert ("[PASS]" if check.ok else "[FAIL]") in line


def test_human_output_ends_with_an_unambiguous_summary():
    ok_lines = diagnostics.format_doctor(diagnostics.diagnose(_snapshot()), "/s")
    assert ok_lines[-1].startswith("OK:")
    bad_lines = diagnostics.format_doctor(
        diagnostics.diagnose(_snapshot(generation=-1)), "/s"
    )
    assert bad_lines[-1].startswith("FAILED:")
    assert "1 of" in bad_lines[-1]


def test_human_output_reports_multiple_failures_together():
    checks = diagnostics.diagnose(
        _snapshot(generation=-1, ca_step=-1, best_fitness=float("nan"))
    )
    lines = diagnostics.format_doctor(checks, "/s")
    assert sum(1 for ln in lines if "[FAIL]" in ln) == 3
    assert lines[-1].startswith("FAILED: 3 of")


def test_human_output_does_not_leak_payload_contents():
    """Details name shapes, dtypes, counts and vocabulary -- never contents.

    Driven through a snapshot that FAILS, because the failure branches are the
    ones that interpolate data; a passing snapshot only ever renders fixed
    success strings and would prove nothing.
    """
    memory = np.full((NUM_CHANNELS,) + SHAPE, 1234.5678, dtype=np.float32)
    memory[0, 0, 0, 0] = np.nan                     # fails memory_values_finite
    lattice = np.zeros(SHAPE, dtype=np.uint8)
    lattice[0, 0, 0] = 77                           # fails lattice_states_known
    lines = "\n".join(
        diagnostics.format_doctor(
            diagnostics.diagnose(_snapshot(lattice=lattice, memory=memory)), "/s.npz"
        )
    )
    assert "1234.5" not in lines
    assert "77" in lines, "the offending state id itself is vocabulary, and is named"


def test_unknown_state_ids_are_capped_in_the_detail():
    """A corrupt lattice must not turn a report into a dump of its own cells."""
    lattice = np.arange(60, dtype=np.uint8).reshape(3, 4, 5)   # 55 unknown ids
    check = _named(
        diagnostics.diagnose(_snapshot(
            lattice=lattice,
            memory=np.zeros((NUM_CHANNELS, 3, 4, 5), dtype=np.float32),
        ))
    )["lattice_states_known"]
    assert not check.ok
    assert "..." in check.detail
    assert "55 distinct" in check.detail
    assert len(check.detail) < 200


# ---------------------------------------------------------------------------
# The report builders must survive every input the checks are meant to flag
# ---------------------------------------------------------------------------


def test_statistics_survive_a_memory_spatial_mismatch():
    """Regression: masking a (4,4,4) channel with an (8,8,8) lattice mask
    raises IndexError, so `doctor --json` used to die with a traceback and emit
    no document on exactly the snapshot `memory_shape_matches_lattice` reports.
    """
    lattice = np.zeros((8, 8, 8), dtype=np.uint8)
    lattice[0, 0, 0] = 1
    memory = np.zeros((NUM_CHANNELS, 4, 4, 4), dtype=np.float32)
    snap = _snapshot(lattice=lattice, memory=memory)

    stats = diagnostics.snapshot_statistics(snap)
    assert [c["populated"] for c in stats["channels"]] == [False] * NUM_CHANNELS

    checks = diagnostics.diagnose(snap)
    assert not _named(checks)["memory_shape_matches_lattice"].ok
    _dumps(diagnostics.doctor_report(snap, "/s.npz", checks))   # must not raise


@pytest.mark.parametrize("channels", [1, 3, 5, 7])
def test_statistics_survive_a_short_memory_grid(channels):
    """Indexing channel 7 of a 3-channel grid raises IndexError.

    All eight rows are still reported, so the JSON shape is the same for every
    snapshot; the rows with no underlying channel are simply unpopulated.
    """
    memory = np.zeros((channels,) + SHAPE, dtype=np.float32)
    snap = _snapshot(memory=memory)
    stats = diagnostics.snapshot_statistics(snap)

    populated = [c["populated"] for c in stats["channels"]]
    assert len(populated) == NUM_CHANNELS
    assert populated[:channels] == [True] * channels
    assert populated[channels:] == [False] * (NUM_CHANNELS - channels)

    _dumps(diagnostics.doctor_report(snap, "/s.npz", diagnostics.diagnose(snap)))


def test_statistics_survive_a_non_array_memory_grid():
    snap = _snapshot(memory=[1, 2, 3])
    _dumps(diagnostics.doctor_report(snap, "/s.npz", diagnostics.diagnose(snap)))


@pytest.mark.parametrize("field", ["generation", "ca_step"])
def test_reports_survive_a_counter_that_is_not_json_serializable(field):
    """`np.int64` fails the exact-int check; the report must still serialize."""
    snap = _snapshot(**{field: np.int64(5)})
    assert not _named(diagnostics.diagnose(snap))[f"{field}_non_negative_int"].ok
    document = json.loads(_dumps(diagnostics.info_report(snap, "/s.npz")))
    assert document[field] == 5


@pytest.mark.parametrize("value", ["not-a-number", None, object()])
def test_reports_survive_an_uncoercible_counter(value):
    snap = _snapshot(generation=value)
    assert diagnostics.info_report(snap, "/s")["generation"] is None
    _dumps(diagnostics.info_report(snap, "/s"))


def test_memory_shape_check_does_not_pass_on_a_non_three_d_lattice():
    """Regression: with a rank-2 lattice of shape (8, 8), the naive expected
    shape (8, 8, 8) matched a grid that is not 8 channels over the volume."""
    lattice = np.zeros((8, 8), dtype=np.uint8)
    memory = np.zeros((8, 8, 8), dtype=np.float32)
    checks = _named(diagnostics.diagnose(_snapshot(lattice=lattice, memory=memory)))
    assert not checks["lattice_rank_is_three"].ok
    assert not checks["memory_shape_matches_lattice"].ok


# ---------------------------------------------------------------------------
# Human formatters
# ---------------------------------------------------------------------------


def test_format_stat_renders_finite_values_unchanged():
    assert diagnostics.format_stat(1.5) == "+1.5000"
    assert diagnostics.format_stat(-0.25) == "-0.2500"


def test_format_stat_renders_non_finite_without_raising():
    """The JSON layer maps non-finite to None; the human table must cope."""
    assert diagnostics.format_stat(None) == "non-finite"


def test_format_percent_renders_none_without_raising():
    assert diagnostics.format_percent(None).strip() == "n/a"
    assert diagnostics.format_percent(12.5).strip() == "12.5"


def test_json_scalar_keeps_exact_ints_and_nulls_the_rest():
    assert diagnostics.json_scalar(5) == 5
    assert type(diagnostics.json_scalar(5)) is int
    assert diagnostics.json_scalar(float("nan")) is None
    assert diagnostics.json_scalar("x") is None
    assert diagnostics.json_scalar(None) is None


def test_format_doctor_tolerates_an_empty_check_list():
    assert diagnostics.format_doctor([], "/s")[-1].startswith("OK:")


def test_diagnose_is_side_effect_free():
    """Deterministic and non-mutating: the inputs are unchanged afterwards."""
    snap = _snapshot()
    lattice_before = snap.lattice.copy()
    memory_before = snap.memory_grid.copy()
    first = [(c.name, c.ok, c.detail) for c in diagnostics.diagnose(snap)]
    second = [(c.name, c.ok, c.detail) for c in diagnostics.diagnose(snap)]
    assert first == second
    np.testing.assert_array_equal(snap.lattice, lattice_before)
    np.testing.assert_array_equal(snap.memory_grid, memory_before)


def test_diagnostics_module_references_no_renderer():
    """Supplements -- does not replace -- the behavioural check in
    tests/test_observatory_cli.py that `doctor` imports no renderer module."""
    source = inspect.getsource(diagnostics)
    for banned in ("scatter3d", "slicer", "dashboard", "animation",
                   "matplotlib", "plotly", "pyplot"):
        assert banned not in source, f"diagnostics references {banned}"


# ===========================================================================
# Totality under hostile input
#
# The seam's whole promise is that a malformed runtime-contract value becomes
# a FAILED CHECK, never a traceback. That promise was false: several wrong
# dtypes reached `np.isfinite()`, `np.unique()` or `int()` and raised before
# the check that exists to reject them could be reported.
#
# These assert TOTALITY, not specific verdicts: for every input the checks are
# designed to reject, the whole pipeline -- diagnose, report construction,
# strict serialization, human formatting -- must complete. Which checks fail
# is asserted separately above; the claim here is that a report exists at all.
# ===========================================================================


class _Partial:
    """A snapshot-shaped object with fields deliberately missing.

    `diagnose()` reads its inputs with `getattr(..., None)`, so a library
    caller can hand it an incomplete object. The report builders must accept
    exactly what the checks accept.
    """

    def __init__(self, **fields):
        self.__dict__.update(fields)


def _raw(lattice, memory, generation=7, ca_step=11, best_fitness=0.5,
         source="/x/snap.npz"):
    """Build a snapshot with NO defaulting.

    `_snapshot()` substitutes a valid array when it is handed `None`, which
    would quietly turn the `non-array-none` cases into healthy snapshots and
    make them prove nothing. Here `None` means None.
    """
    return ObservatorySnapshot(
        lattice=lattice,
        memory_grid=memory,
        generation=generation,
        ca_step=ca_step,
        best_fitness=best_fitness,
        source_path=source,
    )


def _hostile_lattices():
    good = (2, 3, 4)
    return [
        ("uint8-valid", np.zeros(good, dtype=np.uint8)),
        ("int8", np.zeros(good, dtype=np.int8)),
        ("int16", np.zeros(good, dtype=np.int16)),
        ("int32", np.zeros(good, dtype=np.int32)),
        ("int64", np.zeros(good, dtype=np.int64)),
        ("uint16", np.zeros(good, dtype=np.uint16)),
        ("uint64", np.zeros(good, dtype=np.uint64)),
        ("int8-negative", np.full(good, -3, dtype=np.int8)),
        ("float32-integral", np.zeros(good, dtype=np.float32)),
        ("float64-fractional", np.full(good, 0.5, dtype=np.float64)),
        ("float-nan", np.full(good, np.nan, dtype=np.float64)),
        ("float-posinf", np.full(good, np.inf, dtype=np.float64)),
        ("float-neginf", np.full(good, -np.inf, dtype=np.float64)),
        ("bool", np.zeros(good, dtype=bool)),
        ("unicode", np.full(good, "x", dtype="<U5")),
        ("bytes", np.full(good, b"x", dtype="S5")),
        ("object-ints", np.array([[[1, 2], [3, 4]]], dtype=object)),
        ("object-strings", np.array([[["a", "b"], ["c", "d"]]], dtype=object)),
        # Jack's witness: elements that cannot be ordered against each other,
        # so `np.unique()`'s sort raises.
        ("object-mixed-unorderable", np.array([[["x", 1]]], dtype=object)),
        ("object-none", np.array([[[None, None]]], dtype=object)),
        ("complex64", np.zeros(good, dtype=np.complex64)),
        ("complex128", np.zeros(good, dtype=np.complex128)),
        ("datetime64", np.zeros(good, dtype="datetime64[s]")),
        ("rank0", np.array(1, dtype=np.uint8)),
        ("rank1", np.zeros((6,), dtype=np.uint8)),
        ("rank2", np.zeros((3, 4), dtype=np.uint8)),
        ("rank4", np.zeros((2, 2, 2, 2), dtype=np.uint8)),
        ("zero-size", np.zeros((0, 3, 4), dtype=np.uint8)),
        ("zero-size-all", np.zeros((0, 0, 0), dtype=np.uint8)),
        ("unknown-states", np.full(good, 200, dtype=np.uint8)),
        ("non-array-list", [[[1]]]),
        ("non-array-none", None),
        ("non-array-str", "lattice"),
    ]


def _hostile_memories():
    good = (2, 3, 4)
    ok_shape = (NUM_CHANNELS,) + good
    return [
        ("float32-valid", np.zeros(ok_shape, dtype=np.float32)),
        ("float64", np.zeros(ok_shape, dtype=np.float64)),
        ("float16", np.zeros(ok_shape, dtype=np.float16)),
        ("int32", np.zeros(ok_shape, dtype=np.int32)),
        ("uint8", np.zeros(ok_shape, dtype=np.uint8)),
        ("bool", np.zeros(ok_shape, dtype=bool)),
        ("complex64", np.zeros(ok_shape, dtype=np.complex64)),
        ("complex128", np.zeros(ok_shape, dtype=np.complex128)),
        ("datetime64", np.zeros(ok_shape, dtype="datetime64[s]")),
        ("unicode", np.full(ok_shape, "x", dtype="<U5")),
        ("bytes", np.full(ok_shape, b"x", dtype="S5")),
        ("object-numbers", np.array([[[[1.0]]]], dtype=object)),
        # Jack's witness: `np.isfinite()` raises TypeError on object dtype.
        ("object-strings", np.array([[[["x"]]]], dtype=object)),
        ("object-mixed", np.array([[[["x", 1.0]]]], dtype=object)),
        ("object-none", np.array([[[[None]]]], dtype=object)),
        ("nan", np.full(ok_shape, np.nan, dtype=np.float32)),
        ("posinf", np.full(ok_shape, np.inf, dtype=np.float32)),
        ("neginf", np.full(ok_shape, -np.inf, dtype=np.float32)),
        ("zero-size", np.zeros((NUM_CHANNELS, 0, 3, 4), dtype=np.float32)),
        ("rank0", np.array(1.0, dtype=np.float32)),
        ("wrong-rank-3", np.zeros((NUM_CHANNELS, 3, 4), dtype=np.float32)),
        ("wrong-rank-5", np.zeros((NUM_CHANNELS, 2, 3, 4, 1), dtype=np.float32)),
        ("wrong-channels-3", np.zeros((3,) + good, dtype=np.float32)),
        ("wrong-channels-9", np.zeros((9,) + good, dtype=np.float32)),
        ("wrong-spatial", np.zeros((NUM_CHANNELS, 9, 9, 9), dtype=np.float32)),
        ("non-array-list", [0.0]),
        ("non-array-none", None),
        ("non-array-str", "memory"),
    ]


class _Uncoercible:
    """A hostile counter whose float conversion fails."""

    def __float__(self):
        raise ValueError("no float for you")


def _hostile_metadata():
    return [
        ("int", 7),
        ("zero", 0),
        ("negative", -1),
        ("bool-true", True),
        ("bool-false", False),
        ("float", 1.5),
        ("float-nan", float("nan")),
        ("float-inf", float("inf")),
        ("float-neginf", float("-inf")),
        ("str", "9"),
        ("none", None),
        ("np-int64", np.int64(5)),
        ("np-float32", np.float32(1.5)),
        ("np-bool", np.bool_(True)),
        # `float()` raises OverflowError -- an ArithmeticError, so NOT caught
        # by a (TypeError, ValueError) handler.
        ("huge-int", 10 ** 400),
        ("huge-negative-int", -(10 ** 400)),
        ("complex", complex(1, 2)),
        ("uncoercible", _Uncoercible()),
        ("object", object()),
        ("list", [1, 2]),
    ]


def _assert_total(snapshot, source="/x/snap.npz"):
    """The seam must produce a complete, strict, deterministic report.

    Asserts the whole promise at once: diagnose returns rather than raises,
    all 13 checks are present in the established order, both report kinds
    build, strict serialization succeeds, human formatting succeeds, and a
    second run over the same input produces identical bytes.
    """
    checks = diagnostics.diagnose(snapshot)
    assert len(checks) == 13
    assert [c.name for c in checks] == [c.name for c in diagnostics.diagnose(snapshot)]
    assert all(type(c.ok) is bool for c in checks), "check.ok must be a real bool"
    assert all(type(c.detail) is str for c in checks)

    report = diagnostics.doctor_report(snapshot, source, checks)
    text = _dumps(report)                     # strict: allow_nan=False
    assert json.loads(text) == report
    assert "NaN" not in text and "Infinity" not in text

    info = _dumps(diagnostics.info_report(snapshot, source))
    assert "NaN" not in info and "Infinity" not in info

    lines = diagnostics.format_doctor(checks, source)
    assert lines[-1].startswith(("OK:", "FAILED:"))
    assert len([ln for ln in lines if ln.startswith("  [")]) == 13

    # Deterministic: byte-identical on a second pass over the same input.
    assert _dumps(diagnostics.doctor_report(
        snapshot, source, diagnostics.diagnose(snapshot))) == text
    return checks, report, lines


@pytest.mark.parametrize(
    "lattice", [pytest.param(v, id=k) for k, v in _hostile_lattices()]
)
def test_diagnose_is_total_over_lattice_representations(lattice):
    """Jack's witness among them: a mixed object lattice reached `np.unique()`
    and raised TypeError before `lattice_dtype` could be reported failed."""
    memory = np.zeros((NUM_CHANNELS, 2, 3, 4), dtype=np.float32)
    _assert_total(_raw(lattice, memory))


@pytest.mark.parametrize(
    "memory", [pytest.param(v, id=k) for k, v in _hostile_memories()]
)
def test_diagnose_is_total_over_memory_representations(memory):
    """Jack's witness among them: an object-dtype grid reached `np.isfinite()`
    and raised TypeError."""
    lattice = np.zeros((2, 3, 4), dtype=np.uint8)
    lattice[0, 0, 0] = 1
    _assert_total(_raw(lattice, memory))


@pytest.mark.parametrize(
    "value", [pytest.param(v, id=k) for k, v in _hostile_metadata()]
)
@pytest.mark.parametrize("field", ["generation", "ca_step", "best_fitness"])
def test_diagnose_is_total_over_metadata(field, value):
    """`float()` raises OverflowError for a huge int and TypeError for a
    complex; neither may escape the checks or the report builders."""
    _assert_total(_snapshot(**{field: value}))


@pytest.mark.parametrize(
    "lattice", [pytest.param(v, id=k) for k, v in _hostile_lattices()[:12]]
)
@pytest.mark.parametrize(
    "memory", [pytest.param(v, id=k) for k, v in _hostile_memories()[:12]]
)
def test_diagnose_is_total_over_combined_hostility(lattice, memory):
    """Malformed lattice and malformed memory together: no gate may depend on
    the other side being well-formed."""
    _assert_total(_raw(lattice, memory))


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"lattice": np.zeros((2, 3, 4), dtype=np.uint8)},
        {"memory_grid": np.zeros((8, 2, 3, 4), dtype=np.float32)},
        {"generation": 1, "ca_step": 2, "best_fitness": 0.5},
    ],
    ids=["nothing", "lattice-only", "memory-only", "metadata-only"],
)
def test_reports_survive_a_snapshot_with_missing_attributes(fields):
    """`diagnose()` reads with `getattr(..., None)`, so it accepts an
    incomplete object; the report builders must accept the same."""
    _assert_total(_Partial(**fields))


# --- the two reproduced blockers, named explicitly -------------------------


def test_object_memory_grid_does_not_reach_isfinite():
    """Reproducer: `np.isfinite(np.array([[[["x"]]]], dtype=object))` raises
    TypeError. The finiteness check must report a failure instead."""
    snap = _snapshot(memory=np.array([[[["x"]]]], dtype=object))
    checks = _named(diagnostics.diagnose(snap))
    assert not checks["memory_values_finite"].ok
    assert not checks["memory_dtype"].ok


def test_unorderable_object_lattice_does_not_reach_unique():
    """Reproducer: `np.unique(np.array([[["x", 1]]], dtype=object))` sorts and
    raises TypeError comparing str with int. `lattice_dtype` and
    `lattice_states_known` must both be reported failed instead."""
    snap = _snapshot(
        lattice=np.array([[["x", 1]]], dtype=object),
        memory=np.zeros((NUM_CHANNELS, 1, 1, 2), dtype=np.float32),
    )
    checks = _named(diagnostics.diagnose(snap))
    assert not checks["lattice_dtype"].ok
    assert not checks["lattice_states_known"].ok


@pytest.mark.parametrize("dtype", ["<U5", "S5", "O", "complex128", "datetime64[s]"])
def test_unsupported_lattice_dtype_never_passes_the_vocabulary_check(dtype):
    """A skipped dependent evaluation is not a passing result: when a dtype is
    unsafe to inspect, the vocabulary check reports failure, never success."""
    lattice = np.zeros((2, 3, 4), dtype=dtype)
    checks = _named(diagnostics.diagnose(_snapshot(lattice=lattice)))
    assert not checks["lattice_dtype"].ok
    assert not checks["lattice_states_known"].ok


@pytest.mark.parametrize("dtype", ["<U5", "S5", "O", "complex128", "datetime64[s]"])
def test_unsupported_memory_dtype_never_passes_the_finiteness_check(dtype):
    memory = np.zeros((NUM_CHANNELS, 2, 3, 4), dtype=dtype)
    checks = _named(diagnostics.diagnose(_snapshot(memory=memory)))
    assert not checks["memory_dtype"].ok
    assert not checks["memory_values_finite"].ok


def test_huge_integer_fitness_is_reported_not_raised():
    """`float(10**400)` raises OverflowError, an ArithmeticError, so it is not
    caught by a (TypeError, ValueError) handler."""
    checks = _named(diagnostics.diagnose(_snapshot(best_fitness=10 ** 400)))
    assert not checks["best_fitness_finite"].ok


def test_huge_integer_counter_still_serializes_strictly():
    snap = _snapshot(generation=10 ** 400)
    assert not _named(diagnostics.diagnose(snap))["generation_non_negative_int"].ok
    _dumps(diagnostics.info_report(snap, "/s"))


def test_boolean_fitness_is_not_silently_treated_as_one_point_zero():
    """`True` is not a fitness value. The check must fail, and the report must
    not present it as the number 1.0."""
    snap = _snapshot(best_fitness=True)
    assert not _named(diagnostics.diagnose(snap))["best_fitness_finite"].ok
    assert diagnostics.info_report(snap, "/s")["best_fitness"] is None


def test_fractional_float_counter_is_not_silently_truncated():
    snap = _snapshot(generation=2.7)
    assert not _named(diagnostics.diagnose(snap))["generation_non_negative_int"].ok
    assert diagnostics.info_report(snap, "/s")["generation"] != 2


def test_hostile_inputs_are_not_modified():
    """Side-effect freedom under hostile input, not merely healthy input."""
    lattice = np.array([[["x", 1]]], dtype=object)
    memory = np.array([[[["x"]]]], dtype=object)
    lattice_before = lattice.tolist()
    memory_before = memory.tolist()
    _assert_total(_snapshot(lattice=lattice, memory=memory))
    assert lattice.tolist() == lattice_before
    assert memory.tolist() == memory_before


@pytest.mark.parametrize(
    "lattice", [pytest.param(v, id=k) for k, v in _hostile_lattices()]
)
def test_no_detail_grows_with_the_payload(lattice):
    """No detail may grow with the data, however hostile or large."""
    memory = np.zeros((NUM_CHANNELS, 2, 3, 4), dtype=np.float32)
    checks = diagnostics.diagnose(_raw(lattice, memory))
    for check in checks:
        assert len(check.detail) < 200, f"{check.name}: {check.detail[:80]}"


# --- human output must not be forgeable ------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "/x/a\nOK: all 13 checks passed.npz",
        "/x/a\r\n  [PASS] lattice_is_array  forged.npz",
        "/x/a\rFAILED: 0 of 13 checks did not pass.npz",
        "/x/a\u2028  [PASS] forged.npz",
        "/x/a\u2029  [PASS] forged.npz",
        "/x/a\x85OK: all 13 checks passed.npz",
        "/x/a\v  [PASS] forged.npz",
        "/x/a\f  [PASS] forged.npz",
        "/x/a\x1c  [PASS] forged.npz",
        "/x/a\x1d  [PASS] forged.npz",
        "/x/a\x1e  [PASS] forged.npz",
    ],
    ids=["lf", "crlf", "cr", "line-sep", "para-sep", "nel", "vtab",
         "formfeed", "file-sep", "group-sep", "record-sep"],
)
def test_a_source_path_cannot_forge_report_lines(hostile):
    """A pathname is untrusted data. Human `doctor` output must not let one
    inject what looks like an extra check row or a second summary line.

    `str.splitlines()` splits on more than \\n and \\r -- \\v, \\f, \\x1c-\\x1e,
    \\x85, \\u2028 and \\u2029 all count -- so the header line is checked
    against that full set, not just the obvious two.
    """
    checks = diagnostics.diagnose(_snapshot())
    lines = diagnostics.format_doctor(checks, hostile)

    assert len(lines[0].splitlines()) == 1, "header spans more than one line"
    body = [ln for ln in lines if ln.startswith("  [")]
    assert len(body) == 13, f"forged check rows: {len(body)}"
    summaries = [ln for ln in lines if ln.startswith(("OK:", "FAILED:"))]
    assert len(summaries) == 1, f"forged summary lines: {len(summaries)}"


def test_json_mode_keeps_a_hostile_path_as_ordinary_escaped_data():
    """JSON needs no sanitising -- ordinary escaping already makes the newline
    inert -- but it must round-trip to exactly what was supplied."""
    hostile = "/x/a\nOK: all 13 checks passed.npz"
    report = diagnostics.doctor_report(
        _snapshot(), hostile, diagnostics.diagnose(_snapshot())
    )
    text = _dumps(report)
    assert "\n" not in text, "raw newline leaked into the JSON document"
    assert json.loads(text)["source"] == hostile
