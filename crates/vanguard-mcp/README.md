# Vanguard MCP Server

Rust-based Model Context Protocol (MCP) server for orchestrating GPU cluster operations across the Vanguard SOC cluster (3x RTX 5090 + 2x RTX 4090).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Vanguard MCP Server                     │
│                    (Intel 285K Primary)                     │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ MCP Handler  │  │ Task Queue   │  │  GPU Router     │  │
│  │ (JSON-RPC)   │  │ (Priority)   │  │  (Affinity)     │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬────────┘  │
│         │                  │                    │           │
│         └──────────────────┴────────────────────┘           │
│                            │                                │
│                   ┌────────▼────────┐                       │
│                   │  gRPC Service   │                       │
│                   │  (port 50051)   │                       │
│                   └────────┬────────┘                       │
└────────────────────────────┼────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
    ┌─────────▼─────────┐       ┌──────────▼──────────┐
    │  Intel 285K Node  │       │  AMD 9950X3D Node   │
    │  192.168.1.100    │       │  192.168.1.101      │
    │                   │       │                     │
    │  GPU-0: RTX 5090  │       │  GPU-0: RTX 4090    │
    │  GPU-1: RTX 5090  │       │  GPU-1: RTX 4090    │
    │  GPU-2: RTX 5090  │       │                     │
    └───────────────────┘       └─────────────────────┘
```

## Features

### 1. Distributed Task Queue
- Priority-based task scheduling
- GPU affinity preferences (5090-only, 4090-only, prefer-5090, prefer-4090, any)
- Automatic load balancing
- Task timeout and retry logic

### 2. GPU Router
- Real-time GPU utilization tracking
- Temperature-based throttling (>85C)
- VRAM capacity filtering
- Multiple routing strategies: LeastLoaded, RoundRobin, VramCapacity, AffinityFirst

### 3. Watchdog
- BOINC/Folding@home resource reservation (15% + 10% GPU)
- Grokking Run mode (100% GPU, pauses distributed computing)
- Automatic compliance monitoring
- Violation logging

### 4. MCP Tools
- `submit_fractal_task`: Queue fractal branch physics calculations
- `cluster_status`: Get real-time cluster health
- `task_status`: Query task progress
- `set_gpu_affinity`: Configure GPU preferences per task type
- `watchdog_status`: Check BOINC/F@H resource guard
- `trigger_grokking_run`: Activate exclusive GPU mode

## Building

```bash
cd crates/vanguard-mcp
cargo build --release
```

## Running

```bash
cargo run --release
```

Server listens on `0.0.0.0:50051` (gRPC) and handles MCP JSON-RPC requests via stdin/stdout.

## Testing

```bash
cargo test
```

Tests cover:
- Task queue priority ordering
- GPU routing strategies
- Watchdog mode transitions
- Resource compliance checks

## Configuration

### Environment Variables
- `VANGUARD_GRPC_PORT`: gRPC server port (default: 50051)
- `VANGUARD_MAX_QUEUE_SIZE`: Max queued tasks (default: 10000)
- `VANGUARD_BOINC_RESERVE_PCT`: BOINC GPU reservation (default: 15.0)
- `VANGUARD_FOLDING_RESERVE_PCT`: Folding@home GPU reservation (default: 10.0)

### Logging
```bash
RUST_LOG=info cargo run
```

## Integration

### Python Client Example
```python
import grpc
from cluster_pb2 import TaskRequest, GpuPreference
from cluster_pb2_grpc import ClusterServiceStub

channel = grpc.insecure_channel('192.168.1.100:50051')
stub = ClusterServiceStub(channel)

receipt = stub.SubmitTask(TaskRequest(
    task_type='fractal_step',
    payload=b'sierpinski_d4_step_100',
    gpu_preference=GpuPreference.GPU_PREFER_5090,
    priority=7,
    branch_id='sierpinski-d4-b0'
))
print(f"Task {receipt.task_id} queued on {receipt.assigned_node}/{receipt.assigned_gpu}")
```

## License

MIT OR Apache-2.0
