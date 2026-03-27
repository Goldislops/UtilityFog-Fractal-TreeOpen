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
import glob
import time
import os
import sys
import numpy as np

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


def find_latest_snapshot(data_dir):
    """Find the most recent .npz snapshot."""
    pattern = os.path.join(data_dir, "v070_gen*.npz")
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def extract_render_data(snap_path):
    """Extract cell positions, states, and ages from a snapshot."""
    snap = np.load(snap_path, allow_pickle=True)
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


async def snapshot_watcher():
    """Watch for new snapshots and broadcast to clients."""
    global last_snapshot_path, last_snapshot_mtime

    while True:
        try:
            latest = find_latest_snapshot(DATA_DIR)
            if latest:
                mtime = os.path.getmtime(latest)
                if latest != last_snapshot_path or mtime != last_snapshot_mtime:
                    last_snapshot_path = latest
                    last_snapshot_mtime = mtime

                    # Extract and broadcast
                    data = extract_render_data(latest)
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

    # Send initial snapshot immediately
    try:
        latest = find_latest_snapshot(DATA_DIR)
        if latest:
            data = extract_render_data(latest)
            await websocket.send(json.dumps({'type': 'frame', 'data': data}))
    except Exception as e:
        print(f"  Initial send error: {e}")

    try:
        async for message in websocket:
            try:
                event = json.loads(message)
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
