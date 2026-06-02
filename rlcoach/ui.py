"""
RLCoach Dashboard — tkinter UI with controls, progress tracking, and match history.

Thread model:
  Tk mainloop owns the main thread.
  All pipeline threads call UIReporter helpers which enqueue UIEvents that
  are consumed by Tk's 40ms after() pump — never touch widgets directly
  from a background thread.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable, List, Optional

# ── Colour palette ─────────────────────────────────────────────────────────────
BG        = "#0D1117"   # base background
BG2       = "#161B22"   # card background
BG3       = "#21262D"   # inactive / troughs
ACCENT    = "#4FA3E0"   # RL-blue
BLUE_COL  = "#58A6FF"   # blue team colour
ORA_COL   = "#FFA657"   # orange team colour
WIN_COL   = "#3FB950"   # green
LOSS_COL  = "#F85149"   # red
DRAW_COL  = "#8B949E"   # grey
TEXT      = "#E6EDF3"   # primary text
TEXT2     = "#8B949E"   # muted text
BORDER    = "#30363D"
WARN_BG   = "#271A00"
WARN_FG   = "#E8A838"

# ── Event types ────────────────────────────────────────────────────────────────
EV_POLL_START   = "poll_start"
EV_BATCH_INIT   = "batch_init"
EV_DOWNLOAD     = "download"
EV_PARSE        = "parse"
EV_METRICS      = "metrics"
EV_RENDER       = "render"
EV_WRITE        = "write"
EV_DONE         = "done"
EV_FAILED       = "failed"
EV_POLL_DONE    = "poll_done"
EV_STATUS       = "status"
EV_HISTORY_CARD = "history_card"


@dataclass
class UIEvent:
    type: str
    message: str = ""
    replay_name: str = ""
    map_name: str = ""
    date: str = ""
    playlist: str = ""
    result: str = ""            # "W2-1", "L0-3", "D1-1" from player's perspective
    metrics_summary: dict = field(default_factory=dict)
    players_blue: list = field(default_factory=list)    # [{name, is_me, goals, shots, saves}]
    players_orange: list = field(default_factory=list)
    folder_path: str = ""
    count_done: int = 0
    count_total: int = 0
    error: str = ""


class UIReporter:
    """Thread-safe event bus. Pipeline threads call helpers; Dashboard subscribes."""

    def __init__(self):
        self._listeners: List[Callable[[UIEvent], None]] = []

    def subscribe(self, fn: Callable[[UIEvent], None]) -> None:
        self._listeners.append(fn)

    def _emit(self, ev: UIEvent) -> None:
        for fn in self._listeners:
            try:
                fn(ev)
            except Exception:
                pass

    # ── Convenience methods (any thread) ─────────────────────────────────────

    def poll_start(self):
        self._emit(UIEvent(EV_POLL_START, message="Polling PsyNet for replays…"))

    def batch_init(self, total: int):
        self._emit(UIEvent(EV_BATCH_INIT, count_total=total))

    def download(self, guid_short: str, done: int, total: int):
        self._emit(UIEvent(EV_DOWNLOAD,
                           message=f"Downloading {guid_short}…",
                           count_done=done, count_total=total))

    def parse_start(self, filename: str):
        self._emit(UIEvent(EV_PARSE, message="Parsing replay…", replay_name=filename))

    def metrics_start(self, filename: str):
        self._emit(UIEvent(EV_METRICS, message="Computing metrics…", replay_name=filename))

    def render_start(self, filename: str, n: int):
        self._emit(UIEvent(EV_RENDER,
                           message=f"Rendering {n} diagram{'s' if n != 1 else ''}…",
                           replay_name=filename))

    def write_start(self, filename: str):
        self._emit(UIEvent(EV_WRITE, message="Writing output files…", replay_name=filename))

    def replay_done(self, map_name: str, result: str, metrics_summary: dict,
                    players_blue: list, players_orange: list,
                    folder_path: str, date: str = "", playlist: str = ""):
        self._emit(UIEvent(EV_DONE,
                           map_name=map_name, result=result,
                           metrics_summary=metrics_summary,
                           players_blue=players_blue,
                           players_orange=players_orange,
                           folder_path=folder_path,
                           date=date, playlist=playlist))

    def replay_failed(self, filename: str, error: str):
        self._emit(UIEvent(EV_FAILED, replay_name=filename,
                           message=error[:120], error=error[:120]))

    def poll_done(self, n_new: int):
        msg = (f"Poll complete — {n_new} new replay(s) processed."
               if n_new else "Up to date — no new replays.")
        self._emit(UIEvent(EV_POLL_DONE, message=msg))

    def status(self, msg: str):
        self._emit(UIEvent(EV_STATUS, message=msg))


class Dashboard:
    """
    Full coaching dashboard.

    Call run() on the main thread (blocking).
    Call show() from any thread to raise the window.
    Set on_poll_now and on_upload_file callbacks before run().
    """

    STEPS = ["Download", "Parse", "Metrics", "Render", "Write"]

    def __init__(self, reporter: UIReporter, output_dir: Optional[Path] = None):
        self._reporter = reporter
        self._output_dir = output_dir
        self._queue: queue.Queue[UIEvent] = queue.Queue()
        reporter.subscribe(self._enqueue)

        self._root: Optional[tk.Tk] = None

        # Callbacks (set by caller before run())
        self.on_poll_now: Optional[Callable[[], None]] = None
        self.on_upload_file: Optional[Callable[[Path], None]] = None

        # Session counters
        self._wins = 0
        self._losses = 0
        self._session_total = 0
        self._batch_done = 0
        self._batch_total = 0
        self._busy = False

        # Match store (newest first) + filter state
        self._matches: List[dict] = []
        self._filter = "all"

    # ── Public API ────────────────────────────────────────────────────────────

    def show(self) -> None:
        if self._root:
            self._root.after(0, self._raise)

    def quit(self) -> None:
        if self._root:
            self._root.after(0, self._root.quit)

    def run(self) -> None:
        """Build window and run Tk mainloop. Blocks until quit()."""
        self._build()
        if self._output_dir:
            self._root.after(400, self._start_history_load)
        self._root.mainloop()

    # ── Internal threading ────────────────────────────────────────────────────

    def _raise(self):
        if self._root:
            self._root.deiconify()
            self._root.lift()
            self._root.focus_force()

    def _enqueue(self, ev: UIEvent) -> None:
        self._queue.put(ev)

    def _pump(self) -> None:
        try:
            while True:
                self._dispatch(self._queue.get_nowait())
        except queue.Empty:
            pass
        if self._root and self._root.winfo_exists():
            self._root.after(40, self._pump)

    def _dispatch(self, ev: UIEvent) -> None:  # noqa: C901
        t = ev.type

        if t == EV_POLL_START:
            self._set_busy(True)
            self._set_job("Polling PsyNet…", "Fetching latest match history")
            self._reset_steps()
            self._start_anim()

        elif t == EV_BATCH_INIT:
            self._batch_total = ev.count_total
            self._batch_done = 0
            self._update_batch()

        elif t == EV_DOWNLOAD:
            self._batch_done = ev.count_done
            self._batch_total = ev.count_total
            self._set_job(
                f"Downloading replay {ev.count_done + 1} of {ev.count_total}",
                ev.message,
            )
            self._activate_step(0)
            self._update_batch()

        elif t == EV_PARSE:
            self._set_job("Parsing replay…", ev.replay_name)
            self._activate_step(1)

        elif t == EV_METRICS:
            self._set_job("Computing metrics…", ev.replay_name)
            self._activate_step(2)

        elif t == EV_RENDER:
            self._set_job(ev.message, ev.replay_name)
            self._activate_step(3)

        elif t == EV_WRITE:
            self._set_job("Writing output…", ev.replay_name)
            self._activate_step(4)

        elif t in (EV_DONE, EV_HISTORY_CARD):
            live = (t == EV_DONE)
            if live:
                self._stop_anim()
                self._batch_done += 1
                self._update_batch()
                if ev.result.startswith("W"):
                    self._wins += 1
                elif ev.result.startswith("L"):
                    self._losses += 1
                self._session_total += 1
                self._update_header()
                self._reset_steps(all_done=True)

            # Deduplicate by folder_path
            fp = ev.folder_path
            if fp and any(m.get("folder_path") == fp for m in self._matches):
                return

            self._matches.insert(0, {
                "map_name":      ev.map_name,
                "date":          ev.date,
                "playlist":      ev.playlist,
                "result":        ev.result,
                "metrics":       ev.metrics_summary,
                "players_blue":  ev.players_blue,
                "players_orange": ev.players_orange,
                "folder_path":   ev.folder_path,
            })
            self._render_feed()

        elif t == EV_FAILED:
            self._stop_anim()
            self._session_total += 1
            self._update_header()
            self._matches.insert(0, {
                "map_name": ev.replay_name or "Unknown",
                "result": "ERR",
                "error": ev.error or ev.message,
                "folder_path": "",
            })
            self._render_feed()

        elif t == EV_POLL_DONE:
            self._set_busy(False)
            self._set_job("Idle — press 'Download & Parse' to check for new replays", ev.message)
            self._reset_steps()
            self._stop_anim()
            self._status_var.set(ev.message)

        elif t == EV_STATUS:
            self._status_var.set(ev.message)

    # ── Window construction ───────────────────────────────────────────────────

    def _build(self) -> None:
        root = tk.Tk()
        self._root = root
        root.title("RLCoach — Replay Analyzer")
        root.geometry("820x700")
        root.minsize(660, 540)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", root.withdraw)

        # Set window icon from app_icon.png (works in both dev and frozen builds)
        self._tk_icon = None   # keep reference to prevent GC
        try:
            from PIL import Image, ImageTk
            icon_path = Path(__file__).parent.parent / "app_icon.png"
            if icon_path.exists():
                _img = Image.open(icon_path).convert("RGBA").resize((64, 64), Image.LANCZOS)
                self._tk_icon = ImageTk.PhotoImage(_img)
                root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

        self._apply_styles()
        self._build_header(root)
        self._build_warning(root)
        self._build_controls(root)
        tk.Frame(root, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(6, 2))
        self._build_progress(root)
        tk.Frame(root, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(6, 2))
        self._build_history_header(root)
        self._build_feed(root)
        self._build_statusbar(root)

        root.after(40, self._pump)

    def _apply_styles(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        for name in ("Active.Horizontal.TProgressbar", "Batch.Horizontal.TProgressbar"):
            s.configure(name, background=ACCENT, troughcolor=BG3,
                        bordercolor=BG3, lightcolor=ACCENT, darkcolor=ACCENT,
                        thickness=7)

    def _build_header(self, parent) -> None:
        hdr = tk.Frame(parent, bg=BG)
        hdr.pack(fill="x", padx=20, pady=(14, 6))
        tk.Label(hdr, text="RLCoach",
                 bg=BG, fg=TEXT, font=("Segoe UI", 18, "bold")).pack(side="left")
        self._stat_var = tk.StringVar(value="")
        tk.Label(hdr, textvariable=self._stat_var,
                 bg=BG, fg=TEXT2, font=("Segoe UI", 10)).pack(side="right", pady=(5, 0))

    def _build_warning(self, parent) -> None:
        warn = tk.Frame(parent, bg=WARN_BG)
        warn.pack(fill="x", padx=16, pady=(0, 6))
        inner = tk.Frame(warn, bg=WARN_BG, padx=14, pady=8)
        inner.pack(fill="x")
        tk.Label(
            inner,
            text="⚠   Do not download or parse replays while actively playing Rocket League"
                 " — the API connection can disconnect you from game servers.",
            bg=WARN_BG, fg=WARN_FG,
            font=("Segoe UI", 9),
            wraplength=760, justify="left", anchor="w",
        ).pack(fill="x")

    def _build_controls(self, parent) -> None:
        ctrl = tk.Frame(parent, bg=BG)
        ctrl.pack(fill="x", padx=16, pady=(0, 2))

        self._btn_poll = tk.Button(
            ctrl,
            text="▶   Download & Parse Latest Replays",
            bg=ACCENT, fg=BG,
            font=("Segoe UI", 10, "bold"),
            padx=18, pady=9,
            relief="flat", cursor="hand2",
            activebackground="#6BB8F0", activeforeground=BG,
            command=self._do_poll_now,
        )
        self._btn_poll.pack(side="left", padx=(0, 10))

        self._btn_upload = tk.Button(
            ctrl,
            text="📂   Upload .replay File",
            bg=BG3, fg=TEXT,
            font=("Segoe UI", 10),
            padx=18, pady=9,
            relief="flat", cursor="hand2",
            activebackground="#2D3340", activeforeground=TEXT,
            command=self._do_upload,
        )
        self._btn_upload.pack(side="left")

    def _build_progress(self, parent) -> None:
        card = tk.Frame(parent, bg=BG2)
        card.pack(fill="x", padx=16)
        inner = tk.Frame(card, bg=BG2, padx=16, pady=12)
        inner.pack(fill="x")

        self._job_title_var = tk.StringVar(
            value="Ready — press 'Download & Parse' to fetch your latest replays")
        self._job_sub_var = tk.StringVar(value="")

        tk.Label(inner, textvariable=self._job_title_var,
                 bg=BG2, fg=TEXT, font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(inner, textvariable=self._job_sub_var,
                 bg=BG2, fg=TEXT2, font=("Segoe UI", 9),
                 anchor="w").pack(fill="x", pady=(2, 8))

        # Step pills
        pills_row = tk.Frame(inner, bg=BG2)
        pills_row.pack(fill="x", pady=(0, 8))
        self._pills: List[tk.Label] = []
        for i, step in enumerate(self.STEPS):
            if i > 0:
                tk.Label(pills_row, text="›", bg=BG2, fg=TEXT2,
                         font=("Segoe UI", 11)).pack(side="left", padx=4)
            pill = tk.Label(pills_row, text=step,
                            bg=BG3, fg=TEXT2,
                            font=("Segoe UI", 9, "bold"),
                            padx=12, pady=5)
            pill.pack(side="left")
            self._pills.append(pill)

        # Animated progress bar
        self._prog = ttk.Progressbar(inner, style="Active.Horizontal.TProgressbar",
                                      mode="determinate")
        self._prog.pack(fill="x")

        # Batch progress row
        batch_row = tk.Frame(inner, bg=BG2)
        batch_row.pack(fill="x", pady=(8, 0))
        self._batch_var = tk.StringVar(value="")
        tk.Label(batch_row, textvariable=self._batch_var,
                 bg=BG2, fg=TEXT2, font=("Segoe UI", 9),
                 width=20, anchor="w").pack(side="left")
        self._batch_bar = ttk.Progressbar(
            batch_row, style="Batch.Horizontal.TProgressbar",
            mode="determinate", maximum=20)
        self._batch_bar.pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _build_history_header(self, parent) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=16, pady=(2, 4))

        tk.Label(row, text="MATCH HISTORY",
                 bg=BG, fg=TEXT2, font=("Segoe UI", 9, "bold")).pack(side="left")

        # Filter tabs on the right
        filter_frame = tk.Frame(row, bg=BG)
        filter_frame.pack(side="right")
        self._filter_btns: dict = {}
        for key, label in [("all", "All"), ("wins", "Wins"), ("losses", "Losses")]:
            btn = tk.Label(filter_frame, text=label,
                           bg=BG3, fg=TEXT2,
                           font=("Segoe UI", 9),
                           padx=12, pady=3, cursor="hand2")
            btn.pack(side="left", padx=(0, 3))
            btn.bind("<Button-1>", lambda e, k=key: self._set_filter(k))
            self._filter_btns[key] = btn
        self._set_filter("all", render=False)

    def _build_feed(self, parent) -> None:
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=16)

        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)

        self._feed = tk.Frame(self._canvas, bg=BG)
        self._feed.bind("<Configure>",
                        lambda e: self._canvas.configure(
                            scrollregion=self._canvas.bbox("all")))

        cwin = self._canvas.create_window((0, 0), window=self._feed, anchor="nw")
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(cwin, width=e.width))
        self._canvas.bind_all(
            "<MouseWheel>",
            lambda e: self._canvas.yview_scroll(int(-1 * e.delta / 120), "units"),
        )

        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

    def _build_statusbar(self, parent) -> None:
        bar = tk.Frame(parent, bg=BG3)
        bar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self._status_var,
                 bg=BG3, fg=TEXT2, font=("Segoe UI", 9),
                 pady=5, padx=12, anchor="w").pack(side="left")

    # ── Button actions ────────────────────────────────────────────────────────

    def _do_poll_now(self):
        if self.on_poll_now and not self._busy:
            self.on_poll_now()

    def _do_upload(self):
        if self._busy:
            return
        path_str = filedialog.askopenfilename(
            title="Select Rocket League Replay File",
            filetypes=[("Rocket League Replay", "*.replay"), ("All files", "*.*")],
        )
        if path_str and self.on_upload_file:
            self.on_upload_file(Path(path_str))

    # ── Filter ────────────────────────────────────────────────────────────────

    def _set_filter(self, key: str, render: bool = True) -> None:
        self._filter = key
        for k, btn in self._filter_btns.items():
            btn.config(bg=ACCENT if k == key else BG3,
                       fg=BG if k == key else TEXT2)
        if render:
            self._render_feed()

    # ── Feed rendering ────────────────────────────────────────────────────────

    def _render_feed(self) -> None:
        """Clear and rebuild the visible match cards."""
        for w in self._feed.winfo_children():
            w.destroy()

        shown = 0
        for m in self._matches:    # already newest-first
            r = m.get("result", "")
            if self._filter == "wins"   and not r.startswith("W"):
                continue
            if self._filter == "losses" and not r.startswith("L"):
                continue
            if m.get("error"):
                self._draw_error_card(m)
            else:
                self._draw_match_card(m)
            shown += 1

        if shown == 0:
            tk.Label(self._feed,
                     text="No matches yet — press 'Download & Parse' to get started.",
                     bg=BG, fg=TEXT2, font=("Segoe UI", 10),
                     pady=20).pack()

        if self._root:
            self._root.after(30, lambda: self._canvas.yview_moveto(0.0))

    def _draw_match_card(self, m: dict) -> None:
        result  = m.get("result", "")
        is_win  = result.startswith("W")
        is_draw = result.startswith("D")
        accent  = WIN_COL if is_win else (DRAW_COL if is_draw else LOSS_COL)

        # Outer card
        card = tk.Frame(self._feed, bg=BG2)
        card.pack(fill="x", pady=(0, 4))

        # Left accent stripe
        tk.Frame(card, bg=accent, width=5).pack(side="left", fill="y")

        body = tk.Frame(card, bg=BG2, padx=14, pady=10)
        body.pack(side="left", fill="both", expand=True)

        # ── Row 1: Map name + date + result badge ─────────────────────────────
        row1 = tk.Frame(body, bg=BG2)
        row1.pack(fill="x")

        map_clean = (
            (m.get("map_name") or "Unknown Map")
            .replace("_P", "").replace("_GRS", "").replace("_Standard", "")
            .replace("_", " ").strip()
        )
        tk.Label(row1, text=map_clean,
                 bg=BG2, fg=TEXT, font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(side="left")

        if m.get("date"):
            tk.Label(row1, text=f"  {m['date']}",
                     bg=BG2, fg=TEXT2, font=("Segoe UI", 9)).pack(side="left", pady=(2, 0))

        # Result badge (right-aligned)
        badge = tk.Label(row1, text=f"  {result}  ",
                         bg=accent, fg=BG, font=("Segoe UI", 10, "bold"),
                         padx=2, pady=2)
        badge.pack(side="right")

        # ── Row 2: Teams ──────────────────────────────────────────────────────
        blues   = m.get("players_blue", [])
        oranges = m.get("players_orange", [])

        if blues or oranges:
            teams = tk.Frame(body, bg=BG2)
            teams.pack(fill="x", pady=(6, 0))

            if blues:
                names = _fmt_players(blues)
                tk.Label(teams, text=f"🔵  {names}",
                         bg=BG2, fg=BLUE_COL, font=("Segoe UI", 9),
                         anchor="w").pack(fill="x")

            if oranges:
                names = _fmt_players(oranges)
                tk.Label(teams, text=f"🟠  {names}",
                         bg=BG2, fg=ORA_COL, font=("Segoe UI", 9),
                         anchor="w").pack(fill="x")

        # ── Row 3: Metrics pill row + Open Folder button ──────────────────────
        bot = tk.Frame(body, bg=BG2)
        bot.pack(fill="x", pady=(6, 0))

        ms = m.get("metrics", {})
        pills: List[str] = []
        if "avg_boost" in ms:
            pills.append(f"Boost {ms['avg_boost']}%")
        if "def_third_pct" in ms:
            pills.append(f"Def {ms['def_third_pct']}%")
        if "off_third_pct" in ms:
            pills.append(f"Off {ms['off_third_pct']}%")
        dc = ms.get("double_commits", 0)
        if dc:
            pills.append(f"⚠  {dc} double-commit{'s' if dc > 1 else ''}")

        if pills:
            tk.Label(bot, text="  ·  ".join(pills),
                     bg=BG2, fg=TEXT2, font=("Segoe UI", 9),
                     anchor="w").pack(side="left")

        folder = m.get("folder_path", "")
        if folder and Path(folder).exists():
            btn = tk.Label(bot, text=" 📂  Open Folder ",
                           bg=BG3, fg=TEXT2,
                           font=("Segoe UI", 9), padx=4, pady=2, cursor="hand2")
            btn.pack(side="right")
            btn.bind("<Button-1>", lambda e, p=folder: _open_folder(p))
            btn.bind("<Enter>",    lambda e, b=btn: b.config(fg=TEXT,  bg="#2D3340"))
            btn.bind("<Leave>",    lambda e, b=btn: b.config(fg=TEXT2, bg=BG3))

    def _draw_error_card(self, m: dict) -> None:
        card = tk.Frame(self._feed, bg=BG2)
        card.pack(fill="x", pady=(0, 4))
        tk.Frame(card, bg=LOSS_COL, width=5).pack(side="left", fill="y")
        body = tk.Frame(card, bg=BG2, padx=14, pady=10)
        body.pack(side="left", fill="both", expand=True)
        tk.Label(body, text=f"⚠  Parse failed — {m.get('map_name', '?')}",
                 bg=BG2, fg=LOSS_COL, font=("Segoe UI", 10, "bold"),
                 anchor="w").pack(fill="x")
        err = m.get("error", "")
        if err:
            tk.Label(body, text=err,
                     bg=BG2, fg=TEXT2, font=("Segoe UI", 9),
                     anchor="w").pack(fill="x", pady=(2, 0))

    # ── UI state helpers ──────────────────────────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._btn_poll.config(
            state="disabled" if busy else "normal",
            bg="#5A7A90" if busy else ACCENT,
        )
        self._btn_upload.config(state="disabled" if busy else "normal")

    def _set_job(self, title: str, sub: str) -> None:
        self._job_title_var.set(title)
        self._job_sub_var.set(sub)

    def _start_anim(self) -> None:
        self._prog.config(mode="indeterminate")
        self._prog.start(10)

    def _stop_anim(self) -> None:
        self._prog.stop()
        self._prog.config(mode="determinate", value=100)

    def _reset_steps(self, all_done: bool = False) -> None:
        for pill in self._pills:
            pill.config(bg=WIN_COL if all_done else BG3,
                        fg=BG if all_done else TEXT2)

    def _activate_step(self, idx: int) -> None:
        for i, pill in enumerate(self._pills):
            if i < idx:
                pill.config(bg=WIN_COL, fg=BG)
            elif i == idx:
                pill.config(bg=ACCENT, fg=BG)
            else:
                pill.config(bg=BG3, fg=TEXT2)
        self._prog.stop()
        self._prog.config(mode="indeterminate")
        self._prog.start(10)

    def _update_batch(self) -> None:
        t = max(self._batch_total, 1)
        self._batch_bar.config(maximum=t, value=self._batch_done)
        self._batch_var.set(f"{self._batch_done} / {self._batch_total} replays")

    def _update_header(self) -> None:
        n = self._wins + self._losses
        wr = f"  ·  {int(100 * self._wins / n)}% WR" if n > 0 else ""
        self._stat_var.set(
            f"{self._wins}W  {self._losses}L{wr}  ·  {self._session_total} this session"
        )

    # ── History loading ───────────────────────────────────────────────────────

    def _start_history_load(self) -> None:
        threading.Thread(target=self._load_history, daemon=True).start()

    def _load_history(self) -> None:
        if not self._output_dir or not self._output_dir.exists():
            return
        cards = []
        for folder in sorted(self._output_dir.iterdir()):
            if not folder.is_dir():
                continue
            json_file = folder / "match.json"
            if not json_file.exists():
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                card = _json_to_card(data, folder)
                if card:
                    cards.append(card)
            except Exception:
                pass
        # Oldest folder first; inserting at index 0 makes newest appear at top
        for card_kwargs in cards:
            self._queue.put(UIEvent(EV_HISTORY_CARD, **card_kwargs))


# ── Module-level helpers ───────────────────────────────────────────────────────

def _fmt_players(players: list) -> str:
    parts = []
    for p in players:
        name = p.get("name", "?")
        tag  = " (you)" if p.get("is_me") else ""
        g    = p.get("goals", 0)
        parts.append(f"{name}{tag}  G:{g}")
    return "    ".join(parts)


def _open_folder(path: str) -> None:
    try:
        os.startfile(path)
    except Exception:
        pass


def _json_to_card(data: dict, folder: Path) -> Optional[dict]:
    """Parse match.json into UIEvent keyword-arg dict."""
    try:
        res   = data.get("result", {})
        blue  = int(res.get("blue_score", 0))
        orange = int(res.get("orange_score", 0))

        players = data.get("players", [])
        me = next((p for p in players if p.get("is_me")), None)
        me_team = (me.get("team", "blue") if me else "blue")

        if me_team == "orange":
            my_score, opp_score = orange, blue
        else:
            my_score, opp_score = blue, orange

        if my_score > opp_score:
            result = f"W{my_score}-{opp_score}"
        elif opp_score > my_score:
            result = f"L{my_score}-{opp_score}"
        else:
            result = f"D{my_score}-{opp_score}"

        blues   = [_player_dict(p) for p in players if p.get("team") == "blue"]
        oranges = [_player_dict(p) for p in players if p.get("team") == "orange"]

        ms: dict = {}
        if me:
            pos = me.get("positioning") or {}
            bst = me.get("boost") or {}
            if pos.get("def_third_pct") is not None:
                ms["def_third_pct"] = pos["def_third_pct"]
            if pos.get("off_third_pct") is not None:
                ms["off_third_pct"] = pos["off_third_pct"]
            if bst.get("avg_boost") is not None:
                ms["avg_boost"] = bst["avg_boost"]
        dc = len(data.get("team_metrics", {}).get("double_commit_events", []))
        if dc:
            ms["double_commits"] = dc

        return dict(
            map_name=str(data.get("map", "Unknown")),
            date=str(data.get("date", "")),
            playlist=str(data.get("playlist", "")),
            result=result,
            metrics_summary=ms,
            players_blue=blues,
            players_orange=oranges,
            folder_path=str(folder),
        )
    except Exception:
        return None


def _player_dict(p: dict) -> dict:
    core = p.get("core") or {}
    return {
        "name":  p.get("name", "Unknown"),
        "is_me": bool(p.get("is_me")),
        "goals": int(core.get("goals", 0)),
        "shots": int(core.get("shots", 0)),
        "saves": int(core.get("saves", 0)),
        "score": int(core.get("score", 0)),
    }
