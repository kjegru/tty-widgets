#!/usr/bin/env python3
"""
72x12 Micro Hardware Monitor with GPU support for Fish / Bash terminal.
Fits precisely in a 72-column by 12-line terminal pane.
"""
import sys
import time
import os
import subprocess
import curses
import psutil
from datetime import datetime

# Block sparkline characters (9 levels: space + 8 block heights)
SPARK_CHARS = [" ", chr(9601), "▂", "▃", "▄", "▅", "▆", "▇", "█"]
BAR_FILLED = "█"
BAR_EMPTY = "░"

class History:
    def __init__(self, max_len=10):
        self.max_len = max_len
        self.data = [0.0] * max_len

    def add(self, val):
        self.data.pop(0)
        self.data.append(max(0.0, min(100.0, float(val))))

    def sparkline(self):
        res = []
        for v in self.data:
            if v <= 0.0:
                idx = 0
            else:
                idx = max(1, int((v / 100.0) * (len(SPARK_CHARS) - 1)))
                idx = min(len(SPARK_CHARS) - 1, idx)
            res.append(SPARK_CHARS[idx])
        return "".join(res)

def get_bar(percent, width=14):
    filled_len = int(round(width * percent / 100.0))
    filled_len = max(0, min(width, filled_len))
    return BAR_FILLED * filled_len, BAR_EMPTY * (width - filled_len)

def get_gpu_info():
    # Try nvidia-smi
    try:
        cmd = ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=1).decode("utf-8").strip()
        if out:
            parts = [p.strip() for p in out.split(",")]
            name = parts[0].replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
            gpu_util = float(parts[1])
            vram_used = float(parts[2]) / 1024.0 # GB
            vram_total = float(parts[3]) / 1024.0 # GB
            vram_util = (vram_used / vram_total * 100.0) if vram_total > 0 else 0.0
            temp = int(parts[4]) if parts[4].isdigit() else 0
            return {
                "name": name,
                "gpu_util": gpu_util,
                "vram_used": vram_used,
                "vram_total": vram_total,
                "vram_util": vram_util,
                "temp": temp,
                "available": True
            }
    except Exception:
        pass

    # Try amdgpu sysfs
    try:
        busy_path = "/sys/class/drm/card0/device/gpu_busy_percent"
        if os.path.exists(busy_path):
            with open(busy_path, "r") as f:
                gpu_util = float(f.read().strip())
            return {
                "name": "AMD GPU",
                "gpu_util": gpu_util,
                "vram_used": 0.0,
                "vram_total": 0.0,
                "vram_util": 0.0,
                "temp": 0,
                "available": True
            }
    except Exception:
        pass

    return {"name": "NO GPU", "gpu_util": 0.0, "vram_used": 0.0, "vram_total": 0.0, "vram_util": 0.0, "temp": 0, "available": False}

def format_rate(bytes_sec):
    if bytes_sec >= 1024 * 1024 * 1024:
        v = bytes_sec / (1024**3)
        return f"{v:.1f}G" if v < 10 else f"{int(v)}G"
    elif bytes_sec >= 1024 * 1024:
        v = bytes_sec / (1024**2)
        return f"{v:.1f}M" if v < 10 else f"{int(v)}M"
    elif bytes_sec >= 1024:
        v = bytes_sec / 1024
        return f"{v:.1f}K" if v < 10 else f"{int(v)}K"
    else:
        return f"{int(bytes_sec)}B"

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()

    # Color pairs
    curses.init_pair(1, curses.COLOR_CYAN, -1)    # Borders
    curses.init_pair(2, curses.COLOR_GREEN, -1)   # Normal usage
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Mid usage
    curses.init_pair(4, curses.COLOR_RED, -1)     # High usage
    curses.init_pair(5, curses.COLOR_MAGENTA, -1) # GPU
    curses.init_pair(6, curses.COLOR_BLUE, -1)    # Details

    C_CYAN = curses.color_pair(1) | curses.A_BOLD
    C_GREEN = curses.color_pair(2)
    C_YELLOW = curses.color_pair(3)
    C_RED = curses.color_pair(4)
    C_MAG = curses.color_pair(5) | curses.A_BOLD
    C_BLUE = curses.color_pair(6)
    C_WHITE = curses.A_BOLD
    C_DIM = curses.color_pair(6) # Dimmed elements

    def get_color(val):
        if val > 85: return C_RED
        if val > 60: return C_YELLOW
        return C_GREEN

    hist_cpu = History(10)
    hist_ram = History(10)
    hist_gpu = History(10)
    hist_vram = History(10)
    hist_net_rx = History(10)
    hist_disk = History(10)

    last_net = psutil.net_io_counters()
    last_disk = psutil.disk_io_counters()
    last_time = time.time()
    interval = 1.0

    psutil.cpu_percent() # Warmup

    while True:
        now = time.time()
        dt = max(0.1, now - last_time)
        last_time = now

        # CPU & RAM
        cpu_pct = psutil.cpu_percent()
        hist_cpu.add(cpu_pct)

        ram = psutil.virtual_memory()
        hist_ram.add(ram.percent)

        # GPU
        gpu_info = get_gpu_info()
        hist_gpu.add(gpu_info["gpu_util"])
        hist_vram.add(gpu_info["vram_util"])

        # Network IO
        net_now = psutil.net_io_counters()
        rx_speed = (net_now.bytes_recv - last_net.bytes_recv) / dt
        tx_speed = (net_now.bytes_sent - last_net.bytes_sent) / dt
        last_net = net_now
        hist_net_rx.add(min(100.0, (rx_speed / (5 * 1024 * 1024)) * 100.0))

        # Disk IO
        disk_now = psutil.disk_io_counters()
        disk_read = (disk_now.read_bytes - last_disk.read_bytes) / dt if disk_now else 0
        disk_write = (disk_now.write_bytes - last_disk.write_bytes) / dt if disk_now else 0
        last_disk = disk_now
        disk_usage = psutil.disk_usage('/')
        hist_disk.add(disk_usage.percent)

        # CPU Temp
        cpu_temp = "N/A"
        try:
            temps = psutil.sensors_temperatures()
            for key in ("coretemp", "k10temp", "cpu_thermal"):
                if key in temps and temps[key]:
                    cpu_temp = f"{int(temps[key][0].current)}°C"
                    break
        except Exception:
            pass

        # Load & Freq
        try:
            load1, load5, _ = os.getloadavg()
            load_str = f"{load1:.2f} {load5:.2f}"
        except Exception:
            load_str = "N/A"

        try:
            freq = psutil.cpu_freq()
            freq_str = f"{freq.current/1000:.1f}G" if freq else ""
        except Exception:
            freq_str = ""

        # Top CPU process
        top_proc = "N/A"
        try:
            procs = sorted(psutil.process_iter(['name', 'cpu_percent']), key=lambda p: p.info['cpu_percent'] or 0, reverse=True)
            if procs:
                p = procs[0]
                top_proc = f"{p.info['name'][:10]} ({(p.info['cpu_percent'] or 0):.0f}%)"
        except Exception:
            pass

        time_str = datetime.now().strftime("%H:%M:%S")
        gpu_name = gpu_info['name'][:12] if gpu_info['available'] else "NO GPU"

        stdscr.erase()

        # Build 11 lines strictly formatted to 72 width using segment lists
        lines = []

        # L0: Header
        header_title = "⚡ HW MONITOR"
        gpu_tag = f"[{gpu_name}]"
        dashes_len = 72 - (1 + 2 + len(header_title) + 1 + 1 + len(gpu_tag) + 3 + len(time_str) + 2 + 1)
        l0_str = f"╭─ {header_title} " + "─" * dashes_len + f" {gpu_tag} ─ {time_str} ─╮"
        lines.append([(l0_str, C_CYAN)])

        # L1: CPU
        cpu_color = get_color(cpu_pct)
        c_fbar, c_ebar = get_bar(cpu_pct, 14)
        cpu_info = f"[{freq_str:>5}]"
        cpu_tail = f"Temp:{cpu_temp:>5}"
        # Pad tail to 14 chars to match other lines
        cpu_tail = f"{cpu_tail:<14}"
        lines.append([
            ("│", C_CYAN),
            ("CPU  ", C_WHITE),
            (f"{cpu_info:>12}", C_BLUE),
            (" ", C_WHITE),
            (hist_cpu.sparkline(), cpu_color),
            ("  ", C_WHITE),
            (f"{cpu_pct:5.1f}%", cpu_color),
            ("  ", C_WHITE),
            ("[", C_CYAN),
            (c_fbar, cpu_color),
            (c_ebar, C_DIM),
            ("]", C_CYAN),
            ("  ", C_WHITE),
            (cpu_tail, C_WHITE),
            ("│", C_CYAN),
        ])

        # L2: CPU Details
        l2_inner = f" Load: {load_str:<8} │ Cores: {psutil.cpu_count(logical=True):<2} ({psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True):<2}c) │ Tasks: {len(psutil.pids()):<4} │ Top: {top_proc:<13} "
        lines.append([
            ("│", C_CYAN),
            (l2_inner, C_BLUE),
            ("│", C_CYAN),
        ])

        # L3: RAM
        ram_u = ram.used / (1024**3)
        ram_t = ram.total / (1024**3)
        ram_color = get_color(ram.percent)
        r_fbar, r_ebar = get_bar(ram.percent, 14)
        swap_pct = psutil.swap_memory().percent
        lines.append([
            ("│", C_CYAN),
            ("RAM  ", C_WHITE),
            (f"[{ram_u:4.1f}/{ram_t:4.1f}G]", C_BLUE),
            (" ", C_WHITE),
            (hist_ram.sparkline(), ram_color),
            ("  ", C_WHITE),
            (f"{ram.percent:5.1f}%", ram_color),
            ("  ", C_WHITE),
            ("[", C_CYAN),
            (r_fbar, ram_color),
            (r_ebar, C_DIM),
            ("]", C_CYAN),
            ("  ", C_WHITE),
            (f"Swap: {swap_pct:3.0f}%    ", C_WHITE),
            ("│", C_CYAN),
        ])

        # L4: GPU Core
        gpu_u = gpu_info['gpu_util']
        gpu_temp = f"{gpu_info['temp']}°C" if gpu_info['temp'] > 0 else "N/A"
        gpu_color = get_color(gpu_u)
        g_fbar, g_ebar = get_bar(gpu_u, 14)
        gpu_info_str = f"[{gpu_name[:8]:>8}]"
        gpu_tail = f"Temp:{gpu_temp:>5}"
        gpu_tail = f"{gpu_tail:<14}"
        lines.append([
            ("│", C_CYAN),
            ("GPU  ", C_MAG),
            (f"{gpu_info_str:>12}", C_MAG),
            (" ", C_WHITE),
            (hist_gpu.sparkline(), gpu_color),
            ("  ", C_WHITE),
            (f"{gpu_u:5.1f}%", gpu_color),
            ("  ", C_WHITE),
            ("[", C_CYAN),
            (g_fbar, gpu_color),
            (g_ebar, C_DIM),
            ("]", C_CYAN),
            ("  ", C_WHITE),
            (gpu_tail, C_WHITE),
            ("│", C_CYAN),
        ])

        # L5: GPU VRAM
        v_used = gpu_info['vram_used']
        v_tot = gpu_info['vram_total']
        v_pct = gpu_info['vram_util']
        vram_color = get_color(v_pct)
        v_fbar, v_ebar = get_bar(v_pct, 14)
        vram_info = f"[{v_used:4.1f}/{v_tot:4.1f}G]"
        lines.append([
            ("│", C_CYAN),
            ("VRAM ", C_MAG),
            (f"{vram_info:>12}", C_MAG),
            (" ", C_WHITE),
            (hist_vram.sparkline(), vram_color),
            ("  ", C_WHITE),
            (f"{v_pct:5.1f}%", vram_color),
            ("  ", C_WHITE),
            ("[", C_CYAN),
            (v_fbar, vram_color),
            (v_ebar, C_DIM),
            ("]", C_CYAN),
            ("  ", C_WHITE),
            ("              ", C_WHITE),
            ("│", C_CYAN),
        ])

        # L6: NET
        rx_fmt = format_rate(rx_speed)
        tx_fmt = format_rate(tx_speed)
        tot_rx = net_now.bytes_recv / (1024**3)
        tot_tx = net_now.bytes_sent / (1024**3)
        net_info = f"▼{rx_fmt:>4}▲{tx_fmt:>4}"
        net_tail = f"RX:{tot_rx:5.1f}G TX:{tot_tx:5.1f}G"
        lines.append([
            ("│", C_CYAN),
            ("NET  ", C_CYAN),
            (f"{net_info:>12}", C_CYAN),
            (" ", C_WHITE),
            (hist_net_rx.sparkline(), C_CYAN),
            ("  ", C_WHITE),
            (" SPEED", C_CYAN),
            ("  ", C_WHITE),
            (f"{net_tail:>32}", C_WHITE),
            ("│", C_CYAN),
        ])

        # L7: DISK
        d_pct = disk_usage.percent
        disk_color = get_color(d_pct)
        d_fbar, d_ebar = get_bar(d_pct, 14)
        free_gb = disk_usage.free / (1024**3)
        read_fmt = format_rate(disk_read)
        write_fmt = format_rate(disk_write)
        disk_info = f"R:{read_fmt:>4}W:{write_fmt:>4}"
        disk_tail = f"Free:{free_gb:4.0f}G"
        disk_tail = f"{disk_tail:<14}"
        lines.append([
            ("│", C_CYAN),
            ("DISK ", C_YELLOW),
            (f"{disk_info:>12}", C_YELLOW),
            (" ", C_WHITE),
            (hist_disk.sparkline(), disk_color),
            ("  ", C_WHITE),
            (f"{d_pct:5.1f}%", disk_color),
            ("  ", C_WHITE),
            ("[", C_CYAN),
            (d_fbar, disk_color),
            (d_ebar, C_DIM),
            ("]", C_CYAN),
            ("  ", C_WHITE),
            (disk_tail, C_WHITE),
            ("│", C_CYAN),
        ])

        # L8: System
        uptime_sec = time.time() - psutil.boot_time()
        up_str = f"{int(uptime_sec//3600)}h {int((uptime_sec%3600)//60)}m"
        host = os.uname().nodename[:14]
        l8_inner = f" SYS  Host: {host:<14} │ Uptime: {up_str:<9} │ Refresh: {interval:3.1f}s        "
        lines.append([
            ("│", C_CYAN),
            (l8_inner, C_BLUE),
            ("│", C_CYAN),
        ])

        # L9: Footer controls
        l9_inner = " [Q] Quit    [+] Speed Up    [-] Slow Down    [R] Reset Sparklines    "
        lines.append([
            ("│", C_CYAN),
            (l9_inner, C_WHITE),
            ("│", C_CYAN),
        ])

        # L10: Bottom border
        lines.append([("╰" + "─" * 70 + "╯", C_CYAN)])

        # Draw to screen
        max_y, max_x = stdscr.getmaxyx()
        for row, segments in enumerate(lines):
            if row >= max_y:
                break
            col = 0
            for text, color in segments:
                if text:
                    if col + len(text) > max_x:
                        text = text[:max(0, max_x - col)]
                    if text:
                        try:
                            stdscr.addstr(row, col, text, color)
                        except curses.error:
                            pass
                    col += len(text)

        stdscr.refresh()

        # Keyboard handling
        try:
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q'), 27):
                break
            elif ch in (ord('+'), ord('=')):
                interval = max(0.2, interval - 0.2)
            elif ch in (ord('-'), ord('_')):
                interval = min(5.0, interval + 0.2)
            elif ch in (ord('r'), ord('R')):
                hist_cpu = History(10)
                hist_ram = History(10)
                hist_gpu = History(10)
                hist_vram = History(10)
                hist_net_rx = History(10)
                hist_disk = History(10)
        except Exception:
            pass

        time.sleep(interval)

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)
