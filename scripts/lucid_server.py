"""Lucid Dreaming WebSocket Server -- Phase 12B

Streams live lattice state from the fog engine to the 3D browser visualizer.
Receives click/drag interactions from the browser for boundary polishing.

Usage:
    python scripts/lucid_server.py [--port 8765] [--data-dir data]

The server:
  1. Watches for new .npz snapshots in data/
  2. On each new snapshot, extracts cell positions + states + ages
  3. Streams render data to connected browsers via WebSocket
  4. Receives interaction events (click, drag, polish) from browser
"""

import asyncio
import json
import time
import os
import sys
from pathlib import Path

import numpy as np

# This module is documented as `python scripts/lucid_server.py`, which leaves
# the repository root off sys.path. The shared snapshot guard lives in the
# `scripts` package, so the root is put on the path before importing it -- one
# canonical module name either way, which matters because the guard's
# exception type is caught by identity below.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # Appended, not prepended: this must not be able to shadow a standard
    # library module with a repository file of the same name.
    sys.path.append(str(PROJECT_ROOT))

from scripts.snapshot_archive_guard import (  # noqa: E402
    PRODUCTION_POLICY as SNAPSHOT_POLICY,
)
from scripts.snapshot_archive_guard import (  # noqa: E402
    DISCOVERY_CACHE_TTL_SECONDS,
    PRODUCTION_DISCOVERY_POLICY,
    SnapshotArchiveRejected,
    SnapshotDiscoveryCache,
    admit_snapshot,
    entry_fingerprint,
    first_admissible,
)

#: A metadata failure is usually one rotated file and says nothing worth
#: printing. A PERSISTENT one — a dropped share, a permissions change — means
#: the watcher is running blind, and silence there is its own defect. One fixed
#: line, at most this often, on a monotonic clock so a system clock step cannot
#: suppress or spam it.
METADATA_WARNING_INTERVAL = 300.0

#: TWO independent lanes, and the separation is the whole point.
#:
#: Discovery and the watcher's second fingerprint read are different syscalls
#: on different entries, and they fail independently. With one shared counter a
#: persistent second-read failure warned on EVERY poll: discovery succeeded,
#: cleared the state, then the second read failed into a freshly-armed lane.
#: The rate limit was real and simply never applied. Success in one lane must
#: not be able to clear an active failure episode in the other.
DISCOVERY_LANE = "discovery"
FINGERPRINT_LANE = "fingerprint"
_metadata_state = {
    DISCOVERY_LANE: {"failures": 0, "warned_at": None},
    FINGERPRINT_LANE: {"failures": 0, "warned_at": None},
}

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)

# Configuration
DATA_DIR = "data"
WS_PORT = 8765
POLL_INTERVAL = 2.0  # seconds between snapshot checks
MAX_CELLS = 15000    # reduced for browser performance    # max cells to stream per frame

# Track state
last_snapshot_path = None
last_snapshot_mtime = 0
connected_clients = set()


#: The watcher's bounded discovery, shared with every client connection.
#:
#: Discovery here is synchronous on ONE asyncio event loop. The watcher polled
#: every two seconds and every client connection scanned the directory AGAIN
#: before its initial frame, so at the calibrated caps a connect burst was a
#: burst of cap-level directory work on the loop that also serves every frame.
#:
#: The watcher is now the sole owner. Clients consume its completed immutable
#: listing and never scan -- see `find_latest_snapshot`. There is no lock
#: around construction because there is no concurrency to guard: one event
#: loop, and discovery is synchronous within it.
#:
#: Keyed on the data directory, because a cache is coherent for exactly one
#: directory. `DATA_DIR` is rebound once from `--data-dir` before the loop
#: starts, so in production this is built once and reused.
_WATCHER_CACHE = None


def _discovery_cache(data_dir):
    """The shared bounded discovery for `data_dir`, built on first use."""
    global _WATCHER_CACHE
    directory = Path(os.fspath(data_dir))
    cache = _WATCHER_CACHE
    if cache is None or cache.directory != directory:
        cache = SnapshotDiscoveryCache(
            directory=directory,
            policy=PRODUCTION_DISCOVERY_POLICY,
            ttl=DISCOVERY_CACHE_TTL_SECONDS,
        )
        _WATCHER_CACHE = cache
    return cache


def find_latest_snapshot(data_dir, *, allow_refresh=False):
    """Find the most recent .npz snapshot from the watcher's completed listing.

    Ordering uses non-following metadata and skips entries that vanish during
    enumeration. `os.path.getmtime` follows symlinks, so a link could borrow
    its target's modification time to become "newest" before admission had any
    say, and it raises `OSError` for an entry rotated mid-sort -- which, from
    inside the watcher's loop, reached a handler that prints the exception, and
    `OSError`'s message carries the full attacker-chosen path.

    A dangling link or a symlink loop still `lstat`s, so it remains a candidate
    and is refused by `admit_snapshot` with a typed reason rather than
    disappearing from selection unrecorded.

    Selection is a bounded newest-first SEARCH, not just "the newest file".
    Without it one unusable archive with the newest modification time stalls
    the watcher outright -- and the producer writes straight to its final path
    with no temporary-and-rename, so a partially written snapshot IS the newest
    file for as long as the write takes. When nothing in the window is
    admissible the newest candidate is returned anyway, so the existing typed
    refusal runs and is logged rather than being silently reported as "no
    snapshots".

    Who may scan
    ------------
    Discovery used to be `order_candidates(glob.glob(pattern))`, run afresh by
    the watcher AND by every client connection. `glob` is unbounded by
    construction -- `glob.glob` is `list(iglob(...))`, and even `iglob` reaches
    `_listdir`, which is `return list(it)` -- so nothing downstream could bound
    it, and the per-connection copy multiplied the whole cost by the number of
    clients.

    `allow_refresh` is now the only way a scan happens, and it defaults to
    False so a caller that forgets cannot start one by accident. The watcher
    passes True; client connections do not, and therefore perform zero
    directory work no matter how many arrive or how fast. The 10-second refresh
    budget is generous against a 600-second producer cadence.

    The four states, kept apart
    --------------------------
    A known bounded discovery FAILURE returns None and notes the discovery
    lane: no frame is sent, no stale listing is served, and new clients get no
    initial frame until a refresh succeeds. Candidates that matched but could
    not be described also return None and note the lane -- the watcher is
    running blind, and reporting that as an empty directory would hide it. A
    clean EMPTY directory is a completed success: no warning, no failure state,
    and the lane is left exactly as it was. An archive refusal is downstream of
    all of this and never reaches here at all.
    """
    with _discovery_cache(data_dir).borrow(allow_refresh=allow_refresh) as listing:
        if not listing.available:
            # A known failure is worth the lane; "the watcher has not run yet"
            # is not, and a client must never be the one to report it.
            if allow_refresh and listing.failed:
                _note_metadata_failure(DISCOVERY_LANE)
            return None

        # Candidates matched but NONE could be described. That is not an
        # empty directory, and it must not be reported as one: it means the
        # watcher is running blind. Warned about once, rate-limited, path-free.
        blind = not listing.ordered and bool(listing.unreadable)

        if allow_refresh:
            # The lane records whether the WATCHER is running blind, so only
            # the caller that actually performed a discovery may move it. A
            # client connection did no directory work: it has nothing to
            # report, and no standing to declare someone else's episode over.
            # One poll is one lane event, however many clients connect in
            # between.
            if blind:
                _note_metadata_failure(DISCOVERY_LANE)
            else:
                # A completed discovery ends the episode whatever it found. A
                # clean EMPTY directory is a success -- the watcher can see the
                # directory perfectly well, there is simply nothing in it -- so
                # it re-arms exactly as an ordered listing does. Leaving the
                # episode open here kept a later, genuinely new failure
                # suppressed behind a rate limit armed minutes earlier.
                #
                # Only the DISCOVERY lane. Clearing both here is what made the
                # second read's rate limit ineffective: discovery succeeds on
                # every poll, so a shared state was re-armed on every poll.
                _clear_metadata_failures(DISCOVERY_LANE)

        if blind:
            return None

        # Selection and admission run while the listing is held, and nothing is
        # retained afterwards: no selected path is cached and no admission
        # verdict is cached, so the caller's own load re-admits its descriptor.
        # A clean empty listing falls through here and returns None, which is
        # the established no-frame outcome and is NOT a failure.
        return first_admissible(
            listing.ordered,
            data_dir=data_dir,
            policy=SNAPSHOT_POLICY,
        )


def extract_render_data(snap_path):
    """Extract cell positions, states, and ages from a snapshot.

    ``allow_pickle=False`` -- no pickled member is ever loaded
    ---------------------------------------------------------
    An NPZ member of object dtype is stored as a pickle, so loading one with
    pickle enabled is arbitrary code execution by construction. This function
    is reached on every client connect, and from the watched directory
    whenever the newest snapshot's path or mtime CHANGES -- not on every poll,
    which only re-checks. Either way an archive dropped into ``data/`` would be
    unpickled without anyone asking. NumPy now refuses such a member with a ``ValueError``
    instead.

    Passed EXPLICITLY although NumPy's default is already ``False``: relying
    on the default would make the property invisible at the call site and
    silently reversible by an upstream change. There is deliberately no
    fallback retry and no override.

    Archive lifetime
    ----------------
    The three values are materialised inside the ``with`` block and the
    archive is closed before any downstream work begins -- including the
    ``state.shape[0]`` inspection, the non-void search and the per-cell loop,
    which previously ran for up to ``MAX_CELLS`` iterations with the handle
    still open. Closure is explicit, not left to garbage collection, and it
    holds on refusal too because the members are read inside the block.

    Structural admission
    --------------------
    ``admit_snapshot`` now runs first and raises ``SnapshotArchiveRejected``
    before ``np.load``, its decompressor or its allocator is reached, for an
    archive that is out of the data directory, not a ZIP, wrong in its
    membership, hostile in its member names, oversized in its declared or
    physical size, or wrong in any member's NPY header.

    Structural refusals all precede loading. A narrow set of payload-TRANSPORT
    failures cannot: a payload is only checkable by decompressing it, so a
    valid header over a corrupt body surfaces during array materialisation and
    is translated there instead. Exactly four things are translated --
    BadZipFile, zlib.error, EOFError, and NumPy's array-data EOF identified by
    its own traceback frame. The watcher and the
    initial-client send below each catch that type, log one bounded reason
    code and send no frame; the server, the watcher and every client stay
    alive.

    Ownership is no longer conditional. It used to be, because ``np.load``
    returns an ``NpzFile`` for a zip and a plain ndarray for a ``.npy``, and
    only the first owns a handle. Admission refuses non-ZIP input outright, so
    this call site now only ever sees an ``NpzFile``.

    That is a DELIBERATE behaviour change, recorded rather than glossed: a
    numeric ``.npy`` renamed to ``.npz`` used to fail with the incidental
    ``IndexError`` of a string subscript on an ndarray, and now receives a
    typed admission refusal instead.

    The guard opens the file once and hands this function the very descriptor
    it preflighted, so the bytes inspected are the bytes NumPy reads -- which closes the pathname
    reopen and re-resolution races, though not in-place mutation of the file
    while the descriptor is open. The
    inner ``with`` closes the archive; the guard closes the descriptor; both
    hold on success and on every exceptional exit.

    ``allow_pickle=False`` stays at this call site even though an object-dtype
    member can no longer survive admission. It is the second line of defence
    and the property the repository-wide static gate reads.
    """
    with admit_snapshot(snap_path, data_dir=DATA_DIR,
                        policy=SNAPSHOT_POLICY) as descriptor:
        with np.load(descriptor, allow_pickle=False) as snap:
            state = snap['lattice']
            mg = snap['memory_grid']
            gen = int(snap['generation'])

    n = state.shape[0]

    # Find non-void cells
    non_void = np.argwhere(state > 0)

    # Limit to MAX_CELLS (sample if too many)
    if len(non_void) > MAX_CELLS:
        indices = np.random.choice(len(non_void), MAX_CELLS, replace=False)
        non_void = non_void[indices]

    cells = []
    for z, y, x in non_void:
        s = int(state[z, y, x])
        age = float(mg[0, z, y, x])  # compute_age
        energy = float(mg[3, z, y, x])  # energy_reserve
        warmth = float(mg[6, z, y, x])  # warmth
        memory = float(mg[2, z, y, x])  # memory_strength

        cells.append({
            'x': int(x), 'y': int(y), 'z': int(z),
            's': s,  # state
            'a': round(age, 1),  # age
            'e': round(energy, 2),  # energy
            'w': round(warmth, 3),  # warmth
            'm': round(memory, 2),  # memory
        })

    # Compute metrics
    compute_mask = state == 2
    ages = mg[0][compute_mask]

    metrics = {
        'generation': gen,
        'total_cells': int((state > 0).sum()),
        'compute': int(compute_mask.sum()),
        'structural': int((state == 1).sum()),
        'energy': int((state == 3).sum()),
        'sensor': int((state == 4).sum()),
        'max_age': float(ages.max()) if len(ages) > 0 else 0,
        'median_age': float(np.median(ages)) if len(ages) > 0 else 0,
        'sages': int((ages >= 8).sum()) if len(ages) > 0 else 0,
        'grid_size': n,
    }

    return {'cells': cells, 'metrics': metrics}


async def broadcast(message):
    """Send message to all connected clients."""
    if connected_clients:
        await asyncio.gather(
            *[client.send(message) for client in connected_clients],
            return_exceptions=True
        )


def _note_metadata_failure(lane=DISCOVERY_LANE):
    """Count a failure in one lane and warn once if that lane is persisting.

    A LONE failure is an ordinary rotation and is not worth a line, so the
    first one in a lane is silent. A repeat means the watcher is running blind
    in that lane, which silence would hide — so one FIXED message is emitted,
    then rate-limited on a monotonic clock. The message carries no path, no
    filename and no exception text: the entry that failed is attacker-named,
    and this is the one place a name could otherwise reach the log by accident.
    """
    state = _metadata_state[lane]
    state["failures"] += 1

    if state["failures"] < 2:
        return  # a single transient failure stays silent

    now = time.monotonic()
    warned_at = state["warned_at"]
    if warned_at is not None and now - warned_at < METADATA_WARNING_INTERVAL:
        return
    state["warned_at"] = now
    print("  Snapshot metadata unreadable; watcher is not seeing new snapshots")


def _clear_metadata_failures(lane=DISCOVERY_LANE):
    """A successful read ends the episode in THAT lane, and only that lane."""
    _metadata_state[lane] = {"failures": 0, "warned_at": None}


async def snapshot_watcher():
    """Watch for new snapshots and broadcast to clients."""
    global last_snapshot_path, last_snapshot_mtime

    while True:
        try:
            # The watcher is the SOLE directory-discovery owner: this is
            # the only call in the module that may start a scan.
            latest = find_latest_snapshot(DATA_DIR, allow_refresh=True)
            if latest:
                # The SECOND metadata read, and it needs the same protection as
                # the first: selection and this line are separate syscalls, so
                # the chosen snapshot can be rotated away in between. Non-
                # following, and a vanished entry ends this poll quietly rather
                # than printing an OSError whose message carries the path.
                try:
                    mtime = entry_fingerprint(latest)[2]
                except OSError:
                    mtime = None
                    _note_metadata_failure(FINGERPRINT_LANE)
                else:
                    _clear_metadata_failures(FINGERPRINT_LANE)

                if mtime is not None and (
                    latest != last_snapshot_path or mtime != last_snapshot_mtime
                ):
                    last_snapshot_path = latest
                    last_snapshot_mtime = mtime

                    # Extract and broadcast. A refused archive logs one bounded
                    # reason code and sends nothing; `last_snapshot_path` and
                    # `last_snapshot_mtime` were already advanced above, so the
                    # same rejected file is not reprocessed on every poll, and
                    # a later valid snapshot is picked up normally.
                    try:
                        data = extract_render_data(latest)
                    except SnapshotArchiveRejected as refusal:
                        print(f"  Snapshot rejected: {refusal.reason}")
                    else:
                        msg = json.dumps({'type': 'frame', 'data': data})
                        await broadcast(msg)

                        gen = data['metrics']['generation']
                        n_clients = len(connected_clients)
                        if n_clients > 0:
                            print(f"  Broadcast gen {gen:,} to {n_clients} client(s) ({len(data['cells'])} cells)")
        except Exception as e:
            print(f"  Snapshot error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


async def handle_client(websocket):
    """Handle a connected browser client."""
    connected_clients.add(websocket)
    remote = websocket.remote_address
    print(f"Client connected: {remote}")

    # Send initial snapshot immediately. A refused archive costs this client
    # its opening frame and nothing else: one bounded reason code is logged,
    # the connection stays open and its messages are handled as usual.
    try:
        # No refresh: a connect burst must cost zero directory work. This
        # client either gets the watcher's completed listing or no frame.
        latest = find_latest_snapshot(DATA_DIR)
        if latest:
            data = extract_render_data(latest)
            await websocket.send(json.dumps({'type': 'frame', 'data': data}))
    except SnapshotArchiveRejected as refusal:
        print(f"  Snapshot rejected: {refusal.reason}")
    except Exception as e:
        print(f"  Initial send error: {e}")

    try:
        async for message in websocket:
            try:
                event = json.loads(message)
                # Valid JSON is not necessarily a JSON *object*. `null`, booleans,
                # numbers, strings and arrays all decode successfully but have no
                # .get(), so reaching for one raised AttributeError, escaped the
                # JSONDecodeError guard below, and terminated this client's handler
                # -- disconnecting the browser instead of ignoring one bad frame.
                # Accept only an exact built-in dict; every other decoded shape is
                # ignored silently (no reply, no event action, and nothing about the
                # supplied value or its type is logged) and the loop keeps reading
                # later messages from the same client, exactly like malformed JSON.
                if type(event) is not dict:
                    continue
                event_type = event.get('type', '')

                if event_type == 'click':
                    x, y, z = event.get('x', 0), event.get('y', 0), event.get('z', 0)
                    print(f"  Click at ({x},{y},{z})")
                    # Future: modify lattice state at click point

                elif event_type == 'polish':
                    print(f"  Polish event: {event}")
                    # Future: magnetic abrasive polishing

                elif event_type == 'inject':
                    cell_type = event.get('cell_type', 2)
                    print(f"  Inject {cell_type} at ({event.get('x')},{event.get('y')},{event.get('z')})")

                elif event_type == 'ping':
                    await websocket.send(json.dumps({'type': 'pong', 'time': time.time()}))

            except json.JSONDecodeError:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)
        print(f"Client disconnected: {remote}")


async def main():
    print("=" * 55)
    print("  LUCID DREAMING SERVER -- Phase 12B")
    print(f"  WebSocket: ws://localhost:{WS_PORT}")
    print(f"  Data dir: {DATA_DIR}")
    print(f"  Poll interval: {POLL_INTERVAL}s")
    print("=" * 55)
    print()
    print("  Open medusa_lucid.html in your browser to connect!")
    print()

    # Start snapshot watcher
    asyncio.create_task(snapshot_watcher())

    # Start WebSocket server
    async with websockets.serve(handle_client, "localhost", WS_PORT):
        print(f"  Server listening on ws://localhost:{WS_PORT}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Lucid Dreaming WebSocket Server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    WS_PORT = args.port
    DATA_DIR = args.data_dir

    asyncio.run(main())
