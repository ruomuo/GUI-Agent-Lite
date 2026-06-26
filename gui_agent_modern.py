"""
GUI Agent Lite - macOS 优化浮窗版本
右下角小窗口，流式显示思考过程，完成后可折叠
"""

import os
import re
import time
import base64
import json
import io
import sys
import threading
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from dotenv import load_dotenv, set_key, find_dotenv

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from PIL import Image, ImageTk
import requests
import pyautogui

from agent_memory import MemoryStore, TaskMemory

load_dotenv()
pyautogui.FAILSAFE = True

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
_IS_MACOS = sys.platform == 'darwin'
_IS_WINDOWS = sys.platform == 'win32'

# cliclick — reliable macOS mouse/keyboard automation (works on 15.4+)
_CLICLICK = '/opt/homebrew/bin/cliclick' if _IS_MACOS else None

# Platform-appropriate fonts
# macOS: use 'system-ui' which resolves to .AppleSystemUIFont (San Francisco)
#        sizes bumped up to match macOS design standards (default is 13pt)
# Windows: keep Segoe UI with standard sizes
SANS_FONT = ('system-ui', 12) if _IS_MACOS else ('Segoe UI', 10)
SANS_BOLD = ('system-ui', 12, 'bold') if _IS_MACOS else ('Segoe UI', 10, 'bold')
SANS_SMALL = ('system-ui', 10) if _IS_MACOS else ('Segoe UI', 9)
SANS_XSMALL = ('system-ui', 9) if _IS_MACOS else ('Segoe UI', 8)
MONO_FONT = ('Menlo', 10) if _IS_MACOS else ('Consolas', 9)
MONO_BOLD = ('Menlo', 10, 'bold') if _IS_MACOS else ('Consolas', 9, 'bold')
TITLE_FONT = ('system-ui', 14, 'bold') if _IS_MACOS else ('Segoe UI', 14, 'bold')


@dataclass
class Action:
    action_type: str
    params: Dict[str, Any]
    thought: str = ""

    def __str__(self):
        return f"{self.action_type}({self.params})"


class CollapsibleSection:
    def __init__(self, text_widget, tag_prefix, header_text):
        self.text = text_widget
        self.tag = f"collapse_{tag_prefix}_{id(self)}"
        self.toggle_tag = f"toggle_{tag_prefix}_{id(self)}"
        self.header_text = header_text
        self.collapsed = False
        self.content = ""
        self.start_index = None
        self.end_index = None

    def insert_header(self):
        self.start_index = self.text.index(tk.INSERT)
        self.text.insert(tk.END, f"▼ {self.header_text}", self.toggle_tag)
        self.text.insert(tk.END, "\n")

    def insert_content(self, content):
        self.content = content
        self.text.insert(tk.END, content, self.tag)

    def finish(self, summary=""):
        self.end_index = self.text.index(tk.END)
        self.content_with_header = self.content
        if summary:
            self.text.insert(tk.END, f"\n→ {summary}\n", 'action')
        self.text.tag_bind(self.toggle_tag, '<Button-1>', lambda e: self.toggle())

    def toggle(self):
        if self.collapsed:
            self.text.tag_configure(self.tag, elide=False)
            self.text.tag_configure(f"{self.tag}_hidden", elide=False)
            self.text.delete(f"{self.start_index} linestart",
                             f"{self.start_index} lineend")
            self.text.insert(f"{self.start_index} linestart",
                             f"▼ {self.header_text}", self.toggle_tag)
            self.collapsed = False
        else:
            self.text.tag_configure(self.tag, elide=True)
            self.text.delete(f"{self.start_index} linestart",
                             f"{self.start_index} lineend")
            self.text.insert(f"{self.start_index} linestart",
                             f"▶ {self.header_text} [点击展开]", self.toggle_tag)
            self.collapsed = True


class MiniGUIAgentApp:
    if _IS_MACOS:
        THEMES = {
            'dark': {
                'bg': '#1e1e1e', 'bg_dark': '#161616', 'accent': '#0a84ff',
                'success': '#30d158', 'warning': '#ff9f0a', 'error': '#ff453a',
                'text': '#f5f5f7', 'text_dim': '#98989d', 'border': '#3a3a3c',
                'reasoning': '#bf5af2', 'input_bg': '#2c2c2e',
            },
            'light': {
                'bg': '#ffffff', 'bg_dark': '#f2f2f7', 'accent': '#007aff',
                'success': '#34c759', 'warning': '#ff9500', 'error': '#ff3b30',
                'text': '#1d1d1f', 'text_dim': '#86868b', 'border': '#d1d1d6',
                'reasoning': '#8944ab', 'input_bg': '#f9f9f9',
            },
        }
    else:
        THEMES = {
            'dark': {
                'bg': '#1a1a2e', 'bg_dark': '#0f0f1a', 'accent': '#6366f1',
                'success': '#10b981', 'warning': '#f59e0b', 'error': '#ef4444',
                'text': '#f8fafc', 'text_dim': '#94a3b8', 'border': '#2d2d44',
                'reasoning': '#c084fc', 'input_bg': '#16213e',
            },
            'light': {
                'bg': '#f1f5f9', 'bg_dark': '#e2e8f0', 'accent': '#4f46e5',
                'success': '#059669', 'warning': '#d97706', 'error': '#dc2626',
                'text': '#1e293b', 'text_dim': '#64748b', 'border': '#cbd5e1',
                'reasoning': '#7c3aed', 'input_bg': '#ffffff',
            },
        }

    def _init_theme(self):
        theme_name = os.getenv('THEME', 'dark')
        self.current_theme = theme_name
        self.COLORS = self.THEMES.get(theme_name, self.THEMES['dark']).copy()

    def __init__(self):
        self._init_theme()
        self.root = tk.Tk()
        self.root.title("GUI Agent")
        self.root.configure(bg=self.COLORS['bg_dark'])
        self.root.attributes('-topmost', True)

        # macOS: native Retina is already handled by Tk 8.6+, no manual scaling needed
        if _IS_MACOS:
            self.root.attributes('-alpha', 0.94)
        else:
            try:
                self.root.attributes('-alpha', 0.92)
            except Exception:
                pass
            try:
                from ctypes import windll
                windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

        self.screen_width, self.screen_height = pyautogui.size()
        win_w, win_h = 400, 540
        x = self.screen_width - win_w - 16
        y = self.screen_height - win_h - 40
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.root.minsize(340, 400)

        self.is_running = False
        self.current_task = ""
        self.iteration_count = 0
        self.max_iterations = 50
        self.conversations = []
        self.MAX_IMAGE_HISTORY = 5
        self.action_history = []
        self.previous_plan = []

        self.configs_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_configs.json")
        self.saved_configs = {}  # name → {api_key, base_url, model}
        self.active_config_name = tk.StringVar(value="")
        self._load_configs()

        # Init with active config values (or .env fallback)
        active = self.saved_configs.get(self.active_config_name.get()) if self.active_config_name.get() else None
        self.api_key_var = tk.StringVar(value=active['api_key'] if active else os.getenv('OPENAI_API_KEY', ''))
        self.base_url_var = tk.StringVar(value=active['base_url'] if active else os.getenv('OPENAI_BASE_URL', ''))
        self.model_var = tk.StringVar(value=active['model'] if active else os.getenv('OPENAI_MODEL', ''))
        self.language = os.getenv('LANGUAGE', 'zh')

        self.drag_data = {'x': 0, 'y': 0}

        self.memory = MemoryStore(
            storage_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_agent_memory.json")
        )

        self.create_widgets()
        self.load_config()
        if _IS_MACOS:
            self.root.after(500, self._check_macos_permissions)

    # ------------------------------------------------------------------
    # macOS input via cliclick (replaces pyautogui mouse/keyboard)
    # ------------------------------------------------------------------
    @staticmethod
    def _cliclick(*args, **kw):
        """Run a cliclick command. Thread-safe (subprocess)."""
        import subprocess
        cmd = [_CLICLICK] + list(args)
        if not cmd[1:]:
            raise RuntimeError("cliclick called with no commands")
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"cliclick failed: {e.stderr.decode().strip()}")

    @staticmethod
    def _osascript(script):
        """Run an AppleScript snippet. Thread-safe. Raises on failure."""
        import subprocess
        r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            err = r.stderr.strip()
            raise RuntimeError(f"AppleScript failed: {err}")

    def _check_macos_permissions(self):
        """Check macOS Accessibility permissions via cliclick."""
        try:
            # cliclick move 1px — will fail if no accessibility permission
            self._cliclick('m:+1,+0')
            self._cliclick('m:-1,+0')
            self.log_system("✅ 辅助功能权限正常")
        except Exception:
            self.log_error("⚠️ 缺少辅助功能权限！鼠标键盘无法操控")
            self.log_system("请前往 系统设置 → 隐私与安全性 → 辅助功能")
            self.log_system(f"找到你的终端 ({self._get_terminal_name()})，开启开关后重启应用")
            if hasattr(self, 'start_btn'):
                self.start_btn._disabled = True
                self.start_btn.config(bg='#6b7280', fg='#9ca3af')

    @staticmethod
    def _get_terminal_name():
        import subprocess
        try:
            r = subprocess.run(['osascript', '-e', 'get name of first process whose frontmost is true'],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip() or "Terminal"
        except Exception:
            return "Terminal"

    # ------------------------------------------------------------------
    # Multi-config storage (api_configs.json)
    # ------------------------------------------------------------------
    def _load_configs(self):
        """Load saved API configs from JSON file."""
        try:
            with open(self.configs_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.saved_configs = data.get('configs', {})
            self.active_config_name.set(data.get('active', ''))
        except (FileNotFoundError, json.JSONDecodeError):
            self.saved_configs = {}
            self.active_config_name.set('')

    def _save_configs(self):
        """Persist configs to JSON file."""
        data = {
            'configs': self.saved_configs,
            'active': self.active_config_name.get(),
        }
        with open(self.configs_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _switch_config(self, name):
        """Switch active config to the named one."""
        cfg = self.saved_configs.get(name)
        if not cfg:
            return
        self.active_config_name.set(name)
        self.api_key_var.set(cfg['api_key'])
        self.base_url_var.set(cfg['base_url'])
        self.model_var.set(cfg['model'])
        self._save_configs()
        self.update_config_display()
        self._update_config_label()
        self.log_system(f"已切换到: {name}")

    def _update_config_label(self):
        """Update the config selector label with current config name."""
        name = self.active_config_name.get()
        self.config_selector_label.config(text=f"▾ {name}" if name else "▾ 选择配置")

    def _show_config_popup(self, event):
        """Show a popup menu for config selection."""
        menu = tk.Menu(self.root, tearoff=0, font=SANS_SMALL,
                       bg=self.COLORS['bg'], fg=self.COLORS['text'],
                       activebackground=self.COLORS['accent'], activeforeground='white')
        names = sorted(self.saved_configs.keys())
        if not names:
            menu.add_command(label="(无已保存配置)", state=tk.DISABLED)
        for name in names:
            marker = " ★" if name == self.active_config_name.get() else ""
            menu.add_command(label=f"{name}{marker}",
                             command=lambda n=name: self._switch_config(n))
        # Show near the label
        x = self.config_selector_label.winfo_rootx()
        y = self.config_selector_label.winfo_rooty() + self.config_selector_label.winfo_height()
        menu.tk_popup(x, y)

    def create_widgets(self):
        main = tk.Frame(self.root, bg=self.COLORS['bg_dark'])
        main.pack(fill=tk.BOTH, expand=True)

        title_bar = tk.Frame(main, bg=self.COLORS['accent'], height=28)
        title_bar.pack(fill=tk.X)
        title_bar.pack_propagate(False)
        title_bar.bind('<Button-1>', self.start_drag)
        title_bar.bind('<B1-Motion>', self.do_drag)

        tk.Label(title_bar, text="🤖 GUI Agent", font=SANS_BOLD,
                 fg='white', bg=self.COLORS['accent']).pack(side=tk.LEFT, padx=10)

        self.status_dot = tk.Canvas(title_bar, width=10, height=10,
                                     bg=self.COLORS['accent'], highlightthickness=0)
        self.status_dot.pack(side=tk.RIGHT, padx=(0, 5))
        self.status_dot.create_oval(2, 2, 8, 8, fill=self.COLORS['success'], outline='')

        self.status_label = tk.Label(title_bar, text="就绪", font=SANS_SMALL,
                                      fg='white', bg=self.COLORS['accent'])
        self.status_label.pack(side=tk.RIGHT, padx=(0, 10))

        min_btn = tk.Label(title_bar, text=" ─ ", font=SANS_SMALL,
                           fg='white', bg=self.COLORS['accent'], cursor='hand2')
        min_btn.pack(side=tk.RIGHT, padx=(0, 2))
        min_btn.bind('<Button-1>', lambda e: self.root.iconify())

        config_frame = tk.Frame(main, bg=self.COLORS['bg'], padx=6, pady=4)
        config_frame.pack(fill=tk.X, padx=5, pady=(4, 0))

        btn_row = tk.Frame(config_frame, bg=self.COLORS['bg'])
        btn_row.pack(fill=tk.X)

        self.config_btn = self._create_btn(btn_row, text="⚙", bg_color=self.COLORS['bg'],
                                            fg_color=self.COLORS['text'], font=SANS_SMALL,
                                            padx=4, pady=1, command=self.open_config_dialog)
        self.config_btn.pack(side=tk.LEFT, padx=2)

        self.test_btn = self._create_btn(btn_row, text="🔗", bg_color=self.COLORS['bg'],
                                          fg_color=self.COLORS['text'], font=SANS_SMALL,
                                          padx=4, pady=1, command=self.test_api_connection)
        self.test_btn.pack(side=tk.LEFT, padx=2)

        self.config_info = tk.Label(config_frame, text="未配置 API", font=SANS_XSMALL,
                                     fg=self.COLORS['text_dim'], bg=self.COLORS['bg'],
                                     wraplength=280, justify=tk.LEFT)
        self.config_info.pack(fill=tk.X, pady=(4, 0))

        # Config selector — custom clickable label (OptionMenu ignores colors on macOS)
        selector_frame = tk.Frame(main, bg=self.COLORS['bg_dark'])
        selector_frame.pack(fill=tk.X, padx=8, pady=(4, 0))
        tk.Label(selector_frame, text="配置", font=SANS_XSMALL,
                 fg=self.COLORS['text_dim'], bg=self.COLORS['bg_dark']).pack(side=tk.LEFT, padx=(0, 4))

        self.config_selector_label = tk.Label(selector_frame, text="(无)", font=SANS_SMALL,
                                               bg=self.COLORS['bg'], fg=self.COLORS['text'],
                                               anchor=tk.W, padx=6, pady=2,
                                               relief='solid', bd=1,
                                               highlightbackground=self.COLORS['border'])
        self.config_selector_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.config_selector_label.bind('<Button-1>', self._show_config_popup)
        self._update_config_label()

        task_frame = tk.Frame(main, bg=self.COLORS['bg'], padx=6, pady=4)
        task_frame.pack(fill=tk.X, padx=5, pady=(3, 0))

        self.task_entry = tk.Entry(task_frame, font=SANS_FONT,
                                    bg=self.COLORS.get('input_bg', self.COLORS['bg_dark']),
                                    fg=self.COLORS['text'],
                                    insertbackground=self.COLORS['text'],
                                    relief='solid', bd=1, highlightthickness=1,
                                    highlightbackground=self.COLORS['border'],
                                    highlightcolor=self.COLORS['accent'])
        self.task_entry.pack(fill=tk.X)
        self.task_entry.insert(0, '输入任务...')
        self.task_entry.bind('<FocusIn>', self.clear_placeholder)
        self.task_entry.bind('<FocusOut>', self.add_placeholder)
        self.task_entry.bind('<Return>', lambda e: self.start_task())

        ctrl_frame = tk.Frame(main, bg=self.COLORS['bg_dark'], padx=5, pady=2)
        ctrl_frame.pack(fill=tk.X, padx=5)

        self.start_btn = self._create_btn(ctrl_frame, text="▶ 开始", bg_color=self.COLORS['success'],
                                           fg_color='white', font=SANS_BOLD,
                                           padx=14, pady=5, command=self.start_task)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.stop_btn = self._create_btn(ctrl_frame, text="⏹ 停止", bg_color=self.COLORS['error'],
                                          fg_color='white', font=SANS_SMALL,
                                          padx=14, pady=5, command=self.stop_task)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.new_btn = self._create_btn(ctrl_frame, text="🔄 新会话", bg_color=self.COLORS['bg'],
                                         fg_color=self.COLORS['text'], font=SANS_SMALL,
                                         padx=10, pady=5, command=self.new_session)
        self.new_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.iter_label = tk.Label(ctrl_frame, text="0/50", font=SANS_SMALL,
                                    fg=self.COLORS['text_dim'], bg=self.COLORS['bg_dark'])
        self.iter_label.pack(side=tk.RIGHT)

        thought_label = tk.Label(main, text="💭 思考过程", font=SANS_BOLD,
                                  fg=self.COLORS['accent'], bg=self.COLORS['bg_dark'])
        thought_label.pack(anchor=tk.W, padx=8, pady=(5, 1))

        text_frame = tk.Frame(main, bg=self.COLORS['bg_dark'])
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 4))

        self.thought_text = scrolledtext.ScrolledText(
            text_frame, wrap=tk.WORD, font=MONO_FONT,
            bg=self.COLORS['bg'], fg=self.COLORS['text'],
            insertbackground=self.COLORS['text'], relief='flat',
            padx=6, pady=4, state=tk.NORMAL
        )
        self.thought_text.pack(fill=tk.BOTH, expand=True)

        self.thought_text.tag_config('thought', foreground='#818cf8', font=MONO_BOLD)
        self.thought_text.tag_config('action', foreground=self.COLORS['success'])
        self.thought_text.tag_config('system', foreground=self.COLORS['text_dim'])
        self.thought_text.tag_config('error', foreground=self.COLORS['error'])
        self.thought_text.tag_config('step', foreground=self.COLORS['warning'])
        self.thought_text.tag_config('reasoning', foreground=self.COLORS['reasoning'])
        self.thought_text.tag_config('streaming', foreground=self.COLORS['text_dim'])
        self.thought_text.tag_config('toggle', foreground=self.COLORS['accent'],
                                      font=MONO_BOLD)

        bottom = tk.Frame(main, bg=self.COLORS['bg_dark'], padx=5, pady=2)
        bottom.pack(fill=tk.X)

        self._create_btn(bottom, text="清空", bg_color=self.COLORS['bg'],
                         fg_color=self.COLORS['text_dim'], font=SANS_XSMALL,
                         padx=8, pady=2, command=self.clear_logs).pack(side=tk.LEFT)

        self._create_btn(bottom, text="复制", bg_color=self.COLORS['bg'],
                         fg_color=self.COLORS['text_dim'], font=SANS_XSMALL,
                         padx=8, pady=2, command=self.copy_logs).pack(side=tk.LEFT, padx=4)

        # initialize button states
        self.update_ui_state()

    def _create_btn(self, parent, text, bg_color, fg_color, font, command,
                    padx=12, pady=6, side=None, **kw):
        """Cross-platform button: tk.Label on macOS (respects bg), tk.Button on Windows."""
        if _IS_MACOS:
            btn = tk.Label(parent, text=text, font=font, bg=bg_color, fg=fg_color,
                           padx=padx, pady=pady, cursor='hand2', bd=0, **kw)
            # store original colors and disabled state
            btn._orig_bg = bg_color
            btn._orig_fg = fg_color
            btn._disabled = False
            if command is not None:
                btn._cmd = command
                btn.bind('<Button-1>', lambda e: btn._cmd() if not btn._disabled else None)
            else:
                btn._cmd = None
            # hover feedback (only when enabled)
            def _on_enter(e, b=btn):
                if not b._disabled:
                    b.config(relief='solid', bd=1)
            def _on_leave(e, b=btn):
                b.config(relief='flat', bd=0)
            btn.bind('<Enter>', _on_enter)
            btn.bind('<Leave>', _on_leave)
        else:
            btn = tk.Button(parent, text=text, font=font, bg=bg_color, fg=fg_color,
                            activebackground=bg_color, bd=0, padx=padx, pady=pady, cursor='hand2',
                            command=command, **kw)
        return btn

    def start_drag(self, event):
        self.drag_data['x'] = event.x
        self.drag_data['y'] = event.y

    def do_drag(self, event):
        x = self.root.winfo_x() + event.x - self.drag_data['x']
        y = self.root.winfo_y() + event.y - self.drag_data['y']
        self.root.geometry(f"+{x}+{y}")

    def clear_placeholder(self, event):
        if self.task_entry.get() == '输入任务...':
            self.task_entry.delete(0, tk.END)
            self.task_entry.config(fg=self.COLORS['text'])

    def add_placeholder(self, event):
        if not self.task_entry.get():
            self.task_entry.insert(0, '输入任务...')
            self.task_entry.config(fg=self.COLORS['text_dim'])

    def open_config_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("API 配置管理")
        dialog.configure(bg=self.COLORS['bg_dark'])
        dialog.transient(self.root)
        try:
            dialog.attributes('-type', 'utility')
        except Exception:
            pass
        dialog.attributes('-topmost', True)
        dialog.grab_set()

        win_w, win_h = 480, 600
        x = self.root.winfo_x() + (self.root.winfo_width() - win_w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - win_h) // 2
        x = max(0, min(x, self.screen_width - win_w))
        y = max(0, min(y, self.screen_height - win_h))
        dialog.geometry(f"{win_w}x{win_h}+{x}+{y}")
        dialog.minsize(420, 500)

        self.root.attributes('-topmost', False)
        def _restore_topmost():
            self.root.attributes('-topmost', True)
        dialog.bind('<Destroy>', lambda e: self.root.after(100, _restore_topmost))
        dialog.lift(self.root)
        dialog.focus_force()

        container = tk.Frame(dialog, bg=self.COLORS['bg_dark'])
        container.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)

        tk.Label(container, text="API 配置管理", font=TITLE_FONT,
                 fg=self.COLORS['text'], bg=self.COLORS['bg_dark']).pack(anchor=tk.W, pady=(0, 6))

        # --- Saved configs list ---
        list_frame = tk.Frame(container, bg=self.COLORS['bg'], bd=1,
                              highlightbackground=self.COLORS['border'], highlightthickness=1)
        list_frame.pack(fill=tk.X, pady=(0, 8))

        tk.Label(list_frame, text="已保存的配置", font=SANS_SMALL,
                 fg=self.COLORS['text_dim'], bg=self.COLORS['bg']).pack(anchor=tk.W, padx=6, pady=(4, 0))

        self._config_listbox = tk.Listbox(list_frame, font=SANS_SMALL, height=4,
                                           bg=self.COLORS['bg'], fg=self.COLORS['text'],
                                           selectbackground=self.COLORS['accent'],
                                           selectforeground='white',
                                           relief='flat', bd=0,
                                           activestyle='none')
        self._config_listbox.pack(fill=tk.X, padx=4, pady=(2, 4))
        self._refresh_config_listbox()
        self._config_listbox.bind('<<ListboxSelect>>', self._on_config_list_select)

        # --- Config name ---
        tk.Label(container, text="配置名称", font=SANS_SMALL,
                 fg=self.COLORS['text_dim'], bg=self.COLORS['bg_dark']).pack(anchor=tk.W)
        self._cfg_name_var = tk.StringVar()
        tk.Entry(container, textvariable=self._cfg_name_var, font=SANS_FONT,
                 bg=self.COLORS.get('input_bg', self.COLORS['bg']), fg=self.COLORS['text'],
                 insertbackground=self.COLORS['text'],
                 relief='solid', bd=1, highlightthickness=1,
                 highlightbackground=self.COLORS['border'],
                 highlightcolor=self.COLORS['accent']).pack(fill=tk.X, pady=(2, 6))

        # --- API fields ---
        entry_bg = self.COLORS.get('input_bg', self.COLORS['bg'])
        entry_kw = dict(font=SANS_FONT, bg=entry_bg, fg=self.COLORS['text'],
                        insertbackground=self.COLORS['text'],
                        relief='solid', bd=1, highlightthickness=1,
                        highlightbackground=self.COLORS['border'],
                        highlightcolor=self.COLORS['accent'])

        tk.Label(container, text="API Key", font=SANS_SMALL,
                 fg=self.COLORS['text_dim'], bg=self.COLORS['bg_dark']).pack(anchor=tk.W)
        self._cfg_api_var = tk.StringVar(value=self.api_key_var.get())
        tk.Entry(container, textvariable=self._cfg_api_var, show='•', **entry_kw).pack(fill=tk.X, pady=(2, 4))

        tk.Label(container, text="Base URL", font=SANS_SMALL,
                 fg=self.COLORS['text_dim'], bg=self.COLORS['bg_dark']).pack(anchor=tk.W)
        self._cfg_url_var = tk.StringVar(value=self.base_url_var.get())
        tk.Entry(container, textvariable=self._cfg_url_var, **entry_kw).pack(fill=tk.X, pady=(2, 4))

        tk.Label(container, text="Model", font=SANS_SMALL,
                 fg=self.COLORS['text_dim'], bg=self.COLORS['bg_dark']).pack(anchor=tk.W)
        self._cfg_model_var = tk.StringVar(value=self.model_var.get())
        tk.Entry(container, textvariable=self._cfg_model_var, **entry_kw).pack(fill=tk.X, pady=(2, 4))

        # Max iterations + theme (compact row)
        aux_frame = tk.Frame(container, bg=self.COLORS['bg_dark'])
        aux_frame.pack(fill=tk.X, pady=(6, 0))

        tk.Label(aux_frame, text="最大轮数", font=SANS_SMALL,
                 fg=self.COLORS['text_dim'], bg=self.COLORS['bg_dark']).pack(side=tk.LEFT)
        self._cfg_iter_var = tk.StringVar(value=str(self.max_iterations))
        tk.Entry(aux_frame, textvariable=self._cfg_iter_var, font=SANS_SMALL, width=5,
                 bg=entry_bg, fg=self.COLORS['text'], insertbackground=self.COLORS['text'],
                 relief='solid', bd=1, highlightthickness=1,
                 highlightbackground=self.COLORS['border'],
                 highlightcolor=self.COLORS['accent']).pack(side=tk.LEFT, padx=(4, 12))

        tk.Label(aux_frame, text="主题", font=SANS_SMALL,
                 fg=self.COLORS['text_dim'], bg=self.COLORS['bg_dark']).pack(side=tk.LEFT)
        self._cfg_theme_var = tk.StringVar(value=self.current_theme)
        tk.Radiobutton(aux_frame, text="深色", variable=self._cfg_theme_var, value="dark",
                       font=SANS_XSMALL, fg=self.COLORS['text'], bg=self.COLORS['bg_dark'],
                       selectcolor=self.COLORS['border']).pack(side=tk.LEFT, padx=(4, 4))
        tk.Radiobutton(aux_frame, text="浅色", variable=self._cfg_theme_var, value="light",
                       font=SANS_XSMALL, fg=self.COLORS['text'], bg=self.COLORS['bg_dark'],
                       selectcolor=self.COLORS['border']).pack(side=tk.LEFT)

        # --- Action buttons ---
        btn_frame = tk.Frame(container, bg=self.COLORS['bg_dark'])
        btn_frame.pack(fill=tk.X, pady=(12, 0))

        self._create_btn(btn_frame, text="💾 保存为新配置", bg_color=self.COLORS['success'],
                         fg_color='white', font=SANS_SMALL, padx=12, pady=5,
                         command=self._save_as_new_config).pack(side=tk.LEFT, padx=(0, 4))

        self._create_btn(btn_frame, text="✅ 使用此配置", bg_color=self.COLORS['accent'],
                         fg_color='white', font=SANS_SMALL, padx=12, pady=5,
                         command=lambda: self._apply_and_close(dialog)).pack(side=tk.LEFT, padx=(0, 4))

        self._create_btn(btn_frame, text="🗑 删除选中", bg_color=self.COLORS['error'],
                         fg_color='white', font=SANS_SMALL, padx=12, pady=5,
                         command=self._delete_selected_config).pack(side=tk.LEFT, padx=(0, 4))

        self._create_btn(btn_frame, text="取消", bg_color=self.COLORS['bg'],
                         fg_color=self.COLORS['text_dim'], font=SANS_SMALL,
                         padx=12, pady=5, command=dialog.destroy).pack(side=tk.RIGHT)

    # -- Config dialog helpers --
    def _refresh_config_listbox(self):
        self._config_listbox.delete(0, 'end')
        for name in sorted(self.saved_configs.keys()):
            marker = " ★" if name == self.active_config_name.get() else ""
            self._config_listbox.insert('end', f"{name}{marker}")

    def _on_config_list_select(self, event):
        sel = self._config_listbox.curselection()
        if not sel:
            return
        text = self._config_listbox.get(sel[0]).rstrip(' ★')
        cfg = self.saved_configs.get(text)
        if cfg:
            self._cfg_name_var.set(text)
            self._cfg_api_var.set(cfg['api_key'])
            self._cfg_url_var.set(cfg['base_url'])
            self._cfg_model_var.set(cfg['model'])

    def _save_as_new_config(self):
        name = self._cfg_name_var.get().strip()
        if not name:
            self.log_error("请输入配置名称")
            return
        self.saved_configs[name] = {
            'api_key': self._cfg_api_var.get(),
            'base_url': self._cfg_url_var.get(),
            'model': self._cfg_model_var.get(),
        }
        self._save_configs()
        self._refresh_config_listbox()
        self._update_config_label()
        self.log_system(f"配置已保存: {name}")

    def _apply_and_close(self, dialog):
        name = self._cfg_name_var.get().strip()
        if name and self._cfg_api_var.get():
            # Save current fields first if named
            self.saved_configs[name] = {
                'api_key': self._cfg_api_var.get(),
                'base_url': self._cfg_url_var.get(),
                'model': self._cfg_model_var.get(),
            }
        # Apply to active vars
        self.api_key_var.set(self._cfg_api_var.get())
        self.base_url_var.set(self._cfg_url_var.get())
        self.model_var.set(self._cfg_model_var.get())
        if name:
            self.active_config_name.set(name)
        self._save_configs()
        try:
            new_max = int(self._cfg_iter_var.get())
            if 1 <= new_max <= 200:
                self.max_iterations = new_max
                self.iter_label.config(text=f"0/{self.max_iterations}")
        except ValueError:
            pass
        new_theme = self._cfg_theme_var.get()
        if new_theme != self.current_theme:
            self._apply_theme(new_theme)
        self.update_config_display()
        self._update_config_label()
        dialog.destroy()
        self.log_system("配置已应用")

    def _delete_selected_config(self):
        sel = self._config_listbox.curselection()
        if not sel:
            return
        name = self._config_listbox.get(sel[0]).rstrip(' ★')
        if name in self.saved_configs:
            del self.saved_configs[name]
            if self.active_config_name.get() == name:
                self.active_config_name.set('')
            self._save_configs()
            self._refresh_config_listbox()
            self._update_config_label()
            self._cfg_name_var.set('')
            self.log_system(f"已删除配置: {name}")

    def _apply_theme(self, theme_name):
        self.current_theme = theme_name
        self.COLORS = self.THEMES.get(theme_name, self.THEMES['dark']).copy()
        self.root.configure(bg=self.COLORS['bg_dark'])
        self._rebuild_ui()
        self.log_system(f"已切换到{'浅色' if theme_name == 'light' else '深色'}主题")

    def _rebuild_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self.create_widgets()
        self.update_config_display()
        self.iter_label.config(text=f"{self.iteration_count}/{self.max_iterations}")

    def test_api_connection(self):
        self.log_system("测试 API 连接...")
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key_var.get()}",
                "Content-Type": "application/json"
            }
            payload = {"model": self.model_var.get(), "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            response = requests.post(
                f"{self.base_url_var.get().rstrip('/')}/chat/completions",
                headers=headers, json=payload, timeout=30
            )
            if response.status_code == 200:
                self.log_system("✅ API 连接成功")
            else:
                self.log_error(f"API 错误: {response.text[:100]}")
        except Exception as e:
            self.log_error(f"连接失败: {e}")

    def load_config(self):
        self.max_iterations = int(os.getenv('MAX_ITERATIONS', '50'))
        self.update_config_display()

    def update_config_display(self):
        name = self.active_config_name.get()
        model = self.model_var.get()
        if name and model:
            self.config_info.config(text=f"当前: {name}  |  {model}")
        elif model:
            self.config_info.config(text=f"当前: {model}")
        else:
            self.config_info.config(text="未配置 API — 点击 ⚙ 添加")

    def save_config(self):
        """Persist current config + theme to .env (used as initial fallback)."""
        try:
            env_path = find_dotenv() or '.env'
            set_key(env_path, 'OPENAI_API_KEY', self.api_key_var.get())
            set_key(env_path, 'OPENAI_BASE_URL', self.base_url_var.get())
            set_key(env_path, 'OPENAI_MODEL', self.model_var.get())
            set_key(env_path, 'MAX_ITERATIONS', str(self.max_iterations))
            set_key(env_path, 'THEME', self.current_theme)
            self._save_configs()     # also save JSON configs
            self.update_config_display()
        except Exception as e:
            self.log_error(f"保存失败: {e}")

    def log_system(self, message: str):
        self.thought_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n", 'system')
        self.thought_text.see(tk.END)
        self.root.update_idletasks()

    def log_step(self, step: int, total: int):
        self.thought_text.insert(tk.END, f"\n{'='*25} Step {step}/{total} {'='*25}\n", 'step')
        self.thought_text.see(tk.END)
        self.root.update_idletasks()

    def log_error(self, message: str):
        self.thought_text.insert(tk.END, f"❌ {message}\n", 'error')
        self.thought_text.see(tk.END)
        self.root.update_idletasks()

    def take_screenshot_base64(self) -> str:
        screenshot = pyautogui.screenshot()
        if screenshot.mode == 'RGBA':
            screenshot = screenshot.convert('RGB')
        # Resize screenshot to match screen dimensions exactly.
        # This ensures screenshot pixels == screen coordinates, so the model's
        # pixel coordinates map 1:1 to pyautogui move/click targets.
        screenshot = screenshot.resize((self.screen_width, self.screen_height), Image.Resampling.LANCZOS)
        self._screenshot_dims = (screenshot.width, screenshot.height)

        # Save to disk for debugging
        if hasattr(self, '_screenshot_dir') and self._screenshot_dir:
            try:
                self._screenshot_idx += 1
                path = os.path.join(self._screenshot_dir,
                                    f'step{self._screenshot_idx:02d}_{self.iteration_count:02d}.jpg')
                screenshot.save(path, format='JPEG', quality=85)
            except Exception:
                pass

        buffer = io.BytesIO()
        screenshot.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)
        b64 = base64.b64encode(buffer.read()).decode()
        self.log_system(f"截图: {screenshot.size[0]}x{screenshot.size[1]}, {len(b64)//1024}KB")
        return b64

    def get_system_prompt(self) -> str:
        action_space = '\n'.join([
            "click - 单击 (start_point: [x, y])",
            "left_double - 双击 (start_point: [x, y])",
            "right_single - 右键 (start_point: [x, y])",
            "drag - 拖拽 (start_point, end_point)",
            "hotkey - 快捷键 (key: 'ctrl c')",
            "type - 输入文本 (content: 'xxx')",
            "scroll - 滚动 (start_point, direction)",
            "wait - 等待",
            "finished - 完成",
            "call_user - 求助",
        ])
        return f"""You are a GUI agent. Execute tasks on screen by outputting JSON actions.

## Output Format (SINGLE JSON, no markdown, no extra text)
{{"thought": "简短分析", "action": "类型", "参数": "值"}}

For multi-step operations (e.g. click input box then type then press enter), output a SEQUENCE:
{{"thought": "点击搜索框输入库里并搜索", "actions": [
  {{"action": "click", "start_point": [0.5, 0.4]}},
  {{"action": "type", "content": "库里"}},
  {{"action": "hotkey", "key": "enter"}}
]}}

## Actions
click/start_point=[x,y] | left_double/start_point=[x,y] | type/content="text" | hotkey/key="enter" | scroll/start_point+direction | finished

## Platform & Screen
- OS: {'macOS' if _IS_MACOS else 'Windows'}
- Screen: {self.screen_width}x{self.screen_height}
- The screenshot you see is exactly {self.screen_width}x{self.screen_height} pixels — it matches the screen pixel-for-pixel
- ⚠️ CRITICAL: You MUST use NORMALIZED coordinates [x, y] where 0.0 ≤ x,y ≤ 1.0
  - [0.0, 0.0] = top-left corner
  - [0.5, 0.5] = center of screen
  - [1.0, 1.0] = bottom-right corner
  - Example: a folder at 30% from left, 35% from top → [0.30, 0.35]
- You MAY output absolute pixel coordinates like [440, 320] — these map directly to screen pixels
- Never output coordinates outside the 0-1 range unless you mean absolute pixels below {self.screen_width}/{self.screen_height}

## Rules
- Open desktop apps/folders: use left_double, NOT click
- To type in a text field: click it first, then type
- After type, press enter to submit
- Use multi-step actions for efficiency (click+type+enter = 1 response)
- Keep thought SHORT (1 sentence), focus on action
- If previous action didn't work, try DIFFERENT coordinates or approach
- ⚠️ CRITICAL: When the task is DONE, output action "finished" — do NOT repeat previous actions
  Example: {{"thought": "任务已完成", "action": "finished"}}
- Output ONLY the JSON, nothing else. Do NOT output extra fields beyond thought/action/params.

## User Instruction
"""

    def _build_action_history_text(self) -> str:
        if not self.action_history:
            return ""
        lines = ["[Action History - 已执行的操作]"]
        for h in self.action_history[-6:]:
            repeat_warn = ""
            if h['repeat_count'] > 0:
                repeat_warn = f" ⚠️ REPEATED {h['repeat_count']}x - DO NOT repeat!"
            lines.append(f"Step {h['step']}: {h['action']}({h['params']}) → {h['result']}{repeat_warn}")
        
        stuck = self._detect_stuck()
        if stuck:
            lines.append("")
            lines.append("🚨 STUCK DETECTED: 相同操作重复2次以上未生效！")
            lines.append("你必须立即换一种完全不同的方法：")
            lines.append("- 用键盘快捷键代替鼠标点击 (如 Cmd+L 聚焦地址栏)")
            lines.append("- 搜索不同的UI元素 (按钮、菜单、输入框)")
            lines.append("- 用 hotkey 动作代替 click 动作")
            lines.append("- 滚动页面查找其他可交互元素")
            lines.append("绝对不要重复之前失败的坐标和动作！")
        
        return "\n".join(lines)

    def _detect_stuck(self) -> bool:
        if len(self.action_history) < 2:
            return False
        recent = self.action_history[-2:]
        return all(h['repeat_count'] >= 1 for h in recent)

    def call_llm_stream(self, instruction: str, section: CollapsibleSection) -> tuple:
        headers = {
            "Authorization": f"Bearer {self.api_key_var.get()}",
            "Content-Type": "application/json"
        }

        history_text = self._build_action_history_text()
        memory_context = self.memory.get_context_for_task(instruction)
        
        system_text = self.get_system_prompt() + instruction
        if memory_context:
            system_text += "\n\n" + memory_context
        if history_text:
            system_text += "\n\n" + history_text
        
        messages = [{"role": "system", "content": system_text}]

        for item in self.conversations[:-1]:
            if item['role'] == 'assistant':
                messages.append({"role": "assistant", "content": item['text']})
            elif item['role'] == 'user':
                desc = item.get('desc', '屏幕截图已更新')
                messages.append({"role": "user", "content": desc})

        latest = self.conversations[-1]
        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{latest['image']}"}},
                {"type": "text", "text": "当前屏幕截图，请分析并执行操作。"}
            ]
        })

        payload = {
            "model": self.model_var.get(),
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": True
        }

        self.log_system(f"发送 {len(messages)} 条消息")

        reasoning_text = ""
        content_text = ""
        in_reasoning = True

        try:
            response = requests.post(
                f"{self.base_url_var.get().rstrip('/')}/chat/completions",
                headers=headers, json=payload, timeout=180, stream=True
            )

            if response.status_code != 200:
                # Truncate HTML error pages to a readable one-liner
                err_text = response.text[:200]
                if '<!DOCTYPE' in err_text or '<html' in err_text:
                    err_text = f"HTTP {response.status_code} — 服务端返回了网页而非 API 响应，请检查 Base URL 是否正确、模型服务是否在运行"
                self.log_error(f"API错误 ({response.status_code}): {err_text[:150]}")
                raise Exception(f"API返回 {response.status_code}")

            for line in response.iter_lines():
                if not line:
                    continue
                line = line.decode('utf-8')
                if not line.startswith('data: '):
                    continue
                data_str = line[6:]
                if data_str.strip() == '[DONE]':
                    break

                try:
                    chunk = json.loads(data_str)
                    choices = chunk.get('choices', [])
                    if not choices:
                        continue
                    delta = choices[0].get('delta', {})

                    rc = delta.get('reasoning_content', '')
                    cc = delta.get('content', '')

                    if rc:
                        reasoning_text += rc
                        section.text.insert(tk.END, rc, 'reasoning')
                        section.text.see(tk.END)
                        self.root.update_idletasks()

                    if cc:
                        if in_reasoning and reasoning_text:
                            section.text.insert(tk.END, "\n\n", 'streaming')
                            in_reasoning = False
                        content_text += cc
                        section.text.insert(tk.END, cc, 'streaming')
                        section.text.see(tk.END)
                        self.root.update_idletasks()

                except json.JSONDecodeError:
                    continue

            return content_text, reasoning_text

        except requests.exceptions.Timeout:
            self.log_error("API请求超时")
            raise
        except requests.exceptions.ConnectionError:
            self.log_error("网络连接失败")
            raise

    def _parse_json_action(self, data: dict) -> Action:
        action_type = data.get("action", "")
        if action_type == "input":
            action_type = "type"
        params = {}
        thought = data.get("thought", "")
        
        sp = data.get("start_point", data.get("start_box", None))
        ep = data.get("end_point", data.get("end_box", None))

        # UI-TARS model uses "params" key for coordinates
        if sp is None and ep is None:
            p = data.get("params")
            if isinstance(p, list) and len(p) >= 2:
                if action_type in ("scroll",):
                    # scroll(params=[x, y]) — first value isn't a coordinate
                    pass
                else:
                    sp = p[:2]
        
        if sp and isinstance(sp, list):
            if len(sp) == 2:
                x, y = sp
                if 0 <= x <= 1 and 0 <= y <= 1:
                    # Normalized coordinates → convert to screen pixels
                    x = int(x * self.screen_width)
                    y = int(y * self.screen_height)
                else:
                    # Absolute pixel coordinates — screenshot is already resized
                    # to screen dimensions, so pixel values ARE screen coordinates
                    x, y = int(x), int(y)
                params['box'] = [x, y, x, y]
            elif len(sp) == 4:
                params['box'] = [int(c) for c in sp]

        if ep and isinstance(ep, list):
            if len(ep) == 2:
                x, y = ep
                if 0 <= x <= 1 and 0 <= y <= 1:
                    x = int(x * self.screen_width)
                    y = int(y * self.screen_height)
                else:
                    x, y = int(x), int(y)
                params['end_box'] = [x, y, x, y]
            elif len(ep) == 4:
                params['end_box'] = [int(c) for c in ep]
        
        if action_type == "type":
            params['content'] = data.get("content", data.get("text", ""))
        if action_type == "hotkey":
            k = data.get("key", data.get("keys", ""))
            if not k:
                # UI-TARS model may use "params": "enter" or "params": ["ctrl o"]
                p = data.get("params", "")
                if isinstance(p, list):
                    k = ' '.join(str(x) for x in p) if p else ""
                elif isinstance(p, str) and p:
                    k = p
            params['keys'] = k.split() if isinstance(k, str) else k
        if action_type == "scroll":
            params['direction'] = data.get("direction", "down")
        
        return Action(action_type, params, thought)
    
    def parse_box(self, box_str: str) -> list:
        coords = [float(x.strip()) for x in box_str.split(',')]
        if len(coords) == 2:
            if all(0 <= c <= 1 for c in coords):
                x = int(coords[0] * self.screen_width)
                y = int(coords[1] * self.screen_height)
            else:
                x, y = int(coords[0]), int(coords[1])
            return [x, y, x, y]
        if all(0 <= c <= 1 for c in coords):
            coords[0] = int(coords[0] * self.screen_width)
            coords[1] = int(coords[1] * self.screen_height)
            coords[2] = int(coords[2] * self.screen_width)
            coords[3] = int(coords[3] * self.screen_height)
        else:
            coords = [int(c) for c in coords]
        return coords

    def parse_actions(self, response: str) -> List[Action]:
        cleaned = re.sub(r'<\|[^|]*?\|>', '', response).strip()
        cleaned = re.sub(r'```(?:json)?\s*', '', cleaned).strip()
        cleaned = re.sub(r'```$', '', cleaned).strip()
        # Fix missing commas between JSON key-value pairs (UI-TARS model quirk)
        cleaned = re.sub(r'"\s*\n\s*"', r'",\n"', cleaned)
        # Fix full-width comma (，) that breaks JSON
        cleaned = cleaned.replace('，', ',')
        # Normalize Chinese quotes to avoid JSON string boundary confusion
        cleaned = cleaned.replace('“', "'").replace('”', "'")  # ""
        cleaned = cleaned.replace('‘', "'").replace('’', "'")  # ''
        
        actions_json = re.search(r'\{.*"actions"\s*:\s*\[.*\].*\}', cleaned, re.DOTALL)
        if actions_json:
            try:
                data = json.loads(actions_json.group())
                if "actions" in data:
                    thought = data.get("thought", "")
                    result = []
                    for item in data["actions"]:
                        a = self._parse_json_action(item)
                        if not a.thought:
                            a.thought = thought
                        result.append(a)
                    return result
            except json.JSONDecodeError:
                pass
        
        single = self.parse_action(response)
        return [single]

    def parse_action(self, response: str) -> Action:
        cleaned = re.sub(r'<\|[^|]*?\|>', '', response).strip()
        cleaned = re.sub(r'```(?:json)?\s*', '', cleaned).strip()
        cleaned = re.sub(r'```$', '', cleaned).strip()
        # Fix missing commas between JSON key-value pairs
        cleaned = re.sub(r'"\s*\n\s*"', r'",\n"', cleaned)
        cleaned = cleaned.replace('，', ',')
        cleaned = cleaned.replace('“', "'").replace('”', "'")
        cleaned = cleaned.replace('‘', "'").replace('’', "'")

        json_matches = re.findall(r'\{[^{}]*\}', cleaned)
        if json_matches:
            last_json = json_matches[-1]
            try:
                data = json.loads(last_json)
                if "action" in data:
                    return self._parse_json_action(data)
            except json.JSONDecodeError:
                pass
        
        thought_match = re.search(r'Thought:\s*(.+?)(?=Action:|$)', cleaned, re.DOTALL)
        reflection_match = re.search(r'Reflection:\s*(.+?)(?=Action_Summary:|Action:|$)', cleaned, re.DOTALL)
        summary_match = re.search(r'Action_Summary:\s*(.+?)(?=Action:|$)', cleaned, re.DOTALL)
        action_match = re.search(r'Action:\s*(.+)', cleaned)

        if reflection_match:
            thought = f"[反思] {reflection_match.group(1).strip()}"
            if summary_match:
                thought += f"\n[计划] {summary_match.group(1).strip()}"
        else:
            thought = thought_match.group(1).strip() if thought_match else ""

        action_str = action_match.group(1).strip() if action_match else ""
        action_str = re.sub(r'<\|[^|]*?\|>', '', action_str).strip()
        action_type = ""
        params = {}

        if action_str.startswith("click("):
            action_type = "click"
            m = re.search(r"start_box='?\[([^\]]+)\]'?", action_str)
            if m: params['box'] = self.parse_box(m.group(1))
        elif action_str.startswith("left_double("):
            action_type = "left_double"
            m = re.search(r"start_box='?\[([^\]]+)\]'?", action_str)
            if m: params['box'] = self.parse_box(m.group(1))
        elif action_str.startswith("right_single("):
            action_type = "right_single"
            m = re.search(r"start_box='?\[([^\]]+)\]'?", action_str)
            if m: params['box'] = self.parse_box(m.group(1))
        elif action_str.startswith("drag("):
            action_type = "drag"
            s = re.search(r"start_box='?\[([^\]]+)\]'?", action_str)
            e = re.search(r"end_box='?\[([^\]]+)\]'?", action_str)
            if s and e:
                params['start_box'] = self.parse_box(s.group(1))
                params['end_box'] = self.parse_box(e.group(1))
        elif action_str.startswith("hotkey("):
            action_type = "hotkey"
            m = re.search(r"key='?([^']+)'?", action_str)
            if m: params['keys'] = m.group(1).split()
        elif action_str.startswith("type("):
            action_type = "type"
            m = re.search(r"content='([^']*)'", action_str)
            if not m: m = re.search(r'content="([^"]*)"', action_str)
            if m: params['content'] = m.group(1)
        elif action_str.startswith("scroll("):
            action_type = "scroll"
            b = re.search(r"start_box='?\[([^\]]+)\]'?", action_str)
            d = re.search(r"direction='?(\w+)'?", action_str)
            if b: params['box'] = self.parse_box(b.group(1))
            if d: params['direction'] = d.group(1)
        elif action_str.startswith("wait("):
            action_type = "wait"
        elif action_str.startswith("finished("):
            action_type = "finished"
        elif action_str.startswith("call_user("):
            action_type = "call_user"

        return Action(action_type, params, thought)

    def execute_action(self, action: Action) -> bool:
        cl = self._cliclick if _IS_MACOS else None
        try:
            if action.action_type == "click":
                if 'box' in action.params:
                    x1, y1, x2, y2 = action.params['box']
                    x, y = (x1 + x2) // 2, (y1 + y2) // 2
                    if cl:
                        cl(f'm:{x},{y}', f'w:50', f'c:{x},{y}')
                    else:
                        pyautogui.moveTo(x, y, duration=0.2)
                        time.sleep(0.1)
                        pyautogui.click(x, y)
                    self.thought_text.insert(tk.END, f"  🎯 click({x}, {y})\n", 'action')

            elif action.action_type == "left_double":
                if 'box' in action.params:
                    x1, y1, x2, y2 = action.params['box']
                    x, y = (x1 + x2) // 2, (y1 + y2) // 2
                    if cl:
                        # Single click to select + Cmd+O to open — more reliable
                        # than double-click on macOS Desktop/Finder
                        cl(f'm:{x},{y}', 'w:80', f'c:{x},{y}', 'w:200',
                           'kd:cmd', 't:o', 'ku:cmd',
                           'ku:cmd', 'ku:ctrl', 'ku:alt', 'ku:shift')
                    else:
                        pyautogui.moveTo(x, y, duration=0.2)
                        time.sleep(0.1)
                        pyautogui.doubleClick(x, y, interval=0.5)
                    self.thought_text.insert(tk.END, f"  🎯 double_click({x}, {y})\n", 'action')

            elif action.action_type == "right_single":
                if 'box' in action.params:
                    x1, y1, x2, y2 = action.params['box']
                    x, y = (x1 + x2) // 2, (y1 + y2) // 2
                    if cl:
                        cl(f'm:{x},{y}', f'w:50', f'rc:{x},{y}')
                    else:
                        pyautogui.moveTo(x, y, duration=0.2)
                        time.sleep(0.1)
                        pyautogui.rightClick(x, y)
                    self.thought_text.insert(tk.END, f"  🎯 right_click({x}, {y})\n", 'action')

            elif action.action_type == "drag":
                if 'start_box' in action.params and 'end_box' in action.params:
                    sx1, sy1, sx2, sy2 = action.params['start_box']
                    ex1, ey1, ex2, ey2 = action.params['end_box']
                    sx, sy = (sx1 + sx2) // 2, (sy1 + sy2) // 2
                    ex, ey = (ex1 + ex2) // 2, (ey1 + ey2) // 2
                    if cl:
                        cl(f'm:{sx},{sy}', f'w:50', f'dd:{sx},{sy}', f'w:100',
                           f'dm:{ex},{ey}', f'w:50', f'du:{ex},{ey}')
                    else:
                        pyautogui.moveTo(sx, sy, duration=0.2)
                        time.sleep(0.1)
                        pyautogui.mouseDown()
                        time.sleep(0.1)
                        pyautogui.moveTo(ex, ey, duration=0.3)
                        time.sleep(0.1)
                        pyautogui.mouseUp()
                    self.thought_text.insert(tk.END, f"  🎯 drag({sx},{sy})->({ex},{ey})\n", 'action')

            elif action.action_type == "hotkey":
                if 'keys' in action.params:
                    keys = action.params['keys']
                    key_map = {
                        'ctrl': 'ctrl', 'alt': 'alt', 'shift': 'shift',
                        'command': 'cmd', 'cmd': 'cmd', 'win': 'cmd', 'meta': 'cmd',
                        'return': 'return', 'enter': 'return', 'tab': 'tab',
                        'esc': 'escape', 'space': 'space',
                        'up': 'arrow-up', 'down': 'arrow-down',
                        'left': 'arrow-left', 'right': 'arrow-right',
                        'backspace': 'delete', 'delete': 'forward-delete',
                        'pageup': 'page-up', 'pagedown': 'page-down',
                        'home': 'home', 'end': 'end',
                    }
                    # Split by space and + (model may output "command+a" or "command a")
                    import re
                    raw_keys = []
                    for k in keys:
                        raw_keys.extend(re.split(r'[\s+]+', k.strip()))
                    mapped = [key_map.get(k.lower(), k.lower()) for k in raw_keys if k]
                    if cl:
                        MODS = {'cmd', 'ctrl', 'alt', 'shift'}
                        # Special keys valid for cliclick kp: command
                        KP_KEYS = {'return','tab','escape','space','arrow-up','arrow-down',
                                   'arrow-left','arrow-right','delete','forward-delete',
                                   'page-up','page-down','home','end','enter'}
                        modifiers = [k for k in mapped if k in MODS]
                        regular  = [k for k in mapped if k not in MODS]
                        parts = []
                        for m in modifiers:
                            parts.append(f'kd:{m}')
                        for k in regular:
                            if k in KP_KEYS:
                                parts.append(f'kp:{k}')
                            else:
                                # Letters/numbers → use t: (kp: doesn't support them)
                                parts.append(f't:{k}')
                        for m in reversed(modifiers):
                            parts.append(f'ku:{m}')
                        # On macOS, certain keys are more reliable via AppleScript
                        if mapped == ['return']:
                            self._osascript('tell application "System Events" to key code 36')
                        elif parts:
                            cl(*parts)
                        elif mapped:
                            # Fallback: use AppleScript for simple single-key presses
                            key = mapped[0]
                            if key == 'return':
                                self._osascript('tell application "System Events" to key code 36')
                            elif key == 'tab':
                                self._osascript('tell application "System Events" to key code 48')
                            elif key == 'escape':
                                self._osascript('tell application "System Events" to key code 53')
                            elif key == 'space':
                                self._osascript('tell application "System Events" to key code 49')
                            elif key == 'delete':
                                self._osascript('tell application "System Events" to key code 51')
                            elif key == 'arrow-left':
                                self._osascript('tell application "System Events" to key code 123')
                            elif key == 'arrow-right':
                                self._osascript('tell application "System Events" to key code 124')
                            elif key == 'arrow-down':
                                self._osascript('tell application "System Events" to key code 125')
                            elif key == 'arrow-up':
                                self._osascript('tell application "System Events" to key code 126')
                            else:
                                self._osascript(f'tell application "System Events" to keystroke "{key}"')
                        else:
                            self.log_system(f"  ⚠️ hotkey 无有效按键: {mapped}")
                    else:
                        pyautogui.hotkey(*mapped)
                    self.thought_text.insert(tk.END, f"  🎯 hotkey({' + '.join(mapped)})\n", 'action')

            elif action.action_type == "type":
                if 'content' in action.params:
                    content = action.params['content'].replace('\\n', '\n')
                    need_submit = content.endswith('\n')
                    strip_content = content.rstrip('\n')
                    if strip_content:
                        if cl:
                            # Use pbcopy + Cmd+V — cliclick t: cannot handle Unicode
                            import subprocess as _sp
                            _sp.run(['pbcopy'], input=strip_content.encode('utf-8'), timeout=3)
                            time.sleep(0.05)
                            cl('kd:cmd', 't:v', 'ku:cmd')
                            # Safety: release all modifier keys in case any got stuck
                            cl('ku:cmd', 'ku:ctrl', 'ku:alt', 'ku:shift')
                        else:
                            pyautogui.write(strip_content, interval=0.02)
                        time.sleep(0.1)
                    if need_submit:
                        time.sleep(0.1)
                        if cl:
                            cl('kp:return')
                        else:
                            pyautogui.press('enter')
                    self.thought_text.insert(tk.END, f"  🎯 type('{strip_content[:30]}{'...' if len(strip_content)>30 else ''}')\n", 'action')

            elif action.action_type == "scroll":
                direction = action.params.get('direction', 'down')
                if 'box' in action.params:
                    x1, y1, x2, y2 = action.params['box']
                    x, y = (x1 + x2) // 2, (y1 + y2) // 2
                    if cl:
                        cl(f'm:{x},{y}', 'w:30')
                    else:
                        pyautogui.moveTo(x, y, duration=0.1)
                    time.sleep(0.1)
                if cl:
                    if direction.lower() == 'up':
                        self._osascript('tell application "System Events" to key code 116')
                    elif direction.lower() == 'down':
                        self._osascript('tell application "System Events" to key code 121')
                else:
                    amt = 500
                    if direction.lower() == 'up':
                        pyautogui.scroll(amt)
                    elif direction.lower() == 'down':
                        pyautogui.scroll(-amt)
                    elif direction.lower() == 'left':
                        pyautogui.hscroll(-amt)
                    elif direction.lower() == 'right':
                        pyautogui.hscroll(amt)
                self.thought_text.insert(tk.END, f"  🎯 scroll({direction})\n", 'action')

            elif action.action_type == "wait":
                self.log_system("等待 5 秒...")
                time.sleep(5)

            elif action.action_type == "finished":
                self.log_system("✅ 任务完成!")
                return False

            elif action.action_type == "call_user":
                self.log_system("需要用户帮助")

            else:
                self.log_error(f"未知动作: {action.action_type}")

            self.thought_text.see(tk.END)
            self.root.update_idletasks()
            return True

        except Exception as e:
            self.log_error(f"执行失败: {e}")
            return True

    def run_agent(self):
        instruction = self.task_entry.get().strip()
        if not instruction or instruction == '输入任务...':
            self.log_error("请输入任务描述")
            self.is_running = False
            self.update_ui_state()
            return

        self.log_system(f"开始: {instruction}")
        self.current_task = instruction
        # Create screenshot folder for this task
        safe_name = re.sub(r'[^\w一-鿿]', '_', instruction)[:30]
        ts = time.strftime('%m%d_%H%M%S')
        self._screenshot_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'screenshots', f'{ts}_{safe_name}')
        os.makedirs(self._screenshot_dir, exist_ok=True)
        self._screenshot_idx = 0

        self.iteration_count = 0
        self.conversations = []
        self.action_history = []
        self.previous_plan = []

        first_screenshot = self.take_screenshot_base64()
        self.conversations.append({'role': 'user', 'image': first_screenshot, 'text': ''})

        while self.is_running and self.iteration_count < self.max_iterations:
            self.iteration_count += 1
            self.iter_label.config(text=f"{self.iteration_count}/{self.max_iterations}")
            self.log_step(self.iteration_count, self.max_iterations)
            self.root.update_idletasks()

            self.log_system("调用模型...")

            section = CollapsibleSection(self.thought_text, f"s{self.iteration_count}",
                                          f"Step {self.iteration_count} 思考中...")
            section.insert_header()

            try:
                content_text, reasoning_text = self.call_llm_stream(instruction, section)
            except Exception as e:
                self.log_error(f"API 调用失败: {e}")
                break

            if not content_text and not reasoning_text:
                self.log_error("模型返回空响应")
                break
            
            response_text = content_text if content_text else reasoning_text
            
            if not response_text.strip():
                self.log_error("模型返回空响应")
                break
            
            actions = self.parse_actions(response_text)

            # Auto-finish: only when model outputs "finished" but with bad JSON,
            # NOT when it says "done" while still trying to click (that's hallucination)
            if actions and not actions[0].action_type:
                # action_type empty → JSON parse issue. Check if thought says "done"
                thought_lower = actions[0].thought.lower()
                done_kw = ['任务完成', '已完成', 'task completed', 'task done', 'finished']
                if any(kw in thought_lower for kw in done_kw):
                    if self.iteration_count >= 1:
                        self.log_system("✅ 模型输出 finished (JSON 格式问题导致解析失败)，自动结束")
                        self.is_running = False
                        self.update_ui_state()
                        self.log_system("=" * 40)
                        self.log_system("任务执行完毕")
                        return

            action_str = response_text.split('Action:')[-1].strip() if 'Action:' in response_text else response_text
            section.finish(action_str[:60])

            summary = re.sub(r'Reflection:[\s\S]*?(?=Action_Summary:|Action:|$)', '', response_text).strip()
            self.conversations.append({'role': 'assistant', 'text': summary, 'desc': actions[0].thought})

            should_continue = True
            for action in actions:
                if not self.is_running:
                    break
                    
                action_key = f"{action.action_type}:{action.params}"
                repeat_count = sum(1 for h in self.action_history if h['key'] == action_key)

                # Auto-jitter: if same exact action repeated 2+ times, add random offset to click coords
                if repeat_count >= 2 and 'box' in action.params:
                    import random
                    jitter = random.randint(-15, 15)
                    box = action.params['box']
                    action.params['box'] = [box[0] + jitter, box[1] + jitter, box[2] + jitter, box[3] + jitter]
                    self.log_system(f"  ⚡ 自动偏移 {jitter}px 打破重复循环")

                self.action_history.append({
                    'step': self.iteration_count,
                    'action': action.action_type,
                    'params': str(action.params),
                    'key': action_key,
                    'repeat_count': repeat_count,
                    'result': '执行中...'
                })

                result = self.execute_action(action)
                
                if self.action_history:
                    self.action_history[-1]['result'] = '已执行' if result else '任务完成'
                
                if not result:
                    should_continue = False
                    break
                
                time.sleep(0.5)
            
            if not should_continue:
                break

            time.sleep(1.5)

            new_screenshot = self.take_screenshot_base64()
            self.conversations.append({'role': 'user', 'image': new_screenshot, 'text': ''})
            self.trim_conversations()

        self._store_task_memory(instruction)

        self.is_running = False
        self.update_ui_state()
        self.log_system("=" * 40)
        self.log_system("任务执行完毕")

    def _store_task_memory(self, instruction: str):
        task_finished = any(
            h['action'] == 'finished' for h in self.action_history
        )
        step_count = len(self.action_history)

        successful_actions = []
        for h in self.action_history:
            if h['action'] not in ('wait', 'call_user'):
                successful_actions.append(h['action'])

        keywords = self.memory._extract_keywords(instruction)

        memory = TaskMemory(
            memory_id=f"mem_{int(time.time() * 1000)}",
            task_description=instruction,
            action_sequence=self.action_history[-10:],
            success=task_finished,
            timestamp=time.time(),
            poignancy=7.0 if task_finished else 4.0,
            keywords=keywords,
            step_count=step_count,
            shortcut_actions=successful_actions if task_finished else [],
        )
        self.memory.add(memory)

        if task_finished and step_count > 5:
            optimal = self._extract_optimal_actions()
            if optimal:
                memory.shortcut_actions = optimal
                self.memory.learn_shortcut(memory.memory_id, optimal)

        if not task_finished:
            self.memory.add_reflection(
                memory.memory_id,
                f"任务未完成，执行了{step_count}步。重复动作过多，应尝试不同策略。"
            )

        self.log_system(f"记忆已存储 ({'成功' if task_finished else '失败'}, {step_count}步)")

    def _extract_optimal_actions(self) -> List[str]:
        seen = set()
        optimal = []
        for h in self.action_history:
            key = f"{h['action']}:{h.get('params', '')}"
            if key not in seen and h['action'] not in ('wait', 'call_user'):
                seen.add(key)
                optimal.append(h['action'])
        return optimal

    def trim_conversations(self):
        image_count = 0
        keep_from = 0
        for i in range(len(self.conversations) - 1, -1, -1):
            if self.conversations[i]['role'] == 'user' and 'image' in self.conversations[i]:
                image_count += 1
                if image_count > self.MAX_IMAGE_HISTORY:
                    keep_from = i + 1
                    break
        if keep_from > 0:
            while keep_from < len(self.conversations) and self.conversations[keep_from]['role'] != 'user':
                keep_from += 1
            if keep_from > 0:
                self.conversations = self.conversations[keep_from:]

    def start_task(self):
        if not self.api_key_var.get():
            self.log_error("请先配置 API Key")
            return

        # Quick sanity check via cliclick
        try:
            self._cliclick('m:+1,+0')
            self._cliclick('m:-1,+0')
        except Exception as e:
            self.log_error(f"⚠️ 鼠标控制失败: {e}")
            self.log_system("系统设置 → 隐私与安全性 → 辅助功能 → 添加终端并开启后重启")
            return

        self.is_running = True
        self.update_ui_state()
        self.status_dot.delete('all')
        self.status_dot.create_oval(2, 2, 8, 8, fill=self.COLORS['warning'], outline='')
        self.status_label.config(text="运行中")

        thread = threading.Thread(target=self.run_agent)
        thread.daemon = True
        thread.start()

    def stop_task(self):
        self.is_running = False
        self.update_ui_state()
        self.log_system("用户停止任务")

    def new_session(self):
        if self.is_running:
            self.is_running = False
            time.sleep(0.5)
        self.conversations = []
        self.iteration_count = 0
        self.task_entry.delete(0, tk.END)
        self.task_entry.config(fg=self.COLORS['text_dim'])
        self.task_entry.insert(0, '输入任务...')
        self.iter_label.config(text="0/50")
        self.clear_logs()
        self.update_ui_state()
        self.log_system("已创建新会话")

    def update_ui_state(self):
        if self.is_running:
            if _IS_MACOS:
                self.start_btn.config(bg='#6b7280', fg='#9ca3af')
                self.start_btn._disabled = True
                self.stop_btn.config(bg=self.COLORS['error'], fg='white')
                self.stop_btn._disabled = False
            else:
                self.start_btn.config(state=tk.DISABLED, bg='#6b7280')
                self.stop_btn.config(state=tk.NORMAL, bg=self.COLORS['error'])
        else:
            if _IS_MACOS:
                self.start_btn.config(bg=self.COLORS['success'], fg='white')
                self.start_btn._disabled = False
                self.stop_btn.config(bg='#6b7280', fg='#9ca3af')
                self.stop_btn._disabled = True
            else:
                self.start_btn.config(state=tk.NORMAL, bg=self.COLORS['success'])
                self.stop_btn.config(state=tk.DISABLED, bg='#6b7280')
            self.status_dot.delete('all')
            self.status_dot.create_oval(2, 2, 8, 8, fill=self.COLORS['success'], outline='')
            self.status_label.config(text="就绪")

    def clear_logs(self):
        self.thought_text.delete('1.0', tk.END)

    def copy_logs(self):
        logs = self.thought_text.get('1.0', tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(logs)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MiniGUIAgentApp()
    app.run()
