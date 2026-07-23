"""Behavioral tests for scripts/medusa_api.py runtime reporting.

Scope (bounded task): the REST API's runtime-reporting contracts only —
  * /api/status must report the *configured* launch port, not the module
    default;
  * a single-sourced semantic API version is surfaced by both / and
    /api/health;
  * /api/health stays a process-liveness endpoint (status/service/timestamp
    preserved, version added), independent of snapshot or engine freshness.

These are the first behavioral tests for this module. They run entirely
in-process via Flask's test client: no live server is started, no network
port is bound, no OS process is launched, and no real repository data is read
(the snapshot directory is monkeypatched to a temp path and any snapshot file
is a synthetic byte blob — /api/status only stats it, never loads it).

The event bus (a ZMQ PUB socket + telemetry watcher thread) is disabled BEFORE
the module is imported, so importing it here binds no socket and starts no
thread.
"""

from __future__ import annotations

import os

# Disable the event-bus PUB socket / watcher thread before importing the module
# under test, so import binds no network port and starts no background thread.
os.environ["MEDUSA_EVENT_BUS_DISABLED"] = "1"

import pytest

pytest.importorskip("flask")  # flask is an optional dependency for the REST API.

from scripts import medusa_api  # noqa: E402  (import after env flag is set)


# -- fixtures ---------------------------------------------------------------


@pytest.fixture
def client():
    return medusa_api.app.test_client()


@pytest.fixture(autouse=True)
def _restore_configured_port():
    """The Flask app is a module singleton; restore its configured port after
    every test so port mutations never leak across tests."""
    saved = medusa_api.app.config.get("API_PORT")
    yield
    medusa_api.app.config["API_PORT"] = saved


@pytest.fixture
def empty_data_dir(tmp_path, monkeypatch):
    """Point the module's DATA_DIR at an empty temp dir (no snapshots)."""
    monkeypatch.setattr(medusa_api, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def snapshot_data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temp dir containing one synthetic snapshot file.

    The file is a >1 MiB byte blob so _find_latest_snapshot returns it; its
    contents are never parsed by /api/status (which only stats it)."""
    snap = tmp_path / "v070_gen000123.npz"
    snap.write_bytes(b"\x00" * 2_000_000)
    monkeypatch.setattr(medusa_api, "DATA_DIR", tmp_path)
    return tmp_path


_STATUS_KEYS = {
    "latest_snapshot",
    "snapshot_age_seconds",
    "snapshot_size_mb",
    "total_snapshots",
    "engine_alive",
    "api_port",
}


# -- failing-first pins (RED on pre-fix code) -------------------------------


def test_status_reports_configured_port_not_module_default(client, snapshot_data_dir):
    """FAILING-FIRST: a launch configured for port 9090 must be reported as
    9090. Pre-fix /api/status hard-codes the module default, so it reports
    8080 and this assertion fails."""
    medusa_api.app.config["API_PORT"] = 9090
    body = client.get("/api/status").get_json()
    assert body["api_port"] == 9090


def test_health_includes_api_version(client):
    """FAILING-FIRST: /api/health must carry the semantic API version. Pre-fix
    the health body has no 'version' key, so this fails."""
    body = client.get("/api/health").get_json()
    assert body.get("version") == "1.2.0"


# -- version single-sourcing ------------------------------------------------


def test_api_version_constant_is_the_existing_semantic_value():
    assert medusa_api.API_VERSION == "1.2.0"


def test_root_and_health_share_the_single_sourced_version(client):
    root_version = client.get("/").get_json()["version"]
    health_version = client.get("/api/health").get_json()["version"]
    assert root_version == health_version == medusa_api.API_VERSION


# -- /api/health liveness semantics preserved -------------------------------


def test_health_preserves_status_service_timestamp(client):
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert body["service"] == "medusa-api"
    assert isinstance(body["timestamp"], (int, float))


def test_health_is_ok_with_no_snapshot_or_stale_engine_evidence(client, empty_data_dir):
    """Health is process-liveness only: it stays 200/"ok" even when there is
    no snapshot at all (and therefore no fresh-engine evidence)."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["service"] == "medusa-api"
    assert body["version"] == medusa_api.API_VERSION
    # Liveness must not encode snapshot/engine freshness fields.
    assert "engine_alive" not in body
    assert "snapshot_age_seconds" not in body


# -- /api/status contracts preserved ----------------------------------------


def test_status_returns_404_without_snapshots(client, empty_data_dir):
    """Existing 404 contract is unchanged when no snapshot exists."""
    resp = client.get("/api/status")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "No snapshots found"}


def test_status_with_snapshot_reports_configured_port_and_all_keys(client, snapshot_data_dir):
    """With a snapshot present, /api/status is 200, reports the configured
    custom port, and retains every existing response key."""
    medusa_api.app.config["API_PORT"] = 9090
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["api_port"] == 9090
    assert _STATUS_KEYS.issubset(body.keys())
    assert body["latest_snapshot"] == "v070_gen000123.npz"
    assert body["total_snapshots"] == 1
    assert body["engine_alive"] in (True, False)


def test_status_default_port_is_module_default_at_import_time(client, snapshot_data_dir):
    """Import-time / unconfigured fallback is the module default 8080."""
    body = client.get("/api/status").get_json()
    assert body["api_port"] == 8080


# -- public CLI -> app configuration wiring (socket-free) -------------------


def test_public_cli_port_wires_into_runtime_config():
    """Prove the public --port value flows into the app's runtime config via
    the same parser the __main__ block uses — without binding a socket or
    running a server."""
    parser = medusa_api._build_arg_parser()
    args = parser.parse_args(["--port", "9090"])
    returned = medusa_api.configure_runtime(args)
    assert returned is medusa_api.app
    assert medusa_api.app.config["API_PORT"] == 9090


def test_public_cli_default_port_is_8080():
    parser = medusa_api._build_arg_parser()
    args = parser.parse_args([])
    medusa_api.configure_runtime(args)
    assert medusa_api.app.config["API_PORT"] == 8080


def test_configured_port_zero_is_reported_verbatim(client, snapshot_data_dir):
    """--port 0 is honestly the *configured* launch port (0), not the OS-bound
    port an actual server would select at bind time."""
    parser = medusa_api._build_arg_parser()
    args = parser.parse_args(["--port", "0"])
    medusa_api.configure_runtime(args)
    body = client.get("/api/status").get_json()
    assert body["api_port"] == 0


# -- event-bus disabled during tests ----------------------------------------


def test_event_bus_disabled_during_tests():
    """The module was imported with the event bus disabled: no publisher and
    no watcher were constructed (no socket bound, no thread started)."""
    assert os.environ.get("MEDUSA_EVENT_BUS_DISABLED") == "1"
    assert medusa_api._event_publisher is None
    assert medusa_api._state_watcher is None
