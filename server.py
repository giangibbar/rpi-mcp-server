"""RPi4 MCP Server — hardware monitoring, DevOps, GPIO, IoT, and automation tools."""

import json
import subprocess
import os
import time
from pathlib import Path
from collections import deque

import psutil
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rpi4-tools", host="0.0.0.0", port=8002, stateless_http=True)

HOME = Path("/home/egamgia")
BACKUPS = HOME / "backups"

# --- Call Log ---
_call_log = deque(maxlen=100)
LOG_FILE = HOME / "mcp-server" / "calls.json"


def _log_call(tool: str, args: dict, result: str, elapsed: float):
    entry = {"tool": tool, "args": args, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed": round(elapsed, 2), "ok": True, "result_len": len(result)}
    _call_log.appendleft(entry)
    try:
        LOG_FILE.write_text(json.dumps(list(_call_log), indent=None))
    except Exception:
        pass


@mcp.tool()
def mcp_call_log(limit: int = 20) -> str:
    """Show recent MCP tool call history."""
    if LOG_FILE.exists():
        entries = json.loads(LOG_FILE.read_text())[:limit]
    else:
        entries = list(_call_log)[:limit]
    lines = []
    for e in entries:
        lines.append(f"{e['time']} | {e['tool']:20s} | {e['elapsed']}s | {e.get('result_len',0)}b")
    return "\n".join(lines) or "No calls logged yet"


# --- System Monitoring ---


@mcp.tool()
def system_info() -> str:
    """Get RPi4 system info: CPU temp, load, memory, disk, uptime."""
    try:
        temp_raw = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip())
        temp = f"temp={temp_raw / 1000:.1f}'C"
    except Exception:
        temp = "N/A"
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = psutil.getloadavg()
    uptime = subprocess.run(
        ["uptime", "-p"], capture_output=True, text=True
    ).stdout.strip()
    return (
        f"temp: {temp}\n"
        f"load: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}\n"
        f"memory: {mem.used // 1048576}MB / {mem.total // 1048576}MB ({mem.percent}%)\n"
        f"disk: {disk.used // 1073741824}GB / {disk.total // 1073741824}GB ({disk.percent}%)\n"
        f"uptime: {uptime}"
    )


@mcp.tool()
def network_info() -> str:
    """Get network info: IPs, interfaces, active connections, gateway latency."""
    addrs = psutil.net_if_addrs()
    lines = []
    for iface, entries in addrs.items():
        for e in entries:
            if e.family.name == "AF_INET":
                lines.append(f"{iface}: {e.address}")
    conns = len(psutil.net_connections())
    ping = subprocess.run(
        ["ping", "-c", "1", "-W", "2", "192.168.1.1"],
        capture_output=True, text=True
    )
    latency = "N/A"
    for line in ping.stdout.splitlines():
        if "time=" in line:
            latency = line.split("time=")[1].split()[0]
    lines.append(f"active connections: {conns}")
    lines.append(f"gateway latency: {latency}")
    return "\n".join(lines)


@mcp.tool()
def process_top(n: int = 10) -> str:
    """Top N processes by CPU/RAM usage."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    by_cpu = sorted(procs, key=lambda x: x["cpu_percent"] or 0, reverse=True)[:n]
    lines = [f"{'PID':<7} {'CPU%':<6} {'MEM%':<6} NAME"]
    for p in by_cpu:
        lines.append(f"{p['pid']:<7} {p['cpu_percent']:<6.1f} {p['memory_percent']:<6.1f} {p['name']}")
    return "\n".join(lines)


# --- Service & DevOps ---


@mcp.tool()
def service_control(name: str, action: str = "status") -> str:
    """Manage systemd services. Actions: status, restart, stop, start, enable, disable, logs."""
    if action == "logs":
        cmd = ["journalctl", "-u", name, "-n", "50", "--no-pager"]
    elif action == "status":
        cmd = ["systemctl", "status", name]
    else:
        cmd = ["sudo", "systemctl", action, name]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.stdout + r.stderr


@mcp.tool()
def deploy_app(app_name: str, app_dir: str = "", branch: str = "main") -> str:
    """Deploy an app: git pull + pip install (if requirements.txt) + systemctl restart."""
    d = app_dir or str(HOME / "WORKSPACE" / app_name)
    steps = []
    r = subprocess.run(["git", "pull", "origin", branch], cwd=d, capture_output=True, text=True, timeout=30)
    steps.append(f"git pull: {r.stdout.strip() or r.stderr.strip()}")
    req = Path(d) / "requirements.txt"
    if req.exists():
        venv_pip = Path(d) / ".venv" / "bin" / "pip"
        pip = str(venv_pip) if venv_pip.exists() else "pip3"
        r = subprocess.run([pip, "install", "-r", str(req)], cwd=d, capture_output=True, text=True, timeout=60)
        steps.append(f"pip install: {'ok' if r.returncode == 0 else r.stderr[:200]}")
    r = subprocess.run(["systemctl", "restart", app_name], capture_output=True, text=True, timeout=15)
    steps.append(f"restart: {'ok' if r.returncode == 0 else r.stderr.strip()}")
    return "\n".join(steps)


@mcp.tool()
def backup_db(db_path: str) -> str:
    """Backup a SQLite database to ~/backups/ with timestamp."""
    BACKUPS.mkdir(exist_ok=True)
    name = Path(db_path).stem
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS / f"{name}_{ts}.db"
    r = subprocess.run(
        ["sqlite3", db_path, f".backup '{dest}'"],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode == 0:
        size = dest.stat().st_size // 1024
        return f"Backup saved: {dest} ({size}KB)"
    return f"Error: {r.stderr}"


@mcp.tool()
def nginx_reload() -> str:
    """Test nginx config and reload if valid."""
    test = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if test.returncode != 0:
        return f"Config error:\n{test.stderr}"
    r = subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, text=True)
    return "nginx reloaded" if r.returncode == 0 else r.stderr


@mcp.tool()
def cron_list() -> str:
    """List current user's crontab entries."""
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout or r.stderr or "No crontab"


@mcp.tool()
def cron_add(schedule: str, command: str) -> str:
    """Add a crontab entry. schedule: e.g. '0 3 * * *', command: the command to run."""
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    new_entry = f"{schedule} {command}\n"
    new_cron = existing + new_entry
    r = subprocess.run(["crontab", "-"], input=new_cron, capture_output=True, text=True)
    return f"Added: {new_entry.strip()}" if r.returncode == 0 else r.stderr


# --- Shell ---


@mcp.tool()
def run_command(command: str, cwd: str = "/home/egamgia", timeout: int = 30) -> str:
    """Run a shell command on the RPi4. Use for git, pip, builds, etc."""
    r = subprocess.run(
        command, shell=True, capture_output=True, text=True,
        cwd=cwd, timeout=timeout
    )
    output = r.stdout + r.stderr
    return output[:8000] if output else "(no output)"


# --- GPIO & Hardware ---


@mcp.tool()
def gpio_write(pin: int, value: bool) -> str:
    """Set a GPIO pin HIGH (true) or LOW (false) using gpiozero."""
    from gpiozero import LED
    led = LED(pin)
    led.on() if value else led.off()
    return f"GPIO {pin} set to {'HIGH' if value else 'LOW'}"


@mcp.tool()
def gpio_read(pin: int) -> str:
    """Read the current value of a GPIO pin."""
    from gpiozero import InputDevice
    device = InputDevice(pin)
    return f"GPIO {pin} = {device.value}"


@mcp.tool()
def pwm_control(pin: int, duty_cycle: float) -> str:
    """Control PWM on a pin. duty_cycle: 0.0 to 1.0 (for servo, LED dimmer, motors)."""
    from gpiozero import PWMOutputDevice
    device = PWMOutputDevice(pin)
    device.value = max(0.0, min(1.0, duty_cycle))
    return f"GPIO {pin} PWM set to {device.value:.2f}"


@mcp.tool()
def i2c_scan() -> str:
    """Scan I2C bus for connected devices."""
    r = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True, text=True, timeout=5)
    return r.stdout or r.stderr


@mcp.tool()
def sensor_read(sensor_type: str = "cpu_temp") -> str:
    """Read sensor data. Types: cpu_temp, dht22 (pin 4), bme280 (i2c)."""
    if sensor_type == "cpu_temp":
        temp = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return f"CPU temp: {int(temp) / 1000:.1f}°C"
    elif sensor_type == "dht22":
        try:
            import adafruit_dht
            import board
            d = adafruit_dht.DHT22(board.D4)
            return f"temp: {d.temperature:.1f}°C, humidity: {d.humidity:.1f}%"
        except Exception as e:
            return f"DHT22 error: {e}"
    elif sensor_type == "bme280":
        try:
            import smbus2
            import bme280
            bus = smbus2.SMBus(1)
            cal = bme280.load_calibration_params(bus, 0x76)
            data = bme280.sample(bus, 0x76, cal)
            return f"temp: {data.temperature:.1f}°C, humidity: {data.humidity:.1f}%, pressure: {data.pressure:.1f}hPa"
        except Exception as e:
            return f"BME280 error: {e}"
    return f"Unknown sensor type: {sensor_type}"


@mcp.tool()
def camera_capture(output_path: str = "") -> str:
    """Capture a photo with the Pi camera. Returns the file path."""
    path = output_path or str(HOME / "IMAGES" / f"capture_{int(time.time())}.jpg")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["libcamera-still", "-o", path, "--nopreview", "-t", "1000"],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0:
        size = Path(path).stat().st_size // 1024
        return f"Captured: {path} ({size}KB)"
    return f"Error: {r.stderr}"


# --- Logs ---


@mcp.tool()
def read_logs(service: str = "", pattern: str = "", lines: int = 50) -> str:
    """Read systemd journal logs. Filter by service and/or grep pattern."""
    cmd = ["journalctl", "--no-pager", "-n", str(lines)]
    if service:
        cmd += ["-u", service]
    if pattern:
        cmd += ["--grep", pattern]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.stdout + r.stderr


# --- LLM / Ollama ---


@mcp.tool()
def ollama_status() -> str:
    """Check Ollama status: running models, memory usage."""
    r = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10)
    status = r.stdout or r.stderr
    r2 = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
    models = r2.stdout or r2.stderr
    return f"Running:\n{status}\nInstalled:\n{models}"


@mcp.tool()
def ollama_generate(prompt: str, model: str = "qwen2.5:1.5b") -> str:
    """Generate text with Ollama. Returns the response."""
    r = subprocess.run(
        ["ollama", "run", model, prompt],
        capture_output=True, text=True, timeout=120
    )
    return r.stdout[:4000] or r.stderr


# --- Automation ---


@mcp.tool()
def wake_on_lan(mac: str) -> str:
    """Send Wake-on-LAN magic packet to a MAC address."""
    r = subprocess.run(
        ["wakeonlan", mac], capture_output=True, text=True, timeout=5
    )
    return r.stdout.strip() or r.stderr or f"WoL packet sent to {mac}"


@mcp.tool()
def docker_status() -> str:
    """List Docker containers with status and resource usage."""
    r = subprocess.run(
        ["docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"],
        capture_output=True, text=True, timeout=10
    )
    return r.stdout or r.stderr or "Docker not available"


@mcp.tool()
def file_serve(path: str, port: int = 9090, duration: int = 300) -> str:
    """Serve a file temporarily via HTTP. Returns the URL. Auto-stops after duration seconds."""
    import threading
    from http.server import HTTPServer, SimpleHTTPRequestHandler

    directory = str(Path(path).parent)
    filename = Path(path).name

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)
        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)

    def shutdown():
        time.sleep(duration)
        server.shutdown()

    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=shutdown, daemon=True).start()

    ip = subprocess.run(
        ["hostname", "-I"], capture_output=True, text=True
    ).stdout.split()[0]
    return f"http://{ip}:{port}/{filename} (available for {duration}s)"


@mcp.tool()
def format_sd(device: str = "", label: str = "SDCARD", fstype: str = "fat32") -> str:
    """Format an SD card or USB drive. Auto-detects removable media if device not specified. fstype: fat32, ext4."""
    if not device:
        # Auto-detect removable device (not sda which is our SSD)
        r = subprocess.run(["lsblk", "-dno", "NAME,RM,SIZE,TYPE"], capture_output=True, text=True)
        for line in r.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 4 and parts[1] == "1" and parts[3] == "disk" and parts[0] != "sda":
                device = f"/dev/{parts[0]}"
                break
        if not device:
            return "No removable device found"
    # Safety check
    if device == "/dev/sda":
        return "Refusing to format /dev/sda (system SSD)"
    steps = []
    r = subprocess.run(["sudo", "wipefs", "-a", device], capture_output=True, text=True, timeout=10)
    steps.append(f"wipefs: {'ok' if r.returncode == 0 else r.stderr.strip()}")
    r = subprocess.run(["sudo", "parted", device, "--script", "mklabel", "msdos", "mkpart", "primary", fstype, "1MiB", "100%"], capture_output=True, text=True, timeout=10)
    steps.append(f"parted: {'ok' if r.returncode == 0 else r.stderr.strip()}")
    part = f"{device}1"
    if fstype == "fat32":
        r = subprocess.run(["sudo", "mkfs.vfat", "-F", "32", "-n", label, part], capture_output=True, text=True, timeout=30)
    else:
        r = subprocess.run(["sudo", "mkfs.ext4", "-L", label, part], capture_output=True, text=True, timeout=30)
    steps.append(f"mkfs: {'ok' if r.returncode == 0 else r.stderr.strip()}")
    return "\n".join(steps)


@mcp.tool()
def speedtest() -> str:
    """Run an internet speed test. Returns download, upload, ping."""
    r = subprocess.run(
        ["speedtest-cli", "--simple"],
        capture_output=True, text=True, timeout=60
    )
    return r.stdout.strip() or r.stderr.strip() or "speedtest-cli not installed"


@mcp.tool()
def backup_all() -> str:
    """Backup all SQLite databases to ~/backups/ with timestamp."""
    import glob
    date = time.strftime("%Y%m%d_%H%M")
    bkp = HOME / "backups"
    bkp.mkdir(exist_ok=True)
    dbs = glob.glob(str(HOME / "WORKSPACE" / "**" / "*.db"), recursive=True)
    results = []
    for db in dbs:
        name = Path(db).stem
        dest = bkp / f"{name}-{date}.db"
        r = subprocess.run(["sqlite3", db, f".backup '{dest}'"], capture_output=True, text=True, timeout=10)
        results.append(f"{name}: {'ok' if r.returncode == 0 else r.stderr.strip()}")
    return "\n".join(results) or "No databases found"


@mcp.tool()
def git_status(project: str = "") -> str:
    """Show git status for one or all projects in ~/WORKSPACE."""
    ws = HOME / "WORKSPACE"
    projects = [ws / project] if project else sorted(ws.iterdir())
    lines = []
    for p in projects:
        if not (p / ".git").exists():
            continue
        r = subprocess.run(["git", "status", "--short", "--branch"], cwd=str(p), capture_output=True, text=True, timeout=10)
        lines.append(f"[{p.name}]\n{r.stdout.strip()}")
    return "\n\n".join(lines) or "No git repos found"


# --- Logging middleware ---
_original_tools = {}
for _name, _fn in list(mcp._tool_manager._tools.items()):
    _original_tools[_name] = _fn.fn

    def _make_wrapper(name, fn):
        def wrapper(*args, **kwargs):
            t0 = time.time()
            result = fn(*args, **kwargs)
            _log_call(name, kwargs, str(result) if result else "", time.time() - t0)
            return result
        return wrapper

    _fn.fn = _make_wrapper(_name, _fn.fn)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
