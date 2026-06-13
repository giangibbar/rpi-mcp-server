# 🔧 RPi4 MCP Server

A Model Context Protocol (MCP) server for Raspberry Pi 4, exposing 22 hardware and system tools via HTTP/SSE.

## Tools

| Tool | Description |
|------|-------------|
| system_info | CPU temp, load, memory, disk, uptime |
| network_info | IPs, interfaces, connections, gateway latency |
| process_top | Top N processes by CPU/RAM |
| service_control | Manage systemd services |
| deploy_app | Git pull + pip install + restart |
| backup_db | SQLite backup with timestamp |
| nginx_reload | Test and reload nginx |
| cron_list | List crontab entries |
| cron_add | Add crontab entry |
| run_command | Execute shell command |
| gpio_write | Set GPIO pin HIGH/LOW |
| gpio_read | Read GPIO pin value |
| pwm_control | PWM duty cycle control |
| i2c_scan | Scan I2C bus |
| sensor_read | Read sensors (cpu_temp, dht22, bme280) |
| camera_capture | Capture photo with Pi Camera |
| read_logs | Read journald logs |
| ollama_status | Ollama running models and memory |
| ollama_generate | Generate text with Ollama |
| wake_on_lan | Send WoL magic packet |
| docker_status | Docker containers status |
| file_serve | Temporarily serve a file via HTTP |
| speedtest | Internet speed test (download, upload, ping) |
| backup_all | Backup all SQLite databases to ~/backups/ |
| git_status | Git status for all projects in ~/WORKSPACE |
| format_sd | Format SD/USB drive (auto-detects removable media) |
| mcp_call_log | Show recent tool call history |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python server.py
```

Listens on `0.0.0.0:8002/mcp/` (MCP over HTTP+SSE).

## systemd

```ini
[Unit]
Description=RPi4 MCP Server
After=network.target

[Service]
Type=simple
User=egamgia
WorkingDirectory=/home/egamgia/mcp-server
ExecStart=/home/egamgia/mcp-server/.venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Integration

Used by [Kiro CLI](https://github.com/aws/kiro) as MCP tool server for the `rpi-dev` agent.
Also integrated in [RPi Panel](https://github.com/giangibbar/rpi-panel) web UI under the MCP section.
