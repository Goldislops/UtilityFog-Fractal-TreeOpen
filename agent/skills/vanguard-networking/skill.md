# Vanguard Networking Skill

## Purpose
Provides the agent with knowledge of the GPU cluster topology and networking configuration for the Vanguard SOC cluster — a live 4-node (expanding to 6) GPU mesh on the 192.168.86.x subnet.

## Cluster Topology (Live)

### Head Node: Mega (RTX 5090)
- **Hostname**: `Mega`
- **IP Address**: `192.168.86.29`
- **gRPC Port**: `50051`
- **GPU**: RTX 5090 (32GB VRAM)
- **Role**: Head node, MCP server host, orchestrator
- **Services**: Vanguard MCP, BOINC, Folding@home

### Compute Node 1: AMDMSIX870E-1 (RTX 5090)
- **Hostname**: `AMDMSIX870E-1`
- **IP Address**: `192.168.86.16`
- **gRPC Port**: `50052`
- **GPU**: RTX 5090 (32GB VRAM)
- **Role**: Compute node
- **Services**: Vanguard Node Agent, BOINC, Folding@home

### Compute Node 2: AMDMSIX870E-2 (RTX 5090)
- **Hostname**: `AMDMSIX870E-2`
- **IP Address**: `192.168.86.22`
- **gRPC Port**: `50053`
- **GPU**: RTX 5090 (32GB VRAM)
- **Role**: Compute node
- **Services**: Vanguard Node Agent, BOINC, Folding@home

### Compute Node 3: DellUltracore9 (RTX 4090)
- **Hostname**: `DellUltracore9`
- **IP Address**: `192.168.86.3`
- **gRPC Port**: `50054`
- **CPU**: Dell Ultra Core 9 285
- **GPU**: RTX 4090 (24GB VRAM)
- **Role**: Compute node
- **Services**: Vanguard Node Agent, BOINC, Folding@home

### Placeholder Node 5: Ian's Aurora (RTX 4090) — PENDING
- **Hostname**: `aurora-ian`
- **IP Address**: TBD
- **gRPC Port**: `50055`
- **CPU**: Intel i9-14900KF
- **GPU**: RTX 4090 (24GB VRAM)
- **Role**: Future compute node
- **Status**: Awaiting network integration

### Placeholder Node 6: (RTX 4080 Super) — PENDING
- **Hostname**: TBD
- **IP Address**: TBD
- **gRPC Port**: `50056`
- **CPU**: Intel i9-14900K
- **GPU**: RTX 4080 Super (16GB VRAM)
- **Role**: Future compute node
- **Status**: Awaiting network integration

## Network Configuration

### Subnet
- **Network**: `192.168.86.0/24`
- **Gateway**: `192.168.86.1`

### Cluster Service Endpoints
- **MCP Server (Head)**: `grpc://192.168.86.29:50051`
- **Compute 1**: `grpc://192.168.86.16:50052`
- **Compute 2**: `grpc://192.168.86.22:50053`
- **Compute 3**: `grpc://192.168.86.3:50054`
- **Heartbeat Interval**: 10 seconds
- **Task Timeout**: 300 seconds (default)

### GPU Affinity Preferences
- **Ising Parallel Tempering (high-replica)**: Distribute replicas across all 4 nodes
- **Fractal Generation (Sierpinski, Menger)**: Prefer RTX 5090 nodes (Mega, AMDMSIX870E-1/2)
- **Parallel Stepping (>100K nodes)**: Prefer RTX 5090 (higher compute)
- **Visualization Rendering**: Any GPU
- **Small Simulations (<10K nodes)**: Prefer RTX 4090 (DellUltracore9)

### Resource Reservations (Normal Mode)
- **BOINC**: 15% GPU per card
- **Folding@home**: 10% GPU per card
- **UtilityFog**: 75% GPU per card

### Resource Reservations (Grokking Run)
- **BOINC**: 0% (gracefully paused)
- **Folding@home**: 0% (gracefully paused)
- **UtilityFog**: 100% GPU per card
- All 4 nodes dedicated to the grokking computation
- BOINC/F@H auto-restored when grokking ends

## Grokking Run Protocol

1. Watchdog broadcasts `GrokkingRun` mode to all 4 nodes
2. Each node pauses BOINC (`boinccmd --set_gpu_mode never`) and F@H (`FAHClient --pause`)
3. GPU router lifts the 25% reserve ceiling — full 100% capacity available
4. Parallel Tempering replicas distributed across all available GPUs
5. Timer counts down; on expiry, watchdog restores Normal mode
6. BOINC and F@H resume automatically

## Usage Examples

### Submit a Fractal Task
```python
import grpc
from cluster_pb2 import TaskRequest, GpuPreference
from cluster_pb2_grpc import ClusterServiceStub

channel = grpc.insecure_channel('192.168.86.29:50051')
stub = ClusterServiceStub(channel)

request = TaskRequest(
    task_type='fractal_step',
    payload=b'...',
    gpu_preference=GpuPreference.GPU_PREFER_5090,
    priority=5,
    branch_id='sierpinski-d4-b0'
)
receipt = stub.SubmitTask(request)
print(f"Task {receipt.task_id} assigned to {receipt.assigned_node}/{receipt.assigned_gpu}")
```

### Query Cluster Status
```python
from cluster_pb2 import Empty

node_list = stub.ListNodes(Empty())
for node in node_list.nodes:
    print(f"{node.hostname}: {len(node.gpus)} GPUs, {node.total_vram_mb}MB VRAM")
```

### Trigger Grokking Run
```python
result = mcp_client.call_tool('trigger_grokking_run', {
    'duration_secs': 600,
    'confirm': True
})
```

## Monitoring

### Health Checks
- Heartbeat every 10s from each node
- GPU temperature threshold: 85C (tasks rejected above this)
- GPU utilization tracked per-card
- VRAM availability monitored

### Failure Handling
- Node offline: tasks re-queued to other nodes
- GPU overheating: tasks paused until temp < 80C
- Task timeout: automatic retry (max 3 attempts)

## Security
- gRPC uses insecure channel (local 192.168.86.0/24 only)
- Firewall: ports 50051-50056 open only to subnet
- No external access

## Task Priority Levels
- **0-3**: Low (background tasks)
- **4-6**: Normal (default)
- **7-9**: High (interactive)
- **10**: Critical (grokking run)

## Routing Strategies
- `LeastLoaded`: Pick GPU with lowest utilization (default)
- `RoundRobin`: Cycle through all available GPUs
- `VramCapacity`: Pick GPU with most free VRAM
- `AffinityFirst`: Respect GPU model preference strictly

## Troubleshooting

### Common Issues
1. **"Queue full"**: Increase `max_capacity` in TaskQueue or wait for tasks to complete
2. **"No available GPUs"**: Check if all GPUs are above 85C or fully utilized
3. **"Node not responding"**: Verify network connectivity on 192.168.86.x, check if node process is running
4. **"BOINC/F@H starved"**: Watchdog logs violations; reduce UFT task load or trigger grokking run

### Logs
- MCP Server: `journalctl -u vanguard-mcp -f`
- Node Agent: `journalctl -u vanguard-node -f`
- Watchdog: `journalctl -u vanguard-watchdog -f`
