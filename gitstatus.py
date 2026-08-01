#!/usr/bin/env python3
"""
72x14 Git Status Widget for Fish / Bash terminal.
Fits precisely in a 72-column by 14-line terminal pane.

Controls:
  [R] Refresh     [Q] Quit
"""
import sys
import time
import os
import subprocess
import curses

BAR_FILLED  = chr(9608)
BAR_EMPTY   = chr(9617)


def progress_bar(count, max_val, width):
    if max_val == 0:
        return BAR_EMPTY * width
    filled = min(width, int(round(width * count / max_val)))
    return BAR_FILLED * filled + BAR_EMPTY * (width - filled)


def fit(text, width):
    s = text[:width]
    return s + " " * max(0, width - len(s))


def run_git(args):
    env = os.environ.copy()
    env["LANG"] = "C"
    try:
        r = subprocess.run(["git"] + args, capture_output=True, text=True,
                           env=env, timeout=5)
        if r.returncode != 0:
            return None
        return r.stdout.strip()
    except Exception:
        return None


class GitState:
    def __init__(self):
        self.branch          = ""
        self.modified        = 0
        self.added           = 0
        self.deleted         = 0
        self.untracked       = 0
        self.ahead           = 0
        self.behind          = 0
        self.stash_count     = 0
        self.last_msg        = ""
        self.last_age        = ""
        self.last_author     = ""
        self.is_bare         = False
        self.error           = None
        self.refresh()

    def refresh(self):
        if not run_git(["rev-parse", "--is-inside-work-tree"]):
            self.error = "Not inside a git work tree"
            return

        self.error  = None
        self.branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "???"

        raw = run_git(["status", "--porcelain"]) or ""
        self.modified = self.added = self.deleted = self.untracked = 0
        for line in raw.splitlines():
            if not line.strip():
                continue
            xy = line[:2]
            x, y = xy[0], xy[1]
            if x == "?" and y == "?":
                self.untracked += 1
            elif x in "MRC" or y in "MRC":
                self.modified += 1
            elif x == "A":
                self.added += 1
            elif x == "D":
                self.deleted += 1
            else:
                self.modified += 1

        self.ahead = self._count_revlist("@{u}..HEAD")
        self.behind = self._count_revlist("HEAD..@{u}")

        stash_raw = run_git(["stash", "list"]) or ""
        self.stash_count = len(stash_raw.splitlines()) if stash_raw else 0

        self.last_msg    = run_git(["log", "-1", "--format=%s"]) or "(no commits)"
        self.last_age    = run_git(["log", "-1", "--format=%ar"]) or ""
        self.last_author = run_git(["log", "-1", "--format=%an"]) or ""

    def _count_revlist(self, rev_range):
        s = run_git(["rev-list", "--count", rev_range])
        if s and s.isdigit():
            return int(s)
        return 0

    @property
    def dirty_total(self):
        return self.modified + self.added + self.deleted + self.untracked

    @property
    def is_clean(self):
        return self.dirty_total == 0 and self.ahead == 0


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

    state       = GitState()
    last_refr   = time.time()
    AUTO_REFR   = 15
    W           = 72

    def file_color(abbr):
        return C_YEL if abbr == "M" else (C_GREEN if abbr == "A"
               else (C_RED if abbr == "D" else C_DIM))

    def draw(lines):
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

    while True:
        now = time.time()
        if now - last_refr >= AUTO_REFR:
            state.refresh()
            last_refr = now

        try:
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q'), 27):
                break
            elif ch in (ord('r'), ord('R')):
                state.refresh()
                last_refr = time.time()
        except Exception:
            pass

        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        # ── Error screen ───────────────────────────────────────────────────
        if state.error:
            lines = [
                [("╭─ GIT STATUS " + "─" * 56 + "─╮", C_CYAN)],
                [(f"│  {state.error.ljust(66)}  │", C_RED)],
                [(f"╰{'─' * (W - 2)}╯", C_CYAN)],
            ]
            draw(lines)
            stdscr.refresh()
            time.sleep(0.5)
            continue

        dirty   = state.dirty_total
        max_d   = max(1, dirty)
        BAR_W   = 48
        LABEL_W = 9

        lines = []

        # L0 ─ Top border ───────────────────────────────────────────────────
        l0 = "╭─ GIT STATUS ─" + "─" * (W - 15 - 2) + "─╮"
        lines.append([(l0, C_CYAN)])

        # L1 ─ Branch + upstream ────────────────────────────────────────────
        clean_mark = " ✓" if state.is_clean else ""
        branch_name = state.branch
        branch_color = C_GREEN if state.is_clean else C_YEL

        ups_parts = []
        if state.ahead > 0:
            ups_parts.append(f"↑{state.ahead}")
        if state.behind > 0:
            ups_parts.append(f"↓{state.behind}")
        ups_str = "  " + "  ".join(ups_parts) if ups_parts else ""

        prefix = "│  Branch  "
        available = W - 2 - len(prefix) - len(clean_mark) - len(ups_str) - 2
        if len(branch_name) > available:
            branch_name = branch_name[:available - 1] + "…"
        branch_part = f"{prefix}{branch_name}"
        pad_mid = W - 2 - len(branch_part) - len(clean_mark) - len(ups_str)
        l1 = branch_part + clean_mark + " " * max(0, pad_mid) + ups_str + " │"
        lines.append([(l1, branch_color)])

        # L2 ─ Separator ────────────────────────────────────────────────────
        lines.append([(f"│{'─' * (W - 2)}│", C_DIM)])

        # L3–L6 ─ File status rows ──────────────────────────────────────────
        rows_file = [
            ("M", state.modified,  "Modified"),
            ("A", state.added,     "Added"),
            ("D", state.deleted,   "Deleted"),
            ("U", state.untracked, "Untracked"),
        ]
        for abbr, count, label in rows_file:
            label_part = f"│   {abbr}  {label:<{LABEL_W}}"
            count_str  = f"{count:3d}"
            bar_str    = progress_bar(count, max_d, BAR_W)
            line_str   = f"{label_part} {count_str}  {bar_str} │"
            lines.append([(line_str, file_color(abbr))])

        # L7 ─ Separator ────────────────────────────────────────────────────
        lines.append([(f"│{'─' * (W - 2)}│", C_DIM)])

        # L8 ─ Age ───────────────────────────────────────────────────────────
        l8 = f"│  Last     {state.last_age}"
        pad_l8 = W - len(l8) - 1
        l8 = l8 + (" " * max(0, pad_l8)) + "│"
        lines.append([(l8, C_WHITE)])

        # L9 ─ Author & Stash ────────────────────────────────────────────────
        author = state.last_author
        max_author = W - 22 - 10  # "│  Author   " + min space + "Stash N  │"
        if len(author) > max_author:
            author = author[:max_author - 1] + "…"
        auth_p = f"│  Author   {author}"
        stash_p = f"Stash {state.stash_count}"
        pad_auth = W - len(auth_p) - len(stash_p) - 2
        l9 = auth_p + " " * max(0, pad_auth) + stash_p + " │"
        lines.append([(l9, C_DIM)])

        # L10 ─ Message ──────────────────────────────────────────────────────
        msg = state.last_msg
        max_msg_w = W - 13  # "│  Message  " + " │"
        msg = msg[:max_msg_w]
        l10 = f"│  Message  {msg}"
        pad_l10 = W - len(l10) - 1
        l10 = l10 + " " * max(0, pad_l10) + "│"
        lines.append([(l10, C_BLUE)])

        # L11 ─ Separator ────────────────────────────────────────────────────
        lines.append([(f"│{'─' * (W - 2)}│", C_DIM)])

        # L12 ─ Controls ─────────────────────────────────────────────────────
        left_ctrl  = "│  [R] Refresh  "
        right_ctrl = "  [Q] Quit │"
        pad_ctrl   = W - len(left_ctrl) - len(right_ctrl)
        l12 = left_ctrl + " " * max(0, pad_ctrl) + right_ctrl
        lines.append([(l12, C_MAG)])

        # L13 ─ Bottom border ────────────────────────────────────────────────
        l13 = f"╰{'─' * (W - 2)}╯"
        lines.append([(l13, C_CYAN)])

        draw(lines)
        stdscr.refresh()
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)
