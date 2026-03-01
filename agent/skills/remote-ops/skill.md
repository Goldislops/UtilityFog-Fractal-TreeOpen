# Remote Operations Skill

## Purpose
Enables the agent to push status updates, alerts, and results to the user's mobile device or remote dashboard.

## Capabilities

### 1. Push Notifications
Send real-time alerts to mobile devices via:
- **Pushover**: High-priority alerts (task failures, thermal warnings)
- **Telegram Bot**: Status updates, task completions
- **Discord Webhook**: Detailed logs, cluster status

### 2. Status Dashboard
Update a remote web dashboard with:
- Cluster health metrics
- Active task queue
- GPU utilization graphs
- Historical performance data

### 3. Remote Commands
Receive commands from mobile:
- Trigger grokking run
- Pause/resume tasks
- Query task status
- Emergency shutdown

## Configuration

### Pushover Setup
```bash
export PUSHOVER_USER_KEY="your_user_key"
export PUSHOVER_APP_TOKEN="your_app_token"
```

### Telegram Bot Setup
```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

### Discord Webhook Setup
```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

## Usage Examples

### Send Task Completion Alert
```python
import requests
import os

def notify_task_complete(task_id, node_id, elapsed_secs):
    requests.post('https://api.pushover.net/1/messages.json', data={
        'token': os.getenv('PUSHOVER_APP_TOKEN'),
        'user': os.getenv('PUSHOVER_USER_KEY'),
        'message': f'Task {task_id} completed on {node_id} in {elapsed_secs}s',
        'priority': 0,
        'title': 'UtilityFog Task Complete'
    })

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    text = f"Task `{task_id}` completed\nNode: {node_id}\nTime: {elapsed_secs}s"
    requests.post(f'https://api.telegram.org/bot{bot_token}/sendMessage', json={
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    })
```

### Send Thermal Warning
```python
def notify_thermal_warning(node_id, gpu_id, temp_c):
    requests.post('https://api.pushover.net/1/messages.json', data={
        'token': os.getenv('PUSHOVER_APP_TOKEN'),
        'user': os.getenv('PUSHOVER_USER_KEY'),
        'message': f'GPU {gpu_id} on {node_id} at {temp_c}C!',
        'priority': 2,
        'retry': 30,
        'expire': 3600,
        'title': 'GPU Thermal Warning'
    })
```

### Update Dashboard
```python
import json
from datetime import datetime

def update_dashboard(cluster_summary):
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    embed = {
        'title': 'Vanguard Cluster Status',
        'color': 0x00ff00 if cluster_summary['avg_utilization'] < 80 else 0xff0000,
        'fields': [
            {'name': 'Nodes', 'value': str(cluster_summary['node_count']), 'inline': True},
            {'name': 'RTX 5090', 'value': str(cluster_summary['rtx5090_count']), 'inline': True},
            {'name': 'RTX 4090', 'value': str(cluster_summary['rtx4090_count']), 'inline': True},
            {'name': 'Avg Utilization', 'value': f"{cluster_summary['avg_utilization']:.1f}%", 'inline': True},
            {'name': 'Total VRAM', 'value': f"{cluster_summary['total_vram_mb'] / 1024:.1f} GB", 'inline': True},
            {'name': 'Grokking', 'value': 'ACTIVE' if cluster_summary['grokking_active'] else 'OFF', 'inline': True},
        ],
        'timestamp': datetime.utcnow().isoformat()
    }
    requests.post(webhook_url, json={'embeds': [embed]})
```

### Receive Remote Commands (Telegram Bot)
```python
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

def cmd_grokking(update: Update, context: CallbackContext):
    duration = int(context.args[0]) if context.args else 300
    result = mcp_client.call_tool('trigger_grokking_run', {
        'duration_secs': duration,
        'confirm': True
    })
    update.message.reply_text(f"Grokking run activated for {duration}s")

def cmd_status(update: Update, context: CallbackContext):
    summary = get_cluster_summary()
    text = f"""**Cluster Status**
Nodes: {summary['node_count']}
GPUs: {summary['rtx5090_count']}x5090 + {summary['rtx4090_count']}x4090
Avg Util: {summary['avg_utilization']:.1f}%
Grokking: {'ACTIVE' if summary['grokking_active'] else 'OFF'}
"""
    update.message.reply_text(text, parse_mode='Markdown')

updater = Updater(os.getenv('TELEGRAM_BOT_TOKEN'))
updater.dispatcher.add_handler(CommandHandler('grokking', cmd_grokking))
updater.dispatcher.add_handler(CommandHandler('status', cmd_status))
updater.start_polling()
```

## Alert Priorities

### Pushover Priority Levels
- **-2**: Silent (no notification)
- **-1**: Quiet (no sound/vibration)
- **0**: Normal (default)
- **1**: High (bypass quiet hours)
- **2**: Emergency (requires acknowledgment)

### Alert Types
| Event | Channel | Priority |
|-------|---------|----------|
| Task completed | Telegram | Normal |
| Task failed | Pushover | High |
| GPU temp > 85C | Pushover | Emergency |
| Grokking run started | Telegram | Normal |
| Grokking run ended | Telegram | Normal |
| Node offline | Pushover | High |
| Watchdog violation | Discord | Normal |
| Cluster summary (hourly) | Discord | Silent |

## Security

### API Keys
- Store in environment variables (never commit to git)
- Use `.env` file for local development
- Production: use secrets manager (e.g., HashiCorp Vault)

### Rate Limiting
- Pushover: 10,000 messages/month (free tier)
- Telegram: No hard limit, but avoid spam
- Discord: 30 requests/minute per webhook

### Authentication
- Telegram bot: verify `chat_id` matches authorized user
- Discord webhook: use secret URL (don't share publicly)
- Pushover: user key + app token required
