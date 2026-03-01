# Vanguard Networking Skill

## Purpose
Provides the agent with knowledge of the GPU cluster topology and networking configuration for the Vanguard SOC cluster.

## Cluster Topology

### Primary Node: Intel 285K (Vanguard Primary)
- **Hostname**: `vanguard-primary`
- **IP Address**: `192.168.1.100`
- **gRPC Port**: `50051`
- **CPU**: Intel Core Ultra 9 285K
- **GPUs**:
  - GPU-0: RTX 5090 (32GB VRAM)
  - GPU-1: RTX 5090 (32GB VRAM)
  - GPU-2: RTX 5090 (32GB VRAM)
- **Role**: Primary compute node, MCP server host

### Secondary Node: AMD 9950X3D (Compute Secondary)
- **Hostname**: `compute-secondary`
- **IP Address**: `192.168.1.101`
- **gRPC Port**: `50052`
- **CPU**: AMD Ryzen 9 9950X3D
- **GPUs**:
  - GPU-0: RTX 4090 (24GB VRAM)
  - GPU-1: RTX 4090 (24GB VRAM)
- **Role**: Secondary compute node

## Network Configuration

### Cluster Service Endpoints
- **MCP Server**: `http://192.168.1.100:50051`
- **gRPC Cluster Service**: `grpc://192.168.1.100:50051`
- **Heartbeat Interval**: 10 seconds
- **Task Timeout**: 300 seconds (default)

### GPU Affinity Preferences
- **Fractal Generation (Sierpinski, Menger)**: Prefer RTX 5090 (higher VRAM)
- **Parallel Stepping (>100K nodes)**: Prefer RTX 5090 (higher compute)
- **Visualization Rendering**: Any GPU
- **Small Simulations (<10K nodes)**: Prefer RTX 4090 (lower power)

### Resource Reservations
- **BOINC**: 15% GPU per card (normal mode)
- **Folding@home**: 10% GPU per card (normal mode)
- **UtilityFog**: 75% GPU per card (normal mode)
- **Grokking Run**: 100% GPU (BOINC/F@H paused)

## Usage Examples

### Submit a Fractal Task
```python
import grpc
from cluster_pb2 import TaskRequest, GpuPreference
from cluster_pb2_grpc import ClusterServiceStub

channel = grpc.insecure_channel('192.168.1.100:50051')
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
    for gpu in node.gpus:
        print(f"  {gpu.gpu_id}: {gpu.model} @ {gpu.utilization:.1f}% util, {gpu.temperature_c:.1f}C")
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
- gRPC uses insecure channel (local network only)
- No authentication required (trusted cluster)
- Firewall: ports 50051-50052 open only to 192.168.1.0/24

## Performance Tuning

### Task Priority Levels
- **0-3**: Low (background tasks)
- **4-6**: Normal (default)
- **7-9**: High (interactive)
- **10**: Critical (grokking run)

### Routing Strategies
- `LeastLoaded`: Pick GPU with lowest utilization (default)
- `RoundRobin`: Cycle through all available GPUs
- `VramCapacity`: Pick GPU with most free VRAM
- `AffinityFirst`: Respect GPU model preference strictly

## Troubleshooting

### Common Issues
1. **"Queue full" error**: Increase `max_capacity` in TaskQueue or wait for tasks to complete
2. **"No available GPUs"**: Check if all GPUs are above 85C or fully utilized
3. **"Node not responding"**: Verify network connectivity, check if node process is running
4. **"BOINC/F@H starved"**: Watchdog will log violations; reduce UFT task load or trigger grokking run

### Logs
- MCP Server: `journalctl -u vanguard-mcp -f`
- Node Agent: `journalctl -u vanguard-node -f`
- Watchdog: `journalctl -u vanguard-watchdog -f`
