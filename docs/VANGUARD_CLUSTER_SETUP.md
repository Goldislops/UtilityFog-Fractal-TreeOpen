# Vanguard Cluster Setup Guide

Complete setup instructions for the Vanguard SOC GPU cluster (3x RTX 5090 + 2x RTX 4090).

## Hardware Configuration

### Primary Node: Intel 285K
- **CPU**: Intel Core Ultra 9 285K (24 cores, 32 threads)
- **RAM**: 64GB DDR5-6400
- **GPUs**: 3x NVIDIA RTX 5090 (32GB VRAM each)
- **Storage**: 2TB NVMe SSD
- **Network**: 10GbE
- **OS**: Ubuntu 22.04 LTS
- **IP**: 192.168.1.100

### Secondary Node: AMD 9950X3D
- **CPU**: AMD Ryzen 9 9950X3D (16 cores, 32 threads)
- **RAM**: 64GB DDR5-6000
- **GPUs**: 2x NVIDIA RTX 4090 (24GB VRAM each)
- **Storage**: 1TB NVMe SSD
- **Network**: 10GbE
- **OS**: Ubuntu 22.04 LTS
- **IP**: 192.168.1.101

## Software Prerequisites

### Both Nodes
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install nvidia-driver-550 nvidia-utils-550
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
sudo apt install python3.11 python3.11-venv python3-pip
sudo apt install protobuf-compiler
sudo apt install boinc-client boinc-manager
```

## Network Configuration

### Firewall Rules
```bash
sudo ufw allow 50051:50052/tcp
sudo ufw allow 22/tcp
sudo ufw enable
```

## Building Vanguard MCP

```bash
git clone https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen.git
cd UtilityFog-Fractal-TreeOpen/crates/vanguard-mcp
cargo build --release
```

## Systemd Services

### MCP Server (Primary Node)
Create `/etc/systemd/system/vanguard-mcp.service`:
```ini
[Unit]
Description=Vanguard MCP Cluster Server
After=network.target

[Service]
Type=simple
User=utilityfog
WorkingDirectory=/opt/utilityfog
Environment="RUST_LOG=info"
Environment="VANGUARD_GRPC_PORT=50051"
ExecStart=/opt/utilityfog/target/release/vanguard-mcp
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Node Agent (Both Nodes)
Create `/etc/systemd/system/vanguard-node.service`:
```ini
[Unit]
Description=Vanguard Node Agent
After=network.target vanguard-mcp.service

[Service]
Type=simple
User=utilityfog
WorkingDirectory=/opt/utilityfog
Environment="RUST_LOG=info"
Environment="VANGUARD_SERVER=192.168.1.100:50051"
ExecStart=/opt/utilityfog/scripts/node-agent.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Watchdog (Both Nodes)
Create `/etc/systemd/system/vanguard-watchdog.service`:
```ini
[Unit]
Description=Vanguard Resource Watchdog
After=network.target boinc-client.service

[Service]
Type=simple
User=root
Environment="RUST_LOG=info"
Environment="BOINC_RESERVE_PCT=15.0"
Environment="FOLDING_RESERVE_PCT=10.0"
ExecStart=/opt/utilityfog/scripts/watchdog.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Enable Services
```bash
sudo systemctl daemon-reload
sudo systemctl enable vanguard-mcp vanguard-node vanguard-watchdog
sudo systemctl start vanguard-mcp vanguard-node vanguard-watchdog
```

## BOINC Configuration

Edit `/etc/boinc-client/cc_config.xml`:
```xml
<cc_config>
  <options>
    <max_ncpus_pct>50</max_ncpus_pct>
  </options>
  <coproc>
    <type>NVIDIA</type>
    <usage_limit>15</usage_limit>
  </coproc>
</cc_config>
```

## Verification

```bash
sudo systemctl status vanguard-mcp
sudo systemctl status vanguard-node
sudo systemctl status vanguard-watchdog
grpcurl -plaintext localhost:50051 list
watch -n 1 nvidia-smi
```

## Monitoring

```bash
journalctl -u vanguard-mcp -f
journalctl -u vanguard-node -f
journalctl -u vanguard-watchdog -f
```

## Troubleshooting

### GPU Not Detected
```bash
nvidia-smi
sudo apt purge nvidia-*
sudo apt install nvidia-driver-550
sudo reboot
```

### gRPC Connection Refused
```bash
sudo systemctl status vanguard-mcp
sudo ufw status
grpcurl -plaintext localhost:50051 list
```

### High GPU Temperature
```bash
nvidia-smi -q -d TEMPERATURE
sudo nvidia-settings -a "[gpu:0]/GPUFanControlState=1" -a "[fan:0]/GPUTargetFanSpeed=80"
```
