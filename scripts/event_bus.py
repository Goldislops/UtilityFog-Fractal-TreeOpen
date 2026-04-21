"""Phase 18 PR 3 — Event Bus (ZMQ PUB/SUB).

Passive broadcasting antenna for the Medusa matrix: a ZeroMQ PUB socket
(default `tcp://*:8081`) publishes typed events that agents subscribe
to by topic. Complements the existing REST pull model — agents listen
for interesting events rather than polling endpoints.

Does not touch `continuous_evolution_ca.py`. Events come from two
sources:
  1. In-process publishes from other modules (e.g. `TuningState.commit`
     publishing `tuning.committed` directly).
  2. `StateWatcher` — a background daemon thread that tails the on-disk
     telemetry artifacts (`data/telemetry_*.json`) and publishes
     `telemetry.5min` events when new files appear.

## Topics

Stable contract for downstream agents (topic strings MUST NOT change
lightly — they're part of the public API):

  - `tuning.committed`   — a tuning proposal was accepted + applied
  - `tuning.rejected`    — safety gate denied a propose / commit
  - `tuning.rolled_back` — a rollback was committed
  - `telemetry.5min`     — new 5-min telemetry JSON dropped in `data/`

The other topics from PHASE_18.md (`sage.promoted`, `acoustic.spike`,
`census.delta`) require state-diffing logic; they're a follow-up PR
once we have a canonical "last seen census" cursor.

## Frame layout

Events go out as ZMQ multipart messages, 3 frames:
  frame 0: topic        (UTF-8 bytes, e.g. b"tuning.committed")
  frame 1: iso timestamp (UTF-8 bytes, e.g. b"2026-04-21T08:20:15Z")
  frame 2: payload      (UTF-8 JSON bytes)

Subscribers filter by topic prefix via `setsockopt(SUBSCRIBE, ...)`.
Use `""` (empty string) to subscribe to all topics.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import zmq


DEFAULT_ENDPOINT = "tcp://*:8081"
DEFAULT_CLIENT_ENDPOINT = "tcp://127.0.0.1:8081"

# Topic constants — import these rather than hard-coding strings at call sites.
TOPIC_TUNING_COMMITTED = "tuning.committed"
TOPIC_TUNING_REJECTED = "tuning.rejected"
TOPIC_TUNING_ROLLED_BACK = "tuning.rolled_back"
TOPIC_TELEMETRY_5MIN = "telemetry.5min"

ALL_TOPICS = (
    TOPIC_TUNING_COMMITTED,
    TOPIC_TUNING_REJECTED,
    TOPIC_TUNING_ROLLED_BACK,
    TOPIC_TELEMETRY_5MIN,
)


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


class EventPublisher:
    """Thread-safe wrapper around a ZMQ PUB socket.

    One publisher per process. Use as a context manager or call `close()`
    explicitly. Publishing after close is a no-op (silent) rather than an
    error — event publishing should never take down a caller.
    """

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, *, hwm: int = 1000) -> None:
        self.endpoint = endpoint
        self.ctx = zmq.Context.instance()
        self.sock: zmq.Socket = self.ctx.socket(zmq.PUB)
        self.sock.setsockopt(zmq.LINGER, 500)
        self.sock.setsockopt(zmq.SNDHWM, hwm)
        self.sock.bind(endpoint)
        self._lock = threading.Lock()
        self._closed = False

    def publish(self, topic: str, payload: dict) -> None:
        if self._closed:
            return
        ts = _now_iso()
        try:
            data = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        except (TypeError, ValueError):
            # Never take down the caller for a bad payload.
            return
        with self._lock:
            if self._closed:
                return
            try:
                self.sock.send_multipart(
                    [topic.encode("utf-8"), ts.encode("utf-8"), data],
                    flags=zmq.DONTWAIT,
                )
            except zmq.Again:
                # HWM reached — drop silently rather than block the caller.
                pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.sock.close(linger=500)
            except Exception:
                pass

    def __enter__(self) -> "EventPublisher":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class EventSubscriber:
    """Helper SUB-side wrapper. Primarily used by tests and by future agent
    orchestration code. Production traffic goes through `EventPublisher`
    on the other end.
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_CLIENT_ENDPOINT,
        topics: Optional[list[str]] = None,
    ) -> None:
        self.ctx = zmq.Context.instance()
        self.sock: zmq.Socket = self.ctx.socket(zmq.SUB)
        self.sock.setsockopt(zmq.LINGER, 500)
        self.sock.connect(endpoint)
        for topic in topics if topics is not None else [""]:
            self.sock.setsockopt_string(zmq.SUBSCRIBE, topic)
        self._closed = False

    def recv(self, timeout_ms: int = 1000) -> Optional[tuple[str, str, dict]]:
        """Return (topic, timestamp, payload) or None on timeout."""
        if self._closed:
            raise RuntimeError("subscriber is closed")
        self.sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        try:
            topic_b, ts_b, data_b = self.sock.recv_multipart()
        except zmq.Again:
            return None
        try:
            payload = json.loads(data_b.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {"_raw": data_b.decode("utf-8", errors="replace")}
        return topic_b.decode("utf-8"), ts_b.decode("utf-8"), payload

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self.sock.close(linger=500)
            except Exception:
                pass

    def __enter__(self) -> "EventSubscriber":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class StateWatcher(threading.Thread):
    """Background daemon that tails `data/telemetry_*.json` and publishes
    `telemetry.5min` events when a new file appears.

    On startup it marks all currently-existing telemetry files as "seen"
    — we only emit for genuinely new files, not historical ones. The
    engine's existing 5-min telemetry dumps (Phase 14d watchdog + beyond)
    are the source of truth; this watcher just broadcasts their arrival.

    Runs as a daemon thread so it doesn't block Python shutdown.
    """

    def __init__(
        self,
        publisher: EventPublisher,
        data_dir: Path,
        *,
        poll_interval_s: float = 10.0,
        glob_pattern: str = "telemetry_*.json",
    ) -> None:
        super().__init__(daemon=True, name="StateWatcher")
        self.publisher = publisher
        self.data_dir = Path(data_dir)
        self.poll_interval_s = float(poll_interval_s)
        self.glob_pattern = glob_pattern
        self._stop = threading.Event()
        self._seen: set[str] = set()

    def run(self) -> None:
        # Bootstrap: existing files are not "new".
        if self.data_dir.exists():
            self._seen = {p.name for p in self.data_dir.glob(self.glob_pattern)}
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                # Daemon thread must never die.
                pass
            self._stop.wait(self.poll_interval_s)

    def poll_once(self) -> int:
        """Run one polling iteration. Returns the number of events published.
        Exposed for tests — lets them drive the watcher synchronously without
        waiting for the real poll interval.
        """
        if not self.data_dir.exists():
            return 0
        current = sorted(
            self.data_dir.glob(self.glob_pattern),
            key=lambda p: p.name,
        )
        new_files = [p for p in current if p.name not in self._seen]
        count = 0
        for path in new_files:
            self._publish_for(path)
            self._seen.add(path.name)
            count += 1
        return count

    def _publish_for(self, path: Path) -> None:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            # File may still be mid-write; skip this round and try next poll.
            self._seen.discard(path.name)
            return
        self.publisher.publish(
            TOPIC_TELEMETRY_5MIN,
            {"file": path.name, "telemetry": data},
        )

    def stop(self) -> None:
        self._stop.set()


__all__ = [
    "DEFAULT_ENDPOINT",
    "DEFAULT_CLIENT_ENDPOINT",
    "TOPIC_TUNING_COMMITTED",
    "TOPIC_TUNING_REJECTED",
    "TOPIC_TUNING_ROLLED_BACK",
    "TOPIC_TELEMETRY_5MIN",
    "ALL_TOPICS",
    "EventPublisher",
    "EventSubscriber",
    "StateWatcher",
]
