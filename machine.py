import collections
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
OS_NAME = "macOS" if IS_MAC else "Linux" if IS_LINUX else platform.system()


def run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def size_bytes(text):
    m = re.match(r"([\d.]+)\s*([KMGT]?)", text.strip())
    return float(m.group(1)) * 1024 ** "_KMGT".index(m.group(2) or "_") if m else 0


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def nvidia():
    if not shutil.which("nvidia-smi"):
        return {}
    out = run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"], timeout=5)
    rows = [r.split(",") for r in out.strip().splitlines() if "," in r]
    if not rows:
        return {}
    util = max(int(float(r[0])) for r in rows)
    used = sum(float(r[1]) for r in rows) * 1024 * 1024
    return {"gpu": util, "gpu_mem": used, "gpu_name": "NVIDIA"}


# --- macOS ---------------------------------------------------------------


def mac_sample():
    out = run(["top", "-l", "2", "-n", "0", "-s", "1"])
    sample = out[out.rfind("Processes:") :] if "Processes:" in out else out
    m_ = {}
    m = re.search(r"CPU usage: ([\d.]+)% user, ([\d.]+)% sys, ([\d.]+)% idle", sample)
    if m:
        m_["cpu_user"], m_["cpu_sys"], idle = map(float, m.groups())
        m_["cpu"] = round(100 - idle, 1)
    m = re.search(r"Load Avg: ([\d.]+), ([\d.]+), ([\d.]+)", sample)
    if m:
        m_["load"] = list(map(float, m.groups()))
    m = re.search(r"PhysMem: (\S+) used \((\S+) wired, (\S+) compressor\), (\S+) unused", sample)
    if m:
        m_["mem_used"], m_["mem_wired"], m_["mem_compressed"], m_["mem_unused"] = (size_bytes(x) for x in m.groups())
    m = re.search(r"Processes: (\d+) total", sample)
    if m:
        m_["processes"] = int(m.group(1))
    m = re.search(r"System-wide memory free percentage: (\d+)%", run(["memory_pressure", "-Q"]))
    if m:
        m_["mem_free_pct"] = int(m.group(1))
    m = re.search(r"total = (\S+)\s+used = (\S+)", run(["sysctl", "-n", "vm.swapusage"]))
    if m:
        m_["swap_total"], m_["swap_used"] = (size_bytes(x) for x in m.groups())
    gpu = run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"])
    for key, rx in (("gpu", "Device Utilization %"), ("gpu_renderer", "Renderer Utilization %"), ("gpu_mem", "In use system memory")):
        m = re.search(rf'"{rx}"=(\d+)', gpu)
        m_[key] = int(m.group(1)) if m else None
    data_vol = "/System/Volumes/Data" if os.path.isdir("/System/Volumes/Data") else "/"
    disk = shutil.disk_usage(data_vol)
    m_["disk_total"], m_["disk_used"], m_["disk_free"] = disk.total, disk.used, disk.free
    net = collections.Counter()
    for line in run(["netstat", "-ib", "-n"]).splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 10 and cols[0].startswith("en") and cols[2].startswith("<Link"):
            net["in"] += int(cols[6])
            net["out"] += int(cols[9])
    return m_, net


def mac_static():
    keys = ["hw.memsize", "hw.ncpu", "machdep.cpu.brand_string", "hw.perflevel0.physicalcpu", "hw.perflevel1.physicalcpu", "hw.model"]
    info = dict(zip(keys, run(["sysctl", "-n"] + keys).splitlines() + [""] * len(keys)))
    batt = run(["pmset", "-g", "batt"])
    m = re.search(r"(\d+)%; ([^;]+);", batt)
    m2 = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", run(["pmset", "-g", "therm"]))
    left = re.search(r"(\d+):(\d{2}) remaining", batt)
    return {
        "os": OS_NAME,
        "mem_total": int(info["hw.memsize"] or 0),
        "ncpu": info["hw.ncpu"],
        "chip": info["machdep.cpu.brand_string"],
        "model": info["hw.model"],
        "pcores": info["hw.perflevel0.physicalcpu"],
        "ecores": info["hw.perflevel1.physicalcpu"],
        "power": "AC" if "AC Power" in batt else "Battery",
        "battery": int(m.group(1)) if m else None,
        "battery_state": m.group(2).strip() if m else "",
        "battery_minutes": int(left.group(1)) * 60 + int(left.group(2)) if left and m and m.group(2).strip() == "discharging" and not left.group(0).startswith("0:00") else None,
        "cpu_speed_limit": int(m2.group(1)) if m2 else 100,
    }


# --- Linux ---------------------------------------------------------------

_cpu_prev = None


def _cpu_times():
    parts = read("/proc/stat").splitlines()[0].split()[1:]
    vals = list(map(int, parts)) + [0] * 8
    user, nice, system, idle, iowait, irq, softirq, steal = vals[:8]
    return {"user": user + nice, "sys": system + irq + softirq, "idle": idle + iowait, "total": sum(vals[:8])}


def linux_sample():
    global _cpu_prev
    m_ = {}
    now = _cpu_times()
    if _cpu_prev is None:
        time.sleep(0.5)
        _cpu_prev, now = now, _cpu_times()
    dt = max(1, now["total"] - _cpu_prev["total"])
    m_["cpu_user"] = round((now["user"] - _cpu_prev["user"]) * 100 / dt, 2)
    m_["cpu_sys"] = round((now["sys"] - _cpu_prev["sys"]) * 100 / dt, 2)
    m_["cpu"] = round(100 - (now["idle"] - _cpu_prev["idle"]) * 100 / dt, 1)
    _cpu_prev = now
    m_["load"] = [round(x, 2) for x in os.getloadavg()]
    mem = {}
    for line in read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0]) * 1024 if v.split() else 0
    total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", mem.get("MemFree", 0))
    m_["mem_used"] = total - avail
    m_["mem_cache"] = mem.get("Cached", 0) + mem.get("Buffers", 0)
    m_["mem_free_pct"] = round(avail * 100 / total) if total else 0
    m_["swap_total"], m_["swap_used"] = mem.get("SwapTotal", 0), mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)
    loadavg = read("/proc/loadavg").split()
    if len(loadavg) > 3 and "/" in loadavg[3]:
        m_["processes"] = int(loadavg[3].split("/")[1])
    m_.update({"gpu": None, "gpu_renderer": None, "gpu_mem": None})
    m_.update(nvidia())
    disk = shutil.disk_usage("/")
    m_["disk_total"], m_["disk_used"], m_["disk_free"] = disk.total, disk.used, disk.free
    net = collections.Counter()
    for line in read("/proc/net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        if name == "lo" or name.startswith(("docker", "br-", "veth", "virbr", "vnet")):
            continue
        cols = rest.split()
        if len(cols) >= 9:
            net["in"] += int(cols[0])
            net["out"] += int(cols[8])
    return m_, net


def linux_static():
    cpuinfo = read("/proc/cpuinfo")
    m = re.search(r"^(?:model name|Hardware|Model)\s*:\s*(.+)$", cpuinfo, re.M)
    mem_total = 0
    for line in read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            mem_total = int(line.split()[1]) * 1024
    vendor, product = read("/sys/devices/virtual/dmi/id/sys_vendor"), read("/sys/devices/virtual/dmi/id/product_name")
    battery, state, ac, minutes = None, "", None, None
    for ps in sorted(Path("/sys/class/power_supply").glob("*")) if Path("/sys/class/power_supply").is_dir() else []:
        kind = read(ps / "type")
        if kind == "Battery" and battery is None and read(ps / "capacity").isdigit():
            battery, state = int(read(ps / "capacity")), read(ps / "status").lower()
            now = next((read(ps / k) for k in ("energy_now", "charge_now") if read(ps / k).isdigit()), "")
            rate = next((read(ps / k) for k in ("power_now", "current_now") if read(ps / k).isdigit()), "")
            if state == "discharging" and now and rate and int(rate) > 0:
                minutes = int(int(now) / int(rate) * 60)
        elif kind == "Mains":
            ac = read(ps / "online") == "1"
    distro = ""
    for line in read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            distro = line.split("=", 1)[1].strip('"')
    return {
        "os": OS_NAME,
        "distro": distro,
        "mem_total": mem_total,
        "ncpu": str(os.cpu_count() or ""),
        "chip": m.group(1).strip() if m else platform.processor(),
        "model": " ".join(x for x in (vendor, product) if x and "To Be Filled" not in x),
        "pcores": "",
        "ecores": "",
        "power": "Battery" if ac is False else "AC",
        "battery": battery,
        "battery_state": state,
        "battery_minutes": minutes,
        "cpu_speed_limit": None,
    }


def sample():
    return mac_sample() if IS_MAC else linux_sample()


def static():
    return mac_static() if IS_MAC else linux_static()


def open_url(url):
    opener = "open" if IS_MAC else "xdg-open"
    if shutil.which(opener):
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return False


def start_docker():
    if IS_MAC:
        ok = shutil.which("open") and subprocess.run(["open", "-a", "Docker"], capture_output=True, timeout=20).returncode == 0
        return {"ok": bool(ok), "error": "" if ok else "Docker Desktop was not found"}
    for cmd in (["systemctl", "--user", "start", "docker-desktop"], ["systemctl", "--user", "start", "docker"]):
        if shutil.which(cmd[0]) and subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0:
            return {"ok": True, "error": ""}
    return {"ok": False, "error": "could not start Docker — run `sudo systemctl start docker` in a terminal"}


def has_display():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def pick_path(start, prompt, kind="folder"):
    start_dir = Path(start).expanduser() if start else Path.home()
    while not start_dir.is_dir() and start_dir != start_dir.parent:
        start_dir = start_dir.parent
    if IS_MAC:
        if not shutil.which("osascript"):
            return {"ok": False, "error": "osascript not found — type the path instead"}

        def quote(s):
            return s.replace("\\", "\\\\").replace('"', '\\"')

        verb = "choose file" if kind == "file" else "choose folder"
        extra = " with invisibles" if kind == "file" else ""
        cmd = [
            "osascript",
            "-e",
            f'tell application (path to frontmost application as text) to POSIX path of ({verb} with prompt "{quote(prompt[:120])}" default location POSIX file "{quote(str(start_dir))}"{extra})',
        ]
        cancelled = lambda res: "-128" in res.stderr  # noqa: E731
    elif shutil.which("zenity") and has_display():
        cmd = ["zenity", "--file-selection", f"--title={prompt[:120]}", f"--filename={start_dir}/"] + (["--directory"] if kind != "file" else [])
        cancelled = lambda res: res.returncode == 1  # noqa: E731
    elif shutil.which("kdialog") and has_display():
        cmd = ["kdialog", "--title", prompt[:120], "--getopenfilename" if kind == "file" else "--getexistingdirectory", str(start_dir)]
        cancelled = lambda res: res.returncode == 1  # noqa: E731
    else:
        return {"ok": False, "error": "no file dialog available (install zenity or kdialog) — type the path instead"}
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "cancelled": True}
    if res.returncode:
        if cancelled(res):
            return {"ok": False, "cancelled": True}
        return {"ok": False, "error": res.stderr.strip()[:200] or "could not open the dialog"}
    return {"ok": True, "path": res.stdout.strip().rstrip("/") or "/"}
