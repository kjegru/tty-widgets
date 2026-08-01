#!/usr/bin/env python3
"""
72x13 Focus & Pomodoro Desk Companion for Fish / Bash terminal.
Fits precisely in a 72-column by 13-line terminal pane.

Controls:
  [Space] Start / Pause        [S] Skip current phase
  [T] Edit task name           [R] Reset all
  [+/-]   Adjust work minutes  [Q] Quit
"""
import sys
import time
import os
import curses
from datetime import datetime

# ── Big-digit font (5 rows × 4 cols each glyph) ─────────────────────────────
BIG_DIGITS = {
    '0': ["▛▀▀▜","▌  ▐","▌  ▐","▌  ▐","▙▄▄▟"],
    '1': [" ▟▌ ","  ▌ ","  ▌ ","  ▌ "," ▟█▙"],
    '2': ["▛▀▀▜","   ▐","▟▀▀▘","▌   ","▙▄▄▄"],
    '3': ["▛▀▀▜","   ▐"," ▀▀▟","   ▐","▙▄▄▟"],
    '4': ["▌  ▐","▙▄▄▟","   ▐","   ▐","   ▐"],
    '5': ["▛▀▀▀","▌   ","▙▀▀▜","   ▐","▙▄▄▟"],
    '6': ["▛▀▀▀","▌   ","▙▀▀▜","▌  ▐","▙▄▄▟"],
    '7': ["▀▀▀▜","   ▐","  ▟▘","  ▌ ","  ▌ "],
    '8': ["▛▀▀▜","▌  ▐","▟▀▀▟","▌  ▐","▙▄▄▟"],
    '9': ["▛▀▀▜","▌  ▐","▙▄▄▟","   ▐","▙▄▄▟"],
    ':': ["    "," ██ ","    "," ██ ","    "],
    ' ': ["    ","    ","    ","    ","    "],
}

PROGRESS_FULL  = "▰"
PROGRESS_EMPTY = "▱"

SESSIONS_BEFORE_LONG = 4

MOTIVATIONAL = [
    "Stay in the zone.",
    "One step at a time.",
    "Deep work creates value.",
    "Focus is a superpower.",
    "Ship it.",
    "No distractions.",
    "You're doing great!",
    "Make it count.",
    "Progress over perfection.",
    "Breathe. Focus. Execute.",
]

def render_big(text):
    rows = [""] * 5
    for ch in text:
        glyph = BIG_DIGITS.get(ch, BIG_DIGITS[' '])
        for i in range(5):
            rows[i] += glyph[i]
    return rows

def get_bar(percent, width):
    filled = max(0, min(width, int(round(width * percent / 100.0))))
    return PROGRESS_FULL * filled + PROGRESS_EMPTY * (width - filled)

def fmt_mmss(seconds):
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

def fit(text, width):
    return text[:width].ljust(width) if len(text) > width else text.ljust(width)


class PomodoroState:
    def __init__(self, work_mins=25):
        self.work_duration    = work_mins * 60
        self.session_count    = 0
        self.streak           = 0
        self.phase            = 'work'
        self.time_left        = float(work_mins * 60)
        self.running          = False
        self.last_tick        = None
        self.task             = "Press [T] to set task"
        self.motiv_idx        = 0

    def phase_duration(self):
        if self.phase == 'work':        return self.work_duration
        if self.phase == 'short_break': return 5 * 60
        return 15 * 60

    def progress_pct(self):
        total   = self.phase_duration()
        elapsed = total - self.time_left
        return max(0.0, min(100.0, elapsed / total * 100.0))

    def tick(self):
        if self.running:
            now = time.time()
            if self.last_tick is not None:
                self.time_left -= now - self.last_tick
            self.last_tick = now
            if self.time_left <= 0:
                self.time_left = 0
                self._advance(skipped=False)

    def toggle(self):
        self.running   = not self.running
        self.last_tick = time.time() if self.running else None

    def skip(self):
        if self.phase == 'work':
            self.streak = 0
        self._advance(skipped=True)

    def _advance(self, skipped=False):
        if self.phase == 'work' and not skipped:
            self.session_count += 1
            self.streak        += 1
        if self.phase == 'work':
            if self.session_count % SESSIONS_BEFORE_LONG == 0 and self.session_count > 0:
                self.phase     = 'long_break'
                self.time_left = 15.0 * 60
            else:
                self.phase     = 'short_break'
                self.time_left = 5.0 * 60
        else:
            self.phase     = 'work'
            self.time_left = float(self.work_duration)
        self.running   = False
        self.last_tick = None
        self.motiv_idx = (self.motiv_idx + 1) % len(MOTIVATIONAL)

    def reset(self):
        self.__init__(self.work_duration // 60)

    def phase_label(self):
        return {'work': 'WORK TIME', 'short_break': 'SHORT BREAK', 'long_break': 'LONG BREAK'}[self.phase]

    def phase_emoji(self):
        return {'work': '🎯', 'short_break': '☕', 'long_break': '🌿'}[self.phase]


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(1, curses.COLOR_CYAN,    -1)
    curses.init_pair(2, curses.COLOR_GREEN,   -1)
    curses.init_pair(3, curses.COLOR_YELLOW,  -1)
    curses.init_pair(4, curses.COLOR_RED,     -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_BLUE,    -1)
    curses.init_pair(7, curses.COLOR_WHITE,   -1)

    C_CYAN  = curses.color_pair(1) | curses.A_BOLD
    C_GREEN = curses.color_pair(2) | curses.A_BOLD
    C_YEL   = curses.color_pair(3) | curses.A_BOLD
    C_RED   = curses.color_pair(4) | curses.A_BOLD
    C_MAG   = curses.color_pair(5) | curses.A_BOLD
    C_BLUE  = curses.color_pair(6)
    C_WHITE = curses.color_pair(7) | curses.A_BOLD
    C_DIM   = curses.color_pair(6)

    pomo         = PomodoroState()
    editing_task = False
    task_buf     = ""
    blink        = 0

    def pc():   # phase + running colour
        if pomo.phase == 'work':
            return C_GREEN if pomo.running else C_YEL
        return C_RED if pomo.running else C_YEL

    def bc():   # bar colour
        return C_GREEN if pomo.phase == 'work' else C_RED

    while True:
        pomo.tick()
        blink = (blink + 1) % 8

        # ── Keyboard ──────────────────────────────────────────────────────────
        try:
            ch = stdscr.getch()
            if editing_task:
                if ch in (10, 13):
                    pomo.task    = task_buf.strip() or pomo.task
                    editing_task = False
                    task_buf     = ""
                    curses.curs_set(0)
                elif ch in (27,):
                    editing_task = False
                    task_buf     = ""
                    curses.curs_set(0)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    task_buf = task_buf[:-1]
                elif 32 <= ch <= 126:
                    task_buf += chr(ch)
            else:
                if ch in (ord('q'), ord('Q'), 27):
                    break
                elif ch == ord(' '):
                    pomo.toggle()
                elif ch in (ord('s'), ord('S')):
                    pomo.skip()
                elif ch in (ord('t'), ord('T')):
                    editing_task = True
                    task_buf     = "" if pomo.task == "Press [T] to set task" else pomo.task
                    curses.curs_set(1)
                elif ch in (ord('r'), ord('R')):
                    pomo.reset()
                elif ch in (ord('+'), ord('=')):
                    pomo.work_duration = min(90 * 60, pomo.work_duration + 60)
                    if pomo.phase == 'work' and not pomo.running:
                        pomo.time_left = float(pomo.work_duration)
                elif ch in (ord('-'), ord('_')):
                    pomo.work_duration = max(5 * 60, pomo.work_duration - 60)
                    if pomo.phase == 'work' and not pomo.running:
                        pomo.time_left = float(pomo.work_duration)
        except Exception:
            pass

        # ── Build frame ───────────────────────────────────────────────────────
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        pct       = pomo.progress_pct()
        big_rows  = render_big(fmt_mmss(pomo.time_left))
        ph_label  = pomo.phase_label()
        ph_emoji  = pomo.phase_emoji()
        work_mins = pomo.work_duration // 60
        motiv     = MOTIVATIONAL[pomo.motiv_idx]
        now_str   = datetime.now().strftime("%H:%M")
        status    = "▶ RUNNING  " if pomo.running else ("✏ EDIT TASK" if editing_task else "❚❚ PAUSED  ")
        cursor_ch = "█" if editing_task and blink < 4 else " "
        task_disp = (task_buf + cursor_ch) if editing_task else pomo.task

        lines = []   # [(text, color), ...]

        # L0 ─ Top border ──────────────────────────────────────────────────────
        ph_tag   = f"[{ph_label}]"
        title    = "⏳ POMODORO FOCUS SESSION"
        # title len = 26 (with emoji width 2), ph_tag varies
        # structure: ╭─ <title> <dashes> <ph_tag> ─╮  total 72
        # fixed = 2 (╭─) + 1 ( ) + len(title) + 1 ( ) + 1 ( ) + len(ph_tag) + 2 ( ─╮)
        # emoji in title counts as 2 wide in most terminals
        title_vis = len(title) + 1  # emoji adds 1 extra cell
        fixed     = 2 + 1 + title_vis + 1 + 1 + len(ph_tag) + 2
        dash_len  = max(1, 72 - fixed)
        l0 = f"╭─ {title} " + "─" * dash_len + f" {ph_tag} ─╮"
        lines.append([(l0, C_CYAN)])

        # L1 ─ Status row ──────────────────────────────────────────────────────
        left  = f"│ {ph_emoji}  {status}"
        right = f"  {motiv}  {now_str} │"
        mid   = " " * max(0, 72 - len(left) - len(right) - 1)  # emoji = 2 cells
        lines.append([(left, pc()), (mid, C_DIM), (right, C_DIM)])

        # L2–L6 ─ Big clock (5 rows) + sidebar ────────────────────────────────
        # clock segment = "│  " + 4 digits × 4 + colon × 4 = "│  " + 20 chars = 23 chars wide
        # sidebar fills the rest up to │
        streak_dots = "🔥" * min(pomo.streak, 5) if pomo.streak > 0 else "—"
        pos_in_cycle = pomo.session_count % SESSIONS_BEFORE_LONG

        sidebar = [
            f"  Task: {fit(task_disp, 21)}",
            f"  Streak: {streak_dots}  ({pomo.streak})",
            f"  Remaining: {fmt_mmss(pomo.time_left)}     ",
            f"  Sessions done: {pomo.session_count:3d}  ",
            f"  Work: {work_mins:2d}m  [+/-] adjust",
        ]
        sidebar_cols = [C_WHITE, C_YEL, pc(), C_BLUE, C_DIM]

        for i in range(5):
            clock_seg = f"│  {big_rows[i]}  "
            side_seg  = sidebar[i]
            pad_len   = 72 - len(clock_seg) - len(side_seg) - 1
            lines.append([
                (clock_seg,                 pc()),
                (side_seg,                  sidebar_cols[i]),
                (" " * max(0, pad_len) + "│", C_CYAN),
            ])

        # L7 ─ Separator ───────────────────────────────────────────────────────
        lines.append([(f"│{'─' * 70}│", C_CYAN)])

        # L8 ─ Progress bar ────────────────────────────────────────────────────
        bar_prefix = "│  Progress: ["
        bar_suffix = f"]  {pct:5.1f}%  │"
        bar_w      = 72 - len(bar_prefix) - len(bar_suffix)
        lines.append([
            (bar_prefix,        C_CYAN),
            (get_bar(pct, bar_w), bc()),
            (bar_suffix,        C_CYAN),
        ])

        # L9 ─ Cycle dots + controls ───────────────────────────────────────────
        dot_f = "●"; dot_e = "○"
        dots  = "".join(dot_f if d < pos_in_cycle else dot_e for d in range(SESSIONS_BEFORE_LONG))
        ctrl  = " [Space] Play/Pause  [S] Skip  [T] Task  [R] Reset  [Q] Quit"
        cycle_lbl = f"│ Cycle {dots}  {SESSIONS_BEFORE_LONG - pos_in_cycle} to long break"
        pad_ctrl  = 72 - len(cycle_lbl) - len(ctrl) - 1
        lines.append([
            (cycle_lbl,             C_MAG),
            (ctrl,                  C_DIM),
            (" " * max(0, pad_ctrl) + "│", C_CYAN),
        ])

        # L10 ─ Bottom border ──────────────────────────────────────────────────
        lines.append([(f"╰{'─' * 70}╯", C_CYAN)])

        # ── Draw ──────────────────────────────────────────────────────────────
        for row, segments in enumerate(lines):
            if row >= max_y:
                break
            col = 0
            for text, color in segments:
                if not text:
                    continue
                avail = max_x - col
                if avail <= 0:
                    break
                if len(text) > avail:
                    text = text[:avail]
                try:
                    stdscr.addstr(row, col, text, color)
                except curses.error:
                    pass
                col += len(text)

        stdscr.refresh()
        time.sleep(0.125)   # ~8 fps


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)
