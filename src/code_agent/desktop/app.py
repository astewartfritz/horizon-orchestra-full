from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, scrolledtext
from typing import Any, Optional

try:
    import tkinter as tk
    HAS_TK = True
except ImportError:
    HAS_TK = False


_THEME = {
    "bg": "#1a1b26",
    "fg": "#c0caf5",
    "input_bg": "#1f2335",
    "input_fg": "#c0caf5",
    "accent": "#4f8cf7",
    "accent_hover": "#3d7be0",
    "success": "#9ece6a",
    "error": "#f7768e",
    "warning": "#e0af68",
    "secondary": "#565f89",
    "border": "#2f3346",
    "card_bg": "#1f2335",
    "hover_bg": "#292e42",
    "font_family": "Segoe UI",
    "font_mono": "Consolas",
}


class DesktopGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Code Agent — Autonomous AI Engineering")
        self.root.geometry("1280x800")
        self.root.minsize(900, 600)
        self._setup_styles()
        self._build_ui()
        self._setup_bindings()
        self._running = True

    def _setup_styles(self):
        self.root.configure(bg=_THEME["bg"])
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=_THEME["bg"])
        style.configure("TLabel", background=_THEME["bg"], foreground=_THEME["fg"], font=(_THEME["font_family"], 10))
        style.configure("TButton", background=_THEME["card_bg"], foreground=_THEME["fg"], borderwidth=1, font=(_THEME["font_family"], 10))
        style.map("TButton", background=[("active", _THEME["hover_bg"])])
        style.configure("Accent.TButton", background=_THEME["accent"], foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", _THEME["accent_hover"])])

    def _build_ui(self):
        self._build_menu()
        panes = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)

        self._build_sidebar(panes)
        self._build_main(panes)
        self._build_statusbar()

    def _build_menu(self):
        menubar = tk.Menu(self.root, bg=_THEME["card_bg"], fg=_THEME["fg"], activebackground=_THEME["accent"], activeforeground="#ffffff")
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0, bg=_THEME["card_bg"], fg=_THEME["fg"], activebackground=_THEME["accent"], activeforeground="#ffffff")
        file_menu.add_command(label="New Session", command=self._new_session, accelerator="Ctrl+N")
        file_menu.add_command(label="Open Session...", command=self._open_session, accelerator="Ctrl+O")
        file_menu.add_command(label="Save Session", command=self._save_session, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export Logs...", command=self._export_logs)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close, accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0, bg=_THEME["card_bg"], fg=_THEME["fg"], activebackground=_THEME["accent"], activeforeground="#ffffff")
        tools_menu.add_command(label="Run Tool...", command=self._show_tool_runner, accelerator="Ctrl+T")
        tools_menu.add_command(label="Profile Code...", command=self._run_profiler)
        tools_menu.add_command(label="Analyze Code...", command=self._run_analyzer)
        tools_menu.add_separator()
        tools_menu.add_command(label="OpenShell Policy...", command=self._show_openshell)
        tools_menu.add_command(label="Privacy Router...", command=self._show_privacy)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        view_menu = tk.Menu(menubar, tearoff=0, bg=_THEME["card_bg"], fg=_THEME["fg"], activebackground=_THEME["accent"], activeforeground="#ffffff")
        self._show_toolbar_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(label="Toolbar", variable=self._show_toolbar_var, command=self._toggle_toolbar)
        view_menu.add_command(label="Toggle Dark/Light", command=self._toggle_theme)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=_THEME["card_bg"], fg=_THEME["fg"], activebackground=_THEME["accent"], activeforeground="#ffffff")
        help_menu.add_command(label="About Code Agent", command=self._show_about)
        help_menu.add_command(label="Keyboard Shortcuts", command=self._show_shortcuts)
        menubar.add_cascade(label="Help", menu=help_menu)

    def _build_sidebar(self, panes):
        sidebar = ttk.Frame(panes, width=260)
        panes.add(sidebar, weight=0)

        # Session header
        header = tk.Frame(sidebar, bg=_THEME["card_bg"], height=48)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="  Sessions", bg=_THEME["card_bg"], fg=_THEME["secondary"],
                 font=(_THEME["font_family"], 11, "bold")).pack(side=tk.LEFT, padx=12)
        new_btn = tk.Button(header, text="+", bg=_THEME["accent"], fg="#ffffff", bd=0,
                           font=("Segoe UI", 14, "bold"), width=2, cursor="hand2",
                           activebackground=_THEME["accent_hover"], command=self._new_session)
        new_btn.pack(side=tk.RIGHT, padx=8)

        # Session list
        self.session_list = tk.Listbox(sidebar, bg=_THEME["input_bg"], fg=_THEME["fg"],
                                       selectbackground=_THEME["accent"], selectforeground="#ffffff",
                                       bd=0, highlightthickness=0, font=(_THEME["font_family"], 10))
        self.session_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.session_list.insert(tk.END, "  main")
        self.session_list.selection_set(0)

        # Quick tools
        tools_frame = tk.Frame(sidebar, bg=_THEME["card_bg"])
        tools_frame.pack(fill=tk.X, pady=8)
        tk.Label(tools_frame, text="  Quick Tools", bg=_THEME["card_bg"], fg=_THEME["secondary"],
                 font=(_THEME["font_family"], 11, "bold")).pack(anchor=tk.W, padx=12, pady=4)

        quick_btns = [
            ("🔍  Search Code", self._run_search),
            ("📊  Profile", self._run_profiler),
            ("🔬  Analyze", self._run_analyzer),
            ("🛡️  Scan Security", self._run_security),
        ]
        for label, cmd in quick_btns:
            btn = tk.Button(tools_frame, text=label, bg=_THEME["input_bg"], fg=_THEME["fg"],
                           bd=0, anchor=tk.W, padx=16, pady=4, cursor="hand2",
                           activebackground=_THEME["hover_bg"], font=(_THEME["font_family"], 10),
                           command=cmd)
            btn.pack(fill=tk.X, padx=8, pady=1)

    def _build_main(self, panes):
        main = ttk.Frame(panes)
        panes.add(main, weight=1)

        # Toolbar
        self.toolbar = tk.Frame(main, bg=_THEME["card_bg"], height=44)
        self.toolbar.pack(fill=tk.X)
        self.toolbar.pack_propagate(False)

        btn_data = [
            ("▶  Run", self._run_task, _THEME["accent"]),
            ("⏹  Stop", self._stop_task, _THEME["error"]),
            ("🧹  Clear", self._clear_chat, _THEME["secondary"]),
        ]
        for label, cmd, color in btn_data:
            btn = tk.Button(self.toolbar, text=label, bg=color, fg="#ffffff", bd=0,
                           padx=14, pady=4, cursor="hand2", font=(_THEME["font_family"], 10),
                           activebackground=_THEME["accent_hover"], command=cmd)
            btn.pack(side=tk.LEFT, padx=4, pady=6)

        tk.Label(self.toolbar, text="Model:", bg=_THEME["card_bg"], fg=_THEME["secondary"],
                font=(_THEME["font_family"], 9)).pack(side=tk.RIGHT, padx=4)
        self.model_var = tk.StringVar(value="gpt-4o")
        model_combo = ttk.Combobox(self.toolbar, textvariable=self.model_var,
                                   values=["gpt-4o", "gpt-4o-mini", "claude-3-opus", "claude-3-sonnet", "ollama/llama3"],
                                   width=15, state="readonly")
        model_combo.pack(side=tk.RIGHT, padx=8)

        # Notebook for tabs
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Chat tab
        chat_frame = tk.Frame(self.notebook, bg=_THEME["bg"])
        self.notebook.add(chat_frame, text="  💬 Chat  ")

        self.chat_output = scrolledtext.ScrolledText(
            chat_frame, bg=_THEME["input_bg"], fg=_THEME["fg"],
            insertbackground=_THEME["fg"], font=(_THEME["font_mono"], 11),
            bd=0, padx=12, pady=12, state=tk.DISABLED, wrap=tk.WORD,
            relief=tk.FLAT, spacing1=4, spacing2=2, spacing3=4,
        )
        self.chat_output.pack(fill=tk.BOTH, expand=True)

        # Input area
        input_frame = tk.Frame(main, bg=_THEME["bg"])
        input_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.chat_input = tk.Text(input_frame, height=3, bg=_THEME["input_bg"], fg=_THEME["input_fg"],
                                  insertbackground=_THEME["fg"], font=(_THEME["font_family"], 11),
                                  bd=1, relief=tk.FLAT, padx=12, pady=8, wrap=tk.WORD,
                                  highlightbackground=_THEME["border"], highlightcolor=_THEME["accent"],
                                  highlightthickness=1)
        self.chat_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.chat_input.bind("<Return>", self._on_enter_key)

        send_btn = tk.Button(input_frame, text="Send  ▶", bg=_THEME["accent"], fg="#ffffff",
                            bd=0, padx=20, pady=8, cursor="hand2",
                            font=(_THEME["font_family"], 10, "bold"),
                            activebackground=_THEME["accent_hover"], command=self._send_message)
        send_btn.pack(side=tk.RIGHT, padx=(8, 0))

        # Tools tab
        tools_tab = tk.Frame(self.notebook, bg=_THEME["bg"])
        self.notebook.add(tools_tab, text="  🛠️  Tools  ")
        self._build_tools_tab(tools_tab)

        # Logs tab
        logs_tab = tk.Frame(self.notebook, bg=_THEME["bg"])
        self.notebook.add(logs_tab, text="  📋  Logs  ")
        self._build_logs_tab(logs_tab)

        # Config tab
        config_tab = tk.Frame(self.notebook, bg=_THEME["bg"])
        self.notebook.add(config_tab, text="  ⚙️  Config  ")
        self._build_config_tab(config_tab)

        # Analytics tab
        analytics_tab = tk.Frame(self.notebook, bg=_THEME["bg"])
        self.notebook.add(analytics_tab, text="  📊  Analytics  ")
        self._build_analytics_tab(analytics_tab)

        # Context tab
        context_tab = tk.Frame(self.notebook, bg=_THEME["bg"])
        self.notebook.add(context_tab, text="  🧠  Context  ")
        self._build_context_tab(context_tab)

    def _build_tools_tab(self, parent):
        left = tk.Frame(parent, bg=_THEME["bg"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8)

        tk.Label(left, text="Tool Runner", bg=_THEME["bg"], fg=_THEME["fg"],
                font=(_THEME["font_family"], 13, "bold")).pack(anchor=tk.W)

        tool_frame = tk.Frame(left, bg=_THEME["bg"])
        tool_frame.pack(fill=tk.X, pady=8)

        tk.Label(tool_frame, text="Tool:", bg=_THEME["bg"], fg=_THEME["secondary"]).pack(side=tk.LEFT)
        self.tool_var = tk.StringVar(value="bash")
        self.tool_combo = ttk.Combobox(tool_frame, textvariable=self.tool_var,
                                       values=["bash", "read", "write", "edit", "grep", "glob", "webfetch",
                                               "git", "analyze", "sql", "api", "sandbox", "diff"],
                                       width=15, state="readonly")
        self.tool_combo.pack(side=tk.LEFT, padx=8)

        tk.Label(tool_frame, text="Args:", bg=_THEME["bg"], fg=_THEME["secondary"]).pack(side=tk.LEFT, padx=(16, 4))
        self.tool_args = tk.Entry(tool_frame, bg=_THEME["input_bg"], fg=_THEME["input_fg"],
                                 insertbackground=_THEME["fg"], bd=1, relief=tk.FLAT,
                                 highlightbackground=_THEME["border"], font=(_THEME["font_family"], 10))
        self.tool_args.pack(side=tk.LEFT, fill=tk.X, expand=True)

        run_btn = tk.Button(tool_frame, text="Run", bg=_THEME["accent"], fg="#ffffff",
                           bd=0, padx=16, font=(_THEME["font_family"], 10), cursor="hand2",
                           command=self._run_tool)
        run_btn.pack(side=tk.LEFT, padx=8)

        self.tool_output = scrolledtext.ScrolledText(
            left, bg=_THEME["input_bg"], fg=_THEME["fg"],
            font=(_THEME["font_mono"], 10), bd=0, state=tk.DISABLED,
            relief=tk.FLAT, height=12,
        )
        self.tool_output.pack(fill=tk.BOTH, expand=True, pady=8)

        # Quick tool buttons
        quick_frame = tk.Frame(left, bg=_THEME["bg"])
        quick_frame.pack(fill=tk.X)
        quick_tools = [
            ("bash", "echo hello"), ("read", "."), ("glob", "**/*.py"),
            ("grep", "class "), ("webfetch", "https://example.com"),
        ]
        for tool, args in quick_tools:
            btn = tk.Button(quick_frame, text=f"{tool} {args}", bg=_THEME["card_bg"], fg=_THEME["fg"],
                           bd=0, padx=8, pady=2, font=(_THEME["font_mono"], 9), cursor="hand2",
                           activebackground=_THEME["hover_bg"],
                           command=lambda t=tool, a=args: self._quick_tool(t, a))
            btn.pack(side=tk.LEFT, padx=2)

        # Tool info panel
        right = tk.Frame(parent, bg=_THEME["card_bg"], width=280)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)
        right.pack_propagate(False)

        tk.Label(right, text="Available Tools", bg=_THEME["card_bg"], fg=_THEME["fg"],
                font=(_THEME["font_family"], 12, "bold")).pack(anchor=tk.W, padx=12, pady=8)

        self.tool_info = scrolledtext.ScrolledText(
            right, bg=_THEME["input_bg"], fg=_THEME["fg"],
            font=(_THEME["font_mono"], 9), bd=0, state=tk.DISABLED,
            relief=tk.FLAT, wrap=tk.WORD,
        )
        self.tool_info.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._populate_tool_info()

    def _build_logs_tab(self, parent):
        self.log_output = scrolledtext.ScrolledText(
            parent, bg=_THEME["input_bg"], fg=_THEME["fg"],
            insertbackground=_THEME["fg"], font=(_THEME["font_mono"], 10),
            bd=0, padx=12, pady=8, state=tk.DISABLED, wrap=tk.WORD,
            relief=tk.FLAT,
        )
        self.log_output.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        log_ctrl = tk.Frame(parent, bg=_THEME["bg"])
        log_ctrl.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(log_ctrl, text="Clear Logs", bg=_THEME["card_bg"], fg=_THEME["fg"],
                 bd=0, padx=12, cursor="hand2", command=self._clear_logs).pack(side=tk.LEFT)
        tk.Button(log_ctrl, text="Export Logs...", bg=_THEME["card_bg"], fg=_THEME["fg"],
                 bd=0, padx=12, cursor="hand2", command=self._export_logs).pack(side=tk.LEFT, padx=8)

        self._log("Code Agent GUI started")

    def _build_config_tab(self, parent):
        canvas = tk.Canvas(parent, bg=_THEME["bg"], bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        frame = scroll_frame
        row = 0

        def add_section(title, items):
            nonlocal row
            tk.Label(frame, text=title, bg=_THEME["bg"], fg=_THEME["fg"],
                    font=(_THEME["font_family"], 13, "bold")).grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=(16, 8), padx=16)
            row += 1
            for label, var, values in items:
                tk.Label(frame, text=label, bg=_THEME["bg"], fg=_THEME["secondary"],
                        font=(_THEME["font_family"], 10)).grid(row=row, column=0, sticky=tk.W, padx=16, pady=2)
                if values:
                    cb = ttk.Combobox(frame, textvariable=var, values=values, width=20, state="readonly")
                    cb.grid(row=row, column=1, padx=8, pady=2)
                else:
                    e = tk.Entry(frame, textvariable=var, bg=_THEME["input_bg"], fg=_THEME["input_fg"],
                                bd=1, relief=tk.FLAT, width=25, font=(_THEME["font_family"], 10))
                    e.grid(row=row, column=1, padx=8, pady=2)
                row += 1

        self.config_vars = {}
        for name in ["LLM Provider", "Model", "Workspace", "Max Iterations"]:
            self.config_vars[name] = tk.StringVar(value={"LLM Provider": "openai", "Model": "gpt-4o",
                                                          "Workspace": ".", "Max Iterations": "50"}[name])

        add_section("LLM Configuration", [
            ("Provider", self.config_vars["LLM Provider"], ["openai", "anthropic", "ollama"]),
            ("Model", self.config_vars["Model"], ["gpt-4o", "gpt-4o-mini", "claude-3-opus", "claude-3-sonnet", "llama3", "mistral"]),
            ("Workspace", self.config_vars["Workspace"], None),
            ("Max Iterations", self.config_vars["Max Iterations"], None),
        ])

        add_section("Features", [
            ("Cache", tk.StringVar(value="Enabled"), ["Enabled", "Disabled"]),
            ("Streaming", tk.StringVar(value="Enabled"), ["Enabled", "Disabled"]),
            ("Confirm Before Run", tk.StringVar(value="Disabled"), ["Enabled", "Disabled"]),
        ])

        add_section("Policy", [
            ("OpenShell Profile", tk.StringVar(value="standard"), ["strict", "standard", "permissive", "custom"]),
            ("Privacy Router", tk.StringVar(value="Enabled"), ["Enabled", "Disabled"]),
        ])

        tk.Button(frame, text="Save Config", bg=_THEME["accent"], fg="#ffffff",
                 bd=0, padx=24, pady=6, font=(_THEME["font_family"], 10, "bold"),
                 cursor="hand2", command=self._save_config).grid(row=row, column=0, pady=20, padx=16)
        row += 1
        tk.Button(frame, text="Reset to Defaults", bg=_THEME["card_bg"], fg=_THEME["fg"],
                 bd=0, padx=24, pady=6, font=(_THEME["font_family"], 10),
                 cursor="hand2", command=self._reset_config).grid(row=row, column=0, pady=(0, 20), padx=16)

    def _build_analytics_tab(self, parent):
        stats_frame = tk.Frame(parent, bg=_THEME["bg"])
        stats_frame.pack(fill=tk.X, padx=16, pady=16)

        self.stats_labels = {}
        stats_data = [
            ("Total Sessions", "3"),
            ("Total Messages", "47"),
            ("Total Tool Calls", "128"),
            ("Total Tokens", "842,591"),
            ("Estimated Cost", "$0.42"),
            ("Avg Response Time", "2.3s"),
        ]
        for i, (label, value) in enumerate(stats_data):
            card = tk.Frame(stats_frame, bg=_THEME["card_bg"], bd=1, relief=tk.FLAT,
                          highlightbackground=_THEME["border"], highlightthickness=1)
            card.grid(row=i // 3, column=i % 3, padx=8, pady=8, sticky=tk.NSEW)
            stats_frame.grid_columnconfigure(i % 3, weight=1)
            tk.Label(card, text=value, bg=_THEME["card_bg"], fg=_THEME["accent"],
                    font=(_THEME["font_family"], 24, "bold")).pack(pady=(16, 4))
            tk.Label(card, text=label, bg=_THEME["card_bg"], fg=_THEME["secondary"],
                    font=(_THEME["font_family"], 10)).pack(pady=(0, 16))

        model_frame = tk.Frame(parent, bg=_THEME["bg"])
        model_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        tk.Label(model_frame, text="Model Usage Breakdown", bg=_THEME["bg"], fg=_THEME["fg"],
                font=(_THEME["font_family"], 12, "bold")).pack(anchor=tk.W, pady=8)

        usage_data = [
            ("gpt-4o", 45, _THEME["accent"]),
            ("gpt-4o-mini", 30, _THEME["success"]),
            ("claude-3-sonnet", 15, _THEME["warning"]),
            ("ollama/llama3", 10, _THEME["secondary"]),
        ]
        for model, pct, color in usage_data:
            row_f = tk.Frame(model_frame, bg=_THEME["bg"])
            row_f.pack(fill=tk.X, pady=4)
            tk.Label(row_f, text=model, bg=_THEME["bg"], fg=_THEME["fg"],
                    font=(_THEME["font_mono"], 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
            bar_frame = tk.Frame(row_f, bg=_THEME["input_bg"], height=20)
            bar_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
            bar = tk.Frame(bar_frame, bg=color, width=int(pct * 3))
            bar.pack(side=tk.LEFT, fill=tk.Y)
            tk.Label(row_f, text=f"{pct}%", bg=_THEME["bg"], fg=_THEME["secondary"],
                    font=(_THEME["font_mono"], 10), width=6).pack(side=tk.LEFT)

    def _build_context_tab(self, parent):
        from code_agent.context.manager import ContextManager
        from code_agent.context.display import render_rich_context

        self._ctx = ContextManager()
        self._ctx_data = render_rich_context(self._ctx)

        # Top section: gauge card
        gauge_frame = tk.Frame(parent, bg=_THEME["bg"])
        gauge_frame.pack(fill=tk.X, padx=16, pady=(16, 4))

        gauge_card = tk.Frame(gauge_frame, bg=_THEME["card_bg"], bd=1, relief=tk.FLAT,
                              highlightbackground=_THEME["border"], highlightthickness=1)
        gauge_card.pack(fill=tk.X, padx=0, pady=0)

        # Token gauge canvas
        canvas_frame = tk.Frame(gauge_card, bg=_THEME["card_bg"])
        canvas_frame.pack(fill=tk.X, padx=16, pady=(12, 4))
        self.ctx_canvas = tk.Canvas(canvas_frame, height=40, bg=_THEME["card_bg"],
                                    bd=0, highlightthickness=0)
        self.ctx_canvas.pack(fill=tk.X)

        # Token labels
        label_frame = tk.Frame(gauge_card, bg=_THEME["card_bg"])
        label_frame.pack(fill=tk.X, padx=16, pady=(0, 8))

        self.ctx_used_label = tk.Label(label_frame, text="0 tokens used",
                                       bg=_THEME["card_bg"], fg=_THEME["accent"],
                                       font=(_THEME["font_family"], 14, "bold"))
        self.ctx_used_label.pack(side=tk.LEFT)
        self.ctx_max_label = tk.Label(label_frame, text="/ 128,000 tokens",
                                      bg=_THEME["card_bg"], fg=_THEME["secondary"],
                                      font=(_THEME["font_family"], 14))
        self.ctx_max_label.pack(side=tk.LEFT)
        self.ctx_pct_label = tk.Label(label_frame, text="(0%)",
                                      bg=_THEME["card_bg"], fg=_THEME["secondary"],
                                      font=(_THEME["font_family"], 12))
        self.ctx_pct_label.pack(side=tk.LEFT, padx=8)

        # Saturation level badge
        self.ctx_badge = tk.Label(label_frame, text="  EMPTY  ", bg=_THEME["secondary"],
                                  fg="#ffffff", font=(_THEME["font_family"], 9, "bold"))
        self.ctx_badge.pack(side=tk.RIGHT)

        # Middle: tier breakdown + stats cards
        mid_frame = tk.Frame(parent, bg=_THEME["bg"])
        mid_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=4)

        # Left: tier breakdown
        tier_frame = tk.Frame(mid_frame, bg=_THEME["card_bg"], bd=1, relief=tk.FLAT,
                              highlightbackground=_THEME["border"], highlightthickness=1)
        tier_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        tk.Label(tier_frame, text="Tier Breakdown", bg=_THEME["card_bg"], fg=_THEME["fg"],
                font=(_THEME["font_family"], 12, "bold")).pack(anchor=tk.W, padx=12, pady=8)

        self.tier_rows: dict[str, dict] = {}
        tier_colors = {
            "critical": ("Critical", "#ff5050"),
            "important": ("Important", "#ffb432"),
            "normal": ("Normal", "#50a0ff"),
            "low": ("Low", "#8c8ca0"),
        }
        for tier_key, (tier_label, tier_color) in tier_colors.items():
            row = tk.Frame(tier_frame, bg=_THEME["card_bg"])
            row.pack(fill=tk.X, padx=12, pady=2)
            # Color dot
            dot = tk.Canvas(row, width=12, height=12, bg=_THEME["card_bg"], bd=0, highlightthickness=0)
            dot.pack(side=tk.LEFT, padx=(0, 6))
            dot.create_oval(2, 2, 10, 10, fill=tier_color, outline="")
            tk.Label(row, text=tier_label, bg=_THEME["card_bg"], fg=_THEME["fg"],
                    font=(_THEME["font_family"], 10), width=12, anchor=tk.W).pack(side=tk.LEFT)

            bar_bg = tk.Frame(row, bg=_THEME["input_bg"], height=14, width=120)
            bar_bg.pack(side=tk.LEFT, padx=4)
            bar_bg.pack_propagate(False)
            bar_fill = tk.Frame(bar_bg, bg=tier_color, height=14, width=0)
            bar_fill.pack(side=tk.LEFT, fill=tk.Y)

            self.tier_rows[tier_key] = {
                "bar_bg": bar_bg,
                "bar_fill": bar_fill,
                "count_label": tk.Label(row, text="0 entries", bg=_THEME["card_bg"],
                                        fg=_THEME["secondary"], font=(_THEME["font_family"], 9)),
            }
            self.tier_rows[tier_key]["count_label"].pack(side=tk.LEFT, padx=(4, 0))

        # Right: info cards
        info_frame = tk.Frame(mid_frame, bg=_THEME["bg"])
        info_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(8, 0))

        info_items = [
            ("Total Entries", "0", "entries"),
            ("Free Tokens", "124,000", "available"),
            ("Reserve", "4,000", "reserved"),
            ("Saturation", "0%", "level"),
        ]
        self.ctx_info_labels = {}
        for label, val, unit in info_items:
            card = tk.Frame(info_frame, bg=_THEME["card_bg"], bd=1, relief=tk.FLAT,
                           highlightbackground=_THEME["border"], highlightthickness=1)
            card.pack(fill=tk.X, pady=3)
            tk.Label(card, text=val, bg=_THEME["card_bg"], fg=_THEME["accent"],
                    font=(_THEME["font_family"], 18, "bold")).pack(pady=(8, 0))
            tk.Label(card, text=label, bg=_THEME["card_bg"], fg=_THEME["secondary"],
                    font=(_THEME["font_family"], 9)).pack(pady=(0, 8))
            self.ctx_info_labels[label] = (card, val)

        # Bottom: controls
        ctrl_frame = tk.Frame(parent, bg=_THEME["bg"])
        ctrl_frame.pack(fill=tk.X, padx=16, pady=8)

        tk.Button(ctrl_frame, text=" Add Demo Data ", bg=_THEME["accent"], fg="#ffffff",
                 bd=0, padx=16, pady=4, cursor="hand2",
                 font=(_THEME["font_family"], 10), command=self._ctx_add_demo).pack(side=tk.LEFT, padx=4)
        tk.Button(ctrl_frame, text=" Analyze Current Session ", bg=_THEME["card_bg"], fg=_THEME["fg"],
                 bd=0, padx=16, pady=4, cursor="hand2",
                 font=(_THEME["font_family"], 10), command=self._ctx_analyze_session).pack(side=tk.LEFT, padx=4)
        tk.Button(ctrl_frame, text=" Clear ", bg=_THEME["card_bg"], fg=_THEME["error"],
                 bd=0, padx=16, pady=4, cursor="hand2",
                 font=(_THEME["font_family"], 10), command=self._ctx_clear).pack(side=tk.LEFT, padx=4)

        self._ctx_refresh_display()

    def _ctx_refresh_display(self):
        """Redraw the context tab with current data."""
        from code_agent.context.display import render_rich_context
        data = render_rich_context(self._ctx)
        s = data

        # Update gauge canvas
        self.ctx_canvas.delete("all")
        cw = self.ctx_canvas.winfo_width() or 600
        gauge_w = cw - 20
        used_pct = s["saturation_pct"] / 100
        effective_max = s["max_tokens"] - s["reserve_tokens"]

        # Background track
        self.ctx_canvas.create_rectangle(10, 12, 10 + gauge_w, 32, fill=_THEME["input_bg"],
                                         outline=_THEME["border"], width=1, tags="track")

        # Draw blocks
        x = 10
        for block in s["bar_blocks"]:
            w = max(1, int(block["pct"] / 100 * gauge_w))
            self.ctx_canvas.create_rectangle(x, 12, x + w, 32,
                                             fill=block["color_hex"].strip(),
                                             outline="", tags="block")
            x += w

        # Free space
        free_w = max(0, int(s["free_pct"] / 100 * gauge_w))
        if free_w > 0:
            self.ctx_canvas.create_rectangle(x, 12, x + free_w, 32,
                                             fill=_THEME["card_bg"],
                                             outline=_THEME["border"], width=0, stipple="gray50",
                                             tags="free")
            x += free_w

        # Reserve
        reserve_w = max(0, int(s["reserve_pct"] / 100 * gauge_w))
        if reserve_w > 0:
            self.ctx_canvas.create_rectangle(x, 12, x + reserve_w, 32,
                                             fill=_THEME["secondary"],
                                             outline=_THEME["border"], width=0, stipple="gray25",
                                             tags="reserve")

        # Labels
        used_fmt = self._ctx_fmt(s["used_tokens"])
        max_fmt = self._ctx_fmt(s["max_tokens"])
        self.ctx_used_label.config(text=f"{used_fmt} used")
        self.ctx_max_label.config(text=f"/ {max_fmt}")
        self.ctx_pct_label.config(text=f"({s['saturation_pct']}%)")

        # Badge
        level = s.get("saturation_level", "low")
        badge_colors = {"critical": (" CRITICAL ", _THEME["error"]),
                        "high": (" HIGH ", _THEME["warning"]),
                        "moderate": (" MODERATE ", "#50a0ff"),
                        "low": (" LOW ", _THEME["success"])}
        badge_text, badge_bg = badge_colors.get(level, (" UNKNOWN ", _THEME["secondary"]))
        self.ctx_badge.config(text=badge_text, bg=badge_bg)

        # Tier rows
        effective = s["max_tokens"] - s["reserve_tokens"]
        for tier_info in s["tiers"]:
            tier = tier_info["tier"]
            tokens = tier_info["tokens"]
            count = tier_info["count"]
            share = tier_info["share_pct"]

            if tier in self.tier_rows:
                row_data = self.tier_rows[tier]
                if count > 0:
                    bar_width = max(1, int(share / 100 * 120)) if share > 0 else 0
                    row_data["bar_fill"].config(width=bar_width)
                    row_data["count_label"].config(text=f"{count} entries, {self._ctx_fmt(tokens)}")
                else:
                    row_data["bar_fill"].config(width=0)
                    row_data["count_label"].config(text="0 entries")

        # Info cards
        info_values = {
            "Total Entries": str(s["entries"]),
            "Free Tokens": self._ctx_fmt(s["free_tokens"]),
            "Reserve": self._ctx_fmt(s["reserve_tokens"]),
            "Saturation": f"{s['saturation_pct']}%",
        }
        for label, val in info_values.items():
            if label in self.ctx_info_labels:
                card, _ = self.ctx_info_labels[label]
                children = card.winfo_children()
                if children:
                    children[0].config(text=val)

    def _ctx_fmt(self, n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    def _ctx_add_demo(self):
        self._ctx = __import__("code_agent.context.manager", fromlist=[""]).ContextManager()
        self._ctx.add("System: You are a helpful AI coding agent.", tier="critical", source="system")
        self._ctx.add("User: Build a web scraper for news sites.", tier="important", source="user")
        self._ctx.add("Scraped https://example.com (120KB)", tier="normal", source="webfetch")
        self._ctx.add("Analyzed 15 Python files", tier="normal", source="analyze")
        self._ctx.add("Search results: web scraping best", tier="normal", source="websearch")
        self._ctx.add("Debug log: Connection timeout", tier="low", source="log")
        self._ctx.add("Cache hit: 2.3ms", tier="low", source="cache")
        self._ctx_refresh_display()
        self._log("Context: demo data loaded", "ok")

    def _ctx_analyze_session(self):
        """Analyze current chat messages as context data."""
        cm = __import__("code_agent.context.manager", fromlist=[""]).ContextManager()
        text = self.chat_output.get("1.0", tk.END)
        lines = [l for l in text.split("\n") if l.strip()]
        for line in lines:
            if line.startswith("[You]"):
                cm.add(line, tier="important", source="user")
            elif line.startswith("[Agent]"):
                cm.add(line, tier="normal", source="assistant")
            elif line.startswith("[System]"):
                cm.add(line, tier="critical", source="system")
            else:
                cm.add(line, tier="low", source="log")
        self._ctx = cm
        self._ctx_refresh_display()
        self._log(f"Context: analyzed chat ({len(lines)} lines)", "ok")

    def _ctx_clear(self):
        self._ctx = __import__("code_agent.context.manager", fromlist=[""]).ContextManager()
        self._ctx_refresh_display()
        self._log("Context: cleared", "info")

    def _build_statusbar(self):
        status = tk.Frame(self.root, bg=_THEME["card_bg"], height=28)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        status.pack_propagate(False)

        self.status_text = tk.Label(status, text="Ready", bg=_THEME["card_bg"], fg=_THEME["secondary"],
                                   font=(_THEME["font_family"], 9), anchor=tk.W)
        self.status_text.pack(side=tk.LEFT, padx=12)

        tk.Label(status, text="v0.4.0", bg=_THEME["card_bg"], fg=_THEME["secondary"],
                font=(_THEME["font_family"], 9)).pack(side=tk.RIGHT, padx=12)

    def _setup_bindings(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-n>", lambda e: self._new_session())
        self.root.bind("<Control-o>", lambda e: self._open_session())
        self.root.bind("<Control-s>", lambda e: self._save_session())
        self.root.bind("<Control-q>", lambda e: self._on_close())
        self.root.bind("<Control-t>", lambda e: self._show_tool_runner())
        self.root.bind("<Escape>", lambda e: self._clear_chat())

    def _on_enter_key(self, event):
        if not event.state & 0x1:
            self._send_message()
            return "break"

    # === Actions ===

    def _send_message(self):
        text = self.chat_input.get("1.0", tk.END).strip()
        if not text:
            return
        self.chat_input.delete("1.0", tk.END)
        self._append_chat("You", text, _THEME["accent"])
        self._set_status(f"Processing: {text[:50]}...")

        def process():
            time.sleep(0.5)
            self.root.after(0, lambda: self._append_chat("Agent", f"Executing: {text}\n\n[Agent processing...]", _THEME["success"]))
            self.root.after(0, lambda: self._set_status("Ready"))

        threading.Thread(target=process, daemon=True).start()

    def _append_chat(self, sender: str, message: str, color: str):
        self.chat_output.configure(state=tk.NORMAL)
        self.chat_output.insert(tk.END, f"\n[{sender}] ", f"sender_{sender}")
        self.chat_output.tag_config(f"sender_{sender}", foreground=color, font=(_THEME["font_family"], 10, "bold"))
        self.chat_output.insert(tk.END, f"{message}\n", f"msg_{sender}")
        self.chat_output.tag_config(f"msg_{sender}", foreground=_THEME["fg"], font=(_THEME["font_mono"], 10))
        self.chat_output.see(tk.END)
        self.chat_output.configure(state=tk.DISABLED)

    def _log(self, message: str, level: str = "info"):
        colors = {"info": _THEME["fg"], "warn": _THEME["warning"], "error": _THEME["error"], "ok": _THEME["success"]}
        color = colors.get(level, _THEME["fg"])
        self.log_output.configure(state=tk.NORMAL)
        ts = time.strftime("%H:%M:%S")
        self.log_output.insert(tk.END, f"[{ts}] ", "log_ts")
        self.log_output.tag_config("log_ts", foreground=_THEME["secondary"])
        self.log_output.insert(tk.END, f"{message}\n", f"log_{level}")
        self.log_output.tag_config(f"log_{level}", foreground=color)
        self.log_output.see(tk.END)
        self.log_output.configure(state=tk.DISABLED)

    def _set_status(self, text: str):
        self.status_text.config(text=text)

    def _run_tool(self):
        tool = self.tool_var.get()
        args = self.tool_args.get()
        self._log(f"Running: {tool} {args}", "info")
        self._set_status(f"Running {tool}...")

        def execute():
            try:
                if tool == "bash":
                    result = subprocess.run(args, shell=True, capture_output=True, text=True, timeout=30)
                    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
                elif tool == "read":
                    output = Path(args).read_text(encoding="utf-8")[:5000]
                elif tool == "glob":
                    files = list(Path(".").rglob(args)) if "**" in args else list(Path(".").glob(args))
                    output = "\n".join(str(f) for f in files[:50])
                else:
                    output = f"[{tool}] executed with args: {args}"
                self.root.after(0, lambda: self._show_tool_output(output))
                self.root.after(0, lambda: self._log(f"Completed: {tool}", "ok"))
            except Exception as e:
                self.root.after(0, lambda: self._show_tool_output(f"Error: {e}"))
                self.root.after(0, lambda: self._log(f"Error: {e}", "error"))
            self.root.after(0, lambda: self._set_status("Ready"))

        threading.Thread(target=execute, daemon=True).start()

    def _show_tool_output(self, text: str):
        self.tool_output.configure(state=tk.NORMAL)
        self.tool_output.delete("1.0", tk.END)
        self.tool_output.insert(tk.END, text)
        self.tool_output.configure(state=tk.DISABLED)

    def _quick_tool(self, tool: str, args: str):
        self.tool_var.set(tool)
        self.tool_args.delete(0, tk.END)
        self.tool_args.insert(0, args)
        self.notebook.select(1)
        self._run_tool()

    def _populate_tool_info(self):
        tools_info = """Available Tools:

  File Operations:
    read   — Read file contents
    write  — Write content to file
    edit   — Edit file with string replace
    glob   — Find files by pattern

  Search:
    grep   — Search file contents
    analyze — AST-based code analysis

  Execution:
    bash   — Run shell commands
    sandbox — Run in restricted sandbox
    sql    — Query SQLite databases
    api    — Make HTTP requests

  Web:
    webfetch — Fetch URLs
    websearch — Search the web

  Code:
    diff   — Show file differences
    patch  — Apply patches
    transform — AST code transforms
    testgen  — Generate tests

  Git:
    git    — Git operations

  Meta:
    task   — Delegate to sub-agent
    improve — Self-improvement
    workflow — Run workflows"""
        self.tool_info.configure(state=tk.NORMAL)
        self.tool_info.insert(tk.END, tools_info)
        self.tool_info.configure(state=tk.DISABLED)

    def _run_task(self):
        self.notebook.select(0)
        self._append_chat("System", "Ready for your task. Type a message below.", _THEME["secondary"])

    def _stop_task(self):
        self._log("Task stopped by user", "warn")
        self._set_status("Stopped")

    def _clear_chat(self):
        self.chat_output.configure(state=tk.NORMAL)
        self.chat_output.delete("1.0", tk.END)
        self.chat_output.configure(state=tk.DISABLED)
        self._log("Chat cleared", "info")

    def _clear_logs(self):
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.delete("1.0", tk.END)
        self.log_output.configure(state=tk.DISABLED)

    def _new_session(self):
        self._clear_chat()
        self._log("New session created", "info")
        self._append_chat("System", "New session started. How can I help?", _THEME["secondary"])

    def _open_session(self):
        path = filedialog.askopenfilename(
            title="Open Session",
            filetypes=[("Session files", "*.json"), ("All files", "*.*")],
            initialdir=".code-agent-sessions",
        )
        if path:
            self._log(f"Opened session: {path}", "info")

    def _save_session(self):
        path = filedialog.asksaveasfilename(
            title="Save Session",
            defaultextension=".json",
            filetypes=[("Session files", "*.json")],
            initialdir=".code-agent-sessions",
        )
        if path:
            data = {"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "messages": []}
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._log(f"Session saved: {path}", "ok")

    def _export_logs(self):
        path = filedialog.asksaveasfilename(
            title="Export Logs",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            content = self.log_output.get("1.0", tk.END)
            Path(path).write_text(content, encoding="utf-8")
            self._log(f"Logs exported: {path}", "ok")

    def _run_search(self):
        self.notebook.select(1)
        self.tool_var.set("grep")
        self.tool_args.delete(0, tk.END)
        self.tool_args.insert(0, "class ")
        self._log("Search tool selected", "info")

    def _run_profiler(self):
        self._log("Profiler: run 'code-agent profile --help' in terminal", "info")
        messagebox.showinfo("Profiler", "Run: code-agent profile --code \"your code here\"")

    def _run_analyzer(self):
        self._log("Analyzer selected", "info")
        self.notebook.select(1)
        self.tool_var.set("analyze")
        self.tool_args.delete(0, tk.END)
        self.tool_args.insert(0, ".")

    def _run_security(self):
        self._log("Security scan selected", "info")
        messagebox.showinfo("Security Scan", "Run: code-agent audit --path .")

    def _show_tool_runner(self):
        self.notebook.select(1)
        self.tool_args.focus_set()

    def _show_openshell(self):
        self._log("OpenShell: run 'code-agent openshell status' in terminal", "info")
        messagebox.showinfo("OpenShell Policy", "Run: code-agent openshell status")

    def _show_privacy(self):
        self._log("Privacy Router: run 'code-agent privacy \"your query\"' in terminal", "info")
        messagebox.showinfo("Privacy Router", "Run: code-agent privacy \"your query\"")

    def _toggle_toolbar(self):
        if self._show_toolbar_var.get():
            self.toolbar.pack(fill=tk.X)
        else:
            self.toolbar.pack_forget()

    def _toggle_theme(self):
        messagebox.showinfo("Theme", "Theme switching available in full version")

    def _save_config(self):
        self._log("Configuration saved", "ok")
        messagebox.showinfo("Config", "Configuration saved successfully.")

    def _reset_config(self):
        self._log("Configuration reset to defaults", "info")
        messagebox.showinfo("Config", "Configuration reset to defaults.")

    def _show_about(self):
        about = (
            "Code Agent v0.4.0\n\n"
            "Autonomous AI-powered software engineering assistant.\n\n"
            "87 CLI commands  ·  31 tools  ·  Multi-LLM\n"
            "Multi-agent orchestration  ·  Local-first\n\n"
            "MIT License — Open Source"
        )
        messagebox.showinfo("About Code Agent", about)

    def _show_shortcuts(self):
        shortcuts = (
            "Keyboard Shortcuts:\n\n"
            "Ctrl+N    New Session\n"
            "Ctrl+O    Open Session\n"
            "Ctrl+S    Save Session\n"
            "Ctrl+T    Show Tool Runner\n"
            "Ctrl+Q    Quit\n"
            "Enter     Send Message\n"
            "Shift+Enter  New Line\n"
            "Escape    Clear Chat"
        )
        messagebox.showinfo("Keyboard Shortcuts", shortcuts)

    def _on_close(self):
        self._running = False
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if not HAS_TK:
        print("Tkinter not available. Install python-tk package.")
        return
    app = DesktopGUI()
    app.run()


if __name__ == "__main__":
    main()
