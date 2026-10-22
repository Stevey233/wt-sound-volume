#!/usr/bin/env python3
"""Native desktop controls for offline sound bank gain edits."""

import json
import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from bank_volume import (
    GROUP_INFO,
    GROUPS,
    OUTPUT_ROOT,
    SAMPLES,
    Scan,
    __version__,
    export,
    find_game_installs,
    gains_checked,
)

BG = "#171c18"
PANEL = "#222923"
TEXT = "#eef1e8"
MUTED = "#aab6a7"
DIM = "#66725f"
ACCENT = "#d4eaa0"
CUT = "#e9b872"
TRACK = "#111711"
VOICE_GROUPS = {"crew_ground", "crew_naval", "crew_common", "radio_chat"}


def enable_dpi_awareness():
    """Ask Windows for sharp text instead of stretching a 96 DPI window."""
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.OleDLL("shcore").SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def work_area(root):
    """Return the screen area outside the Windows taskbar as left, top, width, height."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class GainSlider(tk.Canvas):
    """A 0 to 400% slider with 100% in the middle, so cuts get half of the track."""

    def __init__(self, parent, px, command):
        super().__init__(parent, height=px(30), bg=PANEL, highlightthickness=0, borderwidth=0, takefocus=1)
        self.px = px
        self.command = command
        self.percent = 100
        self.enabled = False
        for sequence in ("<Button-1>", "<B1-Motion>"):
            self.bind(sequence, self.drag)
        self.bind("<Double-Button-1>", lambda event: self.step(None))
        for sequence, delta in (("<Left>", -1), ("<Right>", 1), ("<Shift-Left>", -10), ("<Shift-Right>", 10)):
            self.bind(sequence, lambda event, delta=delta: self.step(delta))
        for sequence in ("<Configure>", "<FocusIn>", "<FocusOut>"):
            self.bind(sequence, lambda event: self.draw())

    @staticmethod
    def position(percent):
        return percent / 200 if percent <= 100 else 0.5 + (percent - 100) / 600

    @staticmethod
    def value_at(position):
        return position * 200 if position <= 0.5 else 100 + (position - 0.5) * 600

    def ends(self):
        pad = self.px(10)
        return pad, max(pad + 1, self.winfo_width() - pad)

    def drag(self, event):
        if self.enabled:
            self.focus_set()
            left, right = self.ends()
            self.command(round(self.value_at(min(1, max(0, (event.x - left) / (right - left))))))

    def step(self, delta):
        """Move by delta percent, or back to 100% when delta is None."""
        if self.enabled:
            self.command(100 if delta is None else min(400, max(0, self.percent + delta)))
            return "break"
        return None

    def set(self, percent):
        self.percent = percent
        self.draw()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "", takefocus=1 if enabled else 0)
        self.draw()

    def draw(self):
        self.delete("all")
        left, right = self.ends()
        middle = self.winfo_height() // 2
        centre = (left + right) / 2
        x = left + (right - left) * self.position(self.percent)
        width = self.px(6)
        self.create_line(left, middle, right, middle, width=width, fill=TRACK, capstyle="round")
        if self.enabled and self.percent != 100:
            self.create_line(centre, middle, x, middle, width=width, fill=CUT if self.percent < 100 else ACCENT, capstyle="round")
        self.create_line(centre, middle - self.px(9), centre, middle + self.px(9), width=max(1, self.px(2)), fill=DIM)
        radius = self.px(8)
        focused = self.enabled and self.focus_get() is self
        self.create_oval(x - radius, middle - radius, x + radius, middle + radius,
                         fill=TEXT if self.enabled else DIM, outline=ACCENT if focused else PANEL, width=max(1, self.px(2)))


class GainRow:
    def __init__(self, parent, key, changed, px):
        self.key = key
        self.changed = changed
        self.percent = 100
        self.available = False
        self.enabled = False
        info = GROUP_INFO[key]
        self.description = info[2]
        self.frame = tk.Frame(parent, bg=PANEL)
        # The coloured strip marks rows that differ from the pack.
        self.marker = tk.Frame(self.frame, bg=PANEL, width=px(4))
        self.marker.pack(side="left", fill="y")
        body = ttk.Frame(self.frame, style="Card.TFrame", padding=(px(12), px(8), px(12), px(8)))
        body.pack(side="left", fill="both", expand=True)
        body.columnconfigure(0, minsize=px(350))
        body.columnconfigure(1, weight=1)
        text = ttk.Frame(body, style="Card.TFrame")
        text.grid(row=0, column=0, sticky="w")
        title = ttk.Frame(text, style="Card.TFrame")
        title.pack(anchor="w")
        ttk.Label(title, text=info[1], style="CardTitle.TLabel").pack(side="left")
        self.count = ttk.Label(title, style="CardMuted.TLabel")
        self.count.pack(side="left", padx=(px(8), 0))
        ttk.Label(text, text=self.description, style="CardMuted.TLabel", wraplength=px(340)).pack(anchor="w", pady=(px(2), 0))
        self.slider = GainSlider(body, px, self.set_value)
        self.slider.grid(row=0, column=1, sticky="ew", padx=(px(8), px(14)))
        self.value = tk.StringVar(value="100")
        self.spin = ttk.Spinbox(body, from_=0, to=400, increment=1, textvariable=self.value, width=4, command=self.commit, justify="right")
        self.spin.grid(row=0, column=2)
        self.spin.bind("<FocusOut>", self.commit)
        self.spin.bind("<Return>", self.commit)
        ttk.Label(body, text="%", style="CardMuted.TLabel").grid(row=0, column=3, padx=(px(4), px(8)))
        self.db = ttk.Label(body, text="原始", width=9, anchor="e", style="Gain.TLabel")
        self.db.grid(row=0, column=4)
        self.reset_button = ttk.Button(body, text="重置", style="Small.TButton", command=lambda: self.set_value(100))
        self.reset_button.grid(row=0, column=5, sticky="e", padx=(px(10), 0))
        self.set_enabled(False)

    def set_count(self, count):
        unit = "条混音总线" if self.key in VOICE_GROUPS else "个事件"
        self.available = count > 0
        self.count.configure(text=f"{count} {unit}" if count else "")

    def set_value(self, value, notify=True):
        value = min(400, max(0, round(float(value))))
        changed = value != self.percent
        self.percent = value
        self.value.set(str(value))
        self.slider.set(value)
        self.marker.configure(bg=PANEL if value == 100 else CUT if value < 100 else ACCENT)
        if value == 100:
            text, style = "原始", "Gain.TLabel"
        elif value == 0:
            text, style = "大幅压低", "GainCut.TLabel"
        else:
            text, style = f"{20 * math.log10(value / 100):+.2f} dB", "GainCut.TLabel" if value < 100 else "GainBoost.TLabel"
        self.db.configure(text=text, style=style)
        self.refresh_reset()
        if notify and changed:
            self.changed()

    def commit(self, event=None):
        try:
            value = float(self.value.get())
            if not math.isfinite(value):
                raise ValueError
        except ValueError:
            value = self.percent
        self.set_value(value)

    def set_enabled(self, enabled):
        self.enabled = enabled and self.available
        self.slider.set_enabled(self.enabled)
        self.spin.configure(state="normal" if self.enabled else "disabled")
        self.refresh_reset()

    def refresh_reset(self):
        # The hidden style keeps the column width, so rows stay aligned.
        visible = self.enabled and self.percent != 100
        self.reset_button.configure(style="Small.TButton" if visible else "Hidden.TButton", state="normal" if visible else "disabled")


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"战争雷霆音效包音量工具 {__version__}")
        # Windows reports the display scale only to DPI-aware programs, so pixel sizes follow it there.
        self.ui_scale = max(1.0, root.winfo_fpixels("1i") / 96) if sys.platform == "win32" else 1.0
        self.root.geometry(self.fit_geometry(1120, 860, 900, 640))
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.queue = queue.SimpleQueue()
        self.scan = None
        self.busy = False
        self.result = None
        self.current_source = None
        self.rows = {}
        self.tabs = {}
        self.tab_info = {}
        self.tab_empty = {}
        self.canvases = {}
        self.game_installs = find_game_installs()
        self.setup_style()
        self.build()
        self.poll_job = self.root.after(100, self.poll)

    def px(self, value):
        return round(value * self.ui_scale)

    def fit_geometry(self, width, height, min_width, min_height, window=None):
        """Size a window for the display scale and keep it inside the work area."""
        window = window or self.root
        left, top, area_width, area_height = work_area(self.root)
        # The margin leaves room for the title bar and window border.
        width = min(self.px(width), area_width - self.px(16))
        height = min(self.px(height), area_height - self.px(48))
        window.minsize(min(self.px(min_width), width), min(self.px(min_height), height))
        if sys.platform != "win32":
            return f"{width}x{height}"
        return f"{width}x{height}+{left + (area_width - width) // 2}+{top + max(0, (area_height - height - self.px(48)) // 2)}"

    def setup_style(self):
        families = font.families()
        family = next((f for f in ("Noto Sans CJK SC", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "DejaVu Sans") if f in families), "TkDefaultFont")
        # Windows gives entries and table headings their own system font.
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont"):
            font.nametofont(name).configure(family=family, size=10)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, bordercolor="#455143", lightcolor=BG, darkcolor=BG)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=(family, 17, "bold"))
        style.configure("Done.TLabel", foreground=ACCENT, font=(family, 10, "bold"))
        style.configure("CardTitle.TLabel", background=PANEL, font=(family, 11, "bold"))
        style.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED, font=(family, 9))
        style.configure("Gain.TLabel", background=PANEL, foreground=MUTED, font=(family, 10))
        style.configure("GainCut.TLabel", background=PANEL, foreground=CUT, font=(family, 10))
        style.configure("GainBoost.TLabel", background=PANEL, foreground=ACCENT, font=(family, 10))
        style.configure("EmptyTitle.TLabel", background=PANEL, font=(family, 15, "bold"))
        style.configure("TButton", padding=(12, 7), background="#354132", foreground=TEXT)
        style.map("TButton", background=[("active", "#46553f"), ("disabled", "#252c25")], foreground=[("disabled", "#758170")])
        style.configure("Small.TButton", padding=(8, 3), font=(family, 9))
        style.map("Small.TButton", background=[("active", "#46553f"), ("disabled", PANEL)], foreground=[("disabled", DIM)])
        style.configure("Hidden.TButton", padding=(8, 3), font=(family, 9), background=PANEL, foreground=PANEL, bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
        style.map("Hidden.TButton", background=[("disabled", PANEL)], foreground=[("disabled", PANEL)])
        style.configure("Primary.TButton", background=ACCENT, foreground="#17220f", font=(family, 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#e4f5bc"), ("disabled", "#3c4733")], foreground=[("disabled", "#89957a")])
        style.configure("TEntry", fieldbackground="#111711", foreground=TEXT, padding=7, insertcolor=TEXT)
        style.configure("TSpinbox", fieldbackground="#141b14", foreground=TEXT, padding=5, arrowsize=self.px(13), insertcolor=TEXT)
        style.map("TSpinbox", fieldbackground=[("disabled", "#282f28")], foreground=[("disabled", "#74816f")])
        style.configure("TCombobox", fieldbackground="#141b14", foreground=TEXT, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", "#141b14")], foreground=[("readonly", TEXT)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(13, 9), background="#293328", foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=self.px(28))
        style.configure("Treeview.Heading", background="#354132", foreground=TEXT)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL)
        self.family = family

    def build(self):
        outer = ttk.Frame(self.root, padding=(24, 18))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="音效包音量", style="Title.TLabel").pack(side="left")

        source_frame = ttk.Frame(outer)
        source_frame.grid(row=1, column=0, sticky="ew")
        source_frame.columnconfigure(0, weight=1)
        self.source = tk.StringVar()
        self.source_entry = ttk.Entry(source_frame, textvariable=self.source)
        self.source_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.source_entry.bind("<Return>", lambda event: self.start_scan())
        self.choose_zip = ttk.Button(source_frame, text="选择 ZIP", command=self.browse_zip)
        self.choose_zip.grid(row=0, column=1, padx=(0, 8))
        self.choose_dir = ttk.Button(source_frame, text="选择目录", command=self.browse_dir)
        self.choose_dir.grid(row=0, column=2, padx=(0, 8))
        self.choose_game = ttk.Button(source_frame, text="游戏目录", command=self.browse_game)
        self.choose_game.grid(row=0, column=3, padx=(0, 8))
        self.scan_button = ttk.Button(source_frame, text="扫描", style="Primary.TButton", command=self.start_scan)
        self.scan_button.grid(row=0, column=4)
        examples_frame = ttk.Frame(source_frame)
        examples_frame.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        self.examples = sorted(SAMPLES.glob("*.zip"))
        self.example = ttk.Combobox(examples_frame, values=[p.stem for p in self.examples], state="readonly", width=44)
        self.example.bind("<<ComboboxSelected>>", self.select_example)
        # Packs in samples/ next to the program show up here.
        if self.examples:
            ttk.Label(examples_frame, text="示例包", style="Muted.TLabel").pack(side="left", padx=(0, 10))
            self.example.pack(side="left")
            self.example.current(0)
            self.source.set(str(self.examples[0]))
        self.summary = ttk.Label(examples_frame, text="", style="Muted.TLabel")
        self.summary.pack(side="right")
        self.source.trace_add("write", self.source_changed)

        main = ttk.Frame(outer)
        main.grid(row=3, column=0, sticky="nsew", pady=(14, 0))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        self.build_empty(main)
        self.build_editor(main)

        footer = ttk.Frame(outer)
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="")
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel", wraplength=self.px(640)).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=self.px(120))
        self.progress.grid(row=0, column=1, padx=(12, 12))
        self.progress.grid_remove()
        self.export_button = ttk.Button(footer, text="导出完整新包", style="Primary.TButton", command=self.start_export)
        self.export_button.grid(row=0, column=2, sticky="e")
        self.result_frame = ttk.Frame(footer)
        self.result_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.result_frame.columnconfigure(1, weight=1)
        ttk.Label(self.result_frame, text="已导出", style="Done.TLabel").grid(row=0, column=0, padx=(0, 10))
        self.result_path = tk.StringVar(value="")
        self.result_entry = ttk.Entry(self.result_frame, textvariable=self.result_path, state="readonly")
        self.result_entry.grid(row=0, column=1, sticky="ew")
        self.open_button = ttk.Button(self.result_frame, text="打开输出目录", command=self.open_output)
        self.open_button.grid(row=0, column=2, padx=(8, 0))
        self.copy_button = ttk.Button(self.result_frame, text="复制 ZIP 路径", command=self.copy_path)
        self.copy_button.grid(row=0, column=3, padx=(8, 0))
        self.result_frame.grid_remove()
        self.show_main()
        self.refresh_controls()

    def build_empty(self, parent):
        self.empty = ttk.Frame(parent, style="Card.TFrame")
        self.empty.grid(row=0, column=0, sticky="nsew")
        inner = ttk.Frame(self.empty, style="Card.TFrame")
        inner.place(relx=0.5, rely=0.45, anchor="center")
        self.empty_title = ttk.Label(inner, text="选择音效包或游戏目录", style="EmptyTitle.TLabel")
        self.empty_title.pack(pady=(0, 18))
        buttons = ttk.Frame(inner, style="Card.TFrame")
        buttons.pack()
        self.empty_zip = ttk.Button(buttons, text="选择 ZIP", command=self.browse_zip)
        self.empty_zip.pack(side="left", padx=4)
        self.empty_dir = ttk.Button(buttons, text="选择目录", command=self.browse_dir)
        self.empty_dir.pack(side="left", padx=4)
        self.empty_game = ttk.Button(buttons, text="游戏目录", command=self.browse_game)
        self.empty_game.pack(side="left", padx=4)
        # A game found in the usual places gets the main button, so players without mods can start at once.
        self.empty_detected = ttk.Button(buttons, text="扫描游戏原版音效", style="Primary.TButton", command=self.scan_detected_game)
        if self.game_installs:
            self.empty_detected.pack(side="left", padx=4)
        self.empty_scan = ttk.Button(buttons, text="扫描当前路径", style="TButton" if self.game_installs else "Primary.TButton", command=self.start_scan)
        self.empty_progress = ttk.Progressbar(inner, mode="indeterminate", length=self.px(240))

    def build_editor(self, parent):
        self.editor = ttk.Frame(parent)
        self.editor.grid(row=0, column=0, sticky="nsew")
        self.editor.columnconfigure(0, weight=1)
        self.editor.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(self.editor)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.reset_button = ttk.Button(toolbar, text="全部恢复 100%", command=self.reset)
        self.reset_button.pack(side="right")
        self.catalog_button = ttk.Button(toolbar, text="事件清单", command=self.show_catalog)
        self.catalog_button.pack(side="right", padx=(0, 8))
        self.load_button = ttk.Button(toolbar, text="读取预设", command=self.load_preset)
        self.load_button.pack(side="right", padx=(0, 8))
        self.save_button = ttk.Button(toolbar, text="保存预设", command=self.save_preset)
        self.save_button.pack(side="right", padx=(0, 8))

        self.notebook = ttk.Notebook(self.editor)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.bulk_widgets = []
        for tab_name in dict.fromkeys(info[0] for info in GROUP_INFO.values()):
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text=tab_name)
            self.tabs[tab_name] = tab
            bar = ttk.Frame(tab, padding=(4, 10, 4, 4))
            bar.pack(fill="x")
            self.tab_info[tab_name] = ttk.Label(bar, style="Muted.TLabel")
            self.tab_info[tab_name].pack(side="left")
            bulk_value = tk.StringVar(value="50")
            restore = ttk.Button(bar, text="本页恢复 100%", style="Small.TButton", command=lambda t=tab_name: self.set_tab(t, 100))
            restore.pack(side="right")
            apply = ttk.Button(bar, text="应用", style="Small.TButton", command=lambda t=tab_name, v=bulk_value: self.set_tab(t, v.get()))
            apply.pack(side="right", padx=(0, 12))
            ttk.Label(bar, text="%", style="Muted.TLabel").pack(side="right", padx=(4, 8))
            spin = ttk.Spinbox(bar, from_=0, to=400, increment=5, textvariable=bulk_value, width=4, justify="right")
            spin.pack(side="right")
            ttk.Label(bar, text="本页全部设为", style="Muted.TLabel").pack(side="right", padx=(0, 8))
            self.bulk_widgets += [restore, apply, spin]
            body = ttk.Frame(tab)
            body.pack(fill="both", expand=True)
            canvas = tk.Canvas(body, bg=BG, highlightthickness=0, borderwidth=0)
            self.canvases[str(tab)] = canvas
            scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
            content = ttk.Frame(canvas)
            window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind("<Configure>", lambda event, c=canvas: c.configure(scrollregion=c.bbox("all")))
            canvas.bind("<Configure>", lambda event, c=canvas, w=window: c.itemconfigure(w, width=event.width))
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            self.tab_empty[tab_name] = ttk.Label(content, text="这个包里没有本页的声音。", style="Muted.TLabel", padding=(4, 16))
            for key, info in GROUP_INFO.items():
                if info[0] == tab_name:
                    self.rows[key] = GainRow(content, key, self.settings_changed, self.px)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind(sequence, self.scroll_current_tab, add="+")

    def show_main(self):
        """Show the editor after a scan and the start page before one."""
        if self.scan is None:
            self.editor.grid_remove()
            self.empty.grid()
            source = self.source.get().strip()
            self.empty_title.configure(text="正在扫描" if self.busy else "选择音效包或游戏目录")
            self.empty_scan.pack_forget()
            if source and not self.busy:
                self.empty_scan.pack(side="left", padx=4)
        else:
            self.empty.grid_remove()
            self.editor.grid()
        if self.busy and self.scan is None:
            self.empty_progress.pack(pady=(18, 0))
            self.empty_progress.start(12)
        else:
            self.empty_progress.stop()
            self.empty_progress.pack_forget()

    def layout_rows(self):
        """Show only the categories found in the scanned pack."""
        for tab_name in self.tabs:
            rows = [row for row in self.rows.values() if GROUP_INFO[row.key][0] == tab_name]
            for row in rows:
                row.frame.pack_forget()
            self.tab_empty[tab_name].pack_forget()
            shown = [row for row in rows if row.available]
            for row in shown:
                row.frame.pack(fill="x", pady=(self.px(6), 0), padx=(0, 6))
            if not shown:
                self.tab_empty[tab_name].pack(anchor="w")

    def refresh_summary(self):
        """Count adjusted categories on each tab and on the export button."""
        total = 0
        for tab_name, tab in self.tabs.items():
            rows = [row for row in self.rows.values() if GROUP_INFO[row.key][0] == tab_name]
            shown = [row for row in rows if row.available]
            changed = sum(row.percent != 100 for row in shown)
            total += changed
            self.notebook.tab(tab, text=f"{tab_name}  ·  {changed}" if changed else tab_name)
            parts = [f"{len(shown)} 个类别"]
            if changed:
                parts.append(f"{changed} 个已调整")
            if len(rows) > len(shown):
                parts.append(f"{len(rows) - len(shown)} 个包里没有，已隐藏")
            self.tab_info[tab_name].configure(text="，".join(parts))
        label = "导出 mod 包" if self.scan and self.scan.game_version else "导出完整新包"
        self.export_button.configure(text=f"{label}  ·  {total} 项调整" if total else label)

    def source_changed(self, *args):
        self.scan = None
        self.current_source = None
        self.clear_result()
        self.summary.configure(text="")
        for row in self.rows.values():
            row.available = False
        self.show_main()
        self.refresh_controls()

    def clear_result(self):
        self.result = None
        self.result_path.set("")
        self.result_frame.grid_remove()

    def scroll_current_tab(self, event):
        tab = self.notebook.select()
        if str(event.widget).startswith(tab + "."):
            direction = -1 if event.num == 4 or getattr(event, "delta", 0) > 0 else 1
            self.canvases[tab].yview_scroll(direction, "units")
            return "break"
        return None

    def browse_zip(self):
        path = filedialog.askopenfilename(parent=self.root, title="选择音效包 ZIP", initialdir=SAMPLES if SAMPLES.is_dir() else Path.home(), filetypes=[("ZIP 音效包", "*.zip"), ("所有文件", "*")])
        if path:
            self.source.set(path)
            self.start_scan()

    def browse_dir(self):
        path = filedialog.askdirectory(parent=self.root, title="选择解压后的音效包目录", initialdir=Path.home())
        if path:
            self.source.set(path)
            self.start_scan()

    def browse_game(self):
        start = self.game_installs[0] if self.game_installs else Path.home()
        path = filedialog.askdirectory(parent=self.root, title="选择战争雷霆的安装目录", initialdir=start)
        if path:
            self.source.set(path)
            self.start_scan()

    def scan_detected_game(self):
        if self.game_installs:
            self.source.set(str(self.game_installs[0]))
            self.start_scan()

    def select_example(self, event=None):
        index = self.example.current()
        if index >= 0:
            self.source.set(str(self.examples[index]))
            self.start_scan()

    def refresh_controls(self):
        source_state = "disabled" if self.busy else "normal"
        for widget in (self.source_entry, self.choose_zip, self.choose_dir, self.choose_game, self.scan_button,
                       self.empty_zip, self.empty_dir, self.empty_game, self.empty_detected):
            widget.configure(state=source_state)
        self.example.configure(state="disabled" if self.busy else "readonly")
        usable = self.scan is not None and not self.busy
        for row in self.rows.values():
            row.set_enabled(usable)
        for widget in (self.export_button, self.reset_button, self.catalog_button, self.load_button, self.save_button, *self.bulk_widgets):
            widget.configure(state="normal" if usable else "disabled")
        for button in (self.open_button, self.copy_button):
            button.configure(state="normal" if self.result and not self.busy else "disabled")

    def run_worker(self, kind, operation):
        self.busy = True
        self.refresh_controls()
        self.progress.grid()
        self.progress.start(12)

        def work():
            try:
                self.queue.put((kind, operation()))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=False).start()

    def start_scan(self):
        if self.busy:
            return
        source = self.source.get().strip()
        if not source:
            self.status.set("请先选择 ZIP 或目录。")
            return
        self.scan = None
        self.clear_result()
        self.status.set("正在扫描音效包")
        self.run_worker("scan", lambda: Scan(source))
        self.show_main()

    def start_export(self):
        if self.busy or self.scan is None:
            return
        for row in self.rows.values():
            row.commit()
        gains = {key: row.percent if row.available else 100 for key, row in self.rows.items()}
        scan = self.scan
        self.clear_result()
        self.status.set("正在导出新包")
        self.run_worker("export", lambda: export(scan, gains, progress=lambda message: self.queue.put(("progress", message))))

    def poll(self):
        latest_progress = None
        while not self.queue.empty():
            kind, value = self.queue.get()
            if kind == "progress":
                latest_progress = value
                continue
            self.busy = False
            self.progress.stop()
            self.progress.grid_remove()
            if kind == "scan":
                self.scan = value
                self.current_source = value.source
                for key, row in self.rows.items():
                    row.set_count(value.counts[key])
                    row.set_value(100, notify=False)
                self.layout_rows()
                self.refresh_summary()
                first = next((tab for name, tab in self.tabs.items() if any(row.available and GROUP_INFO[row.key][0] == name for row in self.rows.values())), None)
                if first is not None:
                    self.notebook.select(first)
                size = f"{len(value.files)} 个文件 · {sum(value.files.values()) / 1024**2:.1f} MiB"
                self.summary.configure(text=f"游戏原版 {value.game_version} · {size}" if value.game_version else size)
                nested = f"嵌套事件 {value.nested} 个、" if value.nested else ""
                self.status.set(f"扫描完成。未命名事件 {value.unnamed} 个、{nested}快照记录 {value.snapshots} 条保留原样。" + " ".join(value.warnings))
            elif kind == "export":
                self.result = value
                self.result_path.set(value["archive"])
                self.result_frame.grid()
                self.status.set(f"导出完成，修改 {value['changed_fields']} 个音量字段。ZIP 哈希与音量回读校验通过。")
            else:
                self.status.set("失败，" + value)
                messagebox.showerror("操作未完成", value, parent=self.root)
            self.show_main()
            self.refresh_controls()
            latest_progress = None
        if latest_progress:
            self.status.set(latest_progress)
        self.poll_job = self.root.after(100, self.poll)

    def settings_changed(self):
        if self.scan and not self.busy:
            self.clear_result()
            self.refresh_summary()
            self.status.set("音量已更改，点击导出生成新包。")
            self.refresh_controls()

    def set_tab(self, tab_name, value):
        try:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError
        except ValueError:
            self.status.set("请输入 0 到 400 之间的百分比。")
            return
        for row in self.rows.values():
            if row.available and GROUP_INFO[row.key][0] == tab_name:
                row.set_value(value, notify=False)
        self.settings_changed()

    def reset(self):
        for row in self.rows.values():
            row.set_value(100, notify=False)
        self.clear_result()
        self.refresh_summary()
        self.refresh_controls()
        self.status.set("所有类别已恢复为原始音量。")

    def save_preset(self):
        if self.scan is None or self.busy:
            return
        for row in self.rows.values():
            row.commit()
        preset_dir = OUTPUT_ROOT / "presets"
        preset_dir.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(parent=self.root, title="保存音量预设", initialdir=preset_dir, initialfile="音量预设.json", defaultextension=".json", filetypes=[("JSON 预设", "*.json")])
        if path:
            try:
                Path(path).write_text(json.dumps({"version": 1, "gains_percent": {key: row.percent for key, row in self.rows.items()}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self.status.set("预设已保存，" + path)
            except OSError as exc:
                messagebox.showerror("保存预设失败", str(exc), parent=self.root)

    def load_preset(self):
        if self.scan is None or self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title="读取音量预设", initialdir=OUTPUT_ROOT, filetypes=[("JSON 预设", "*.json")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("预设格式不支持")
            # Presets saved before a category existed leave it at 100%.
            gains = gains_checked({**dict.fromkeys(GROUPS, 100), **data["gains_percent"]})
            for key, row in self.rows.items():
                row.set_value(gains[key] if row.available else 100, notify=False)
            self.clear_result()
            self.refresh_summary()
            self.refresh_controls()
            self.status.set("预设已读取。包里没有的类别保持 100%。")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("读取预设失败", str(exc), parent=self.root)

    def show_catalog(self):
        if self.scan is None:
            return
        window = tk.Toplevel(self.root)
        window.title("声音事件清单")
        window.configure(bg=BG)
        window.geometry(self.fit_geometry(1100, 600, 600, 360, window))
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        search = tk.StringVar()
        ttk.Label(frame, text="搜索事件、类别或 bank 文件").pack(anchor="w")
        entry = ttk.Entry(frame, textvariable=search)
        entry.pack(fill="x", pady=(6, 10))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        columns = ("group", "bank", "event", "db")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for key, title, width in zip(columns, ("类别", "bank", "事件或混音总线", "原始 dB"), (150, 180, 600, 80)):
            tree.heading(key, text=title)
            tree.column(key, width=self.px(width), minwidth=self.px(60))
        scrollbar = ttk.Scrollbar(table_frame, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(10, 0))
        shown = ttk.Label(bottom, style="Muted.TLabel")
        shown.pack(side="left")
        scan = self.scan

        def populate(*args):
            tree.delete(*tree.get_children())
            query = search.get().casefold()
            count = 0
            for t in scan.targets:
                values = (GROUPS[t.group], t.bank, t.event, f"{t.db:g}")
                if query in " ".join(values).casefold():
                    tree.insert("", "end", values=values)
                    count += 1
            shown.configure(text=f"显示 {count} / {len(scan.targets)} 条")

        def save_catalog():
            OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", prefix="event-catalog-", suffix=".json", dir=OUTPUT_ROOT, encoding="utf-8", delete=False) as file:
                json.dump({**scan.summary(), "events": [t.__dict__ for t in scan.targets]}, file, ensure_ascii=False, indent=2)
            self.status.set("事件清单已保存，" + file.name)

        ttk.Button(bottom, text="保存完整 JSON 清单", command=save_catalog).pack(side="right")
        search.trace_add("write", populate)
        populate()
        entry.focus_set()

    def open_output(self):
        if not self.result:
            return
        path = self.result["directory"]
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.status.set("打开目录失败，" + str(exc))

    def copy_path(self):
        if self.result:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.result["archive"])
            self.status.set("已复制 ZIP 路径。")

    def close(self):
        if self.busy:
            self.status.set("任务正在运行，完成后即可关闭。")
            return
        self.root.after_cancel(self.poll_job)
        self.root.destroy()


def main():
    enable_dpi_awareness()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(f"无法打开桌面窗口，{exc}。命令行用法见 README.md。") from exc
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
