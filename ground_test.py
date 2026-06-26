"""
Grounding 测试工具 — 框选区域获取归一化/绝对坐标
用法:
    python ground_test.py                    # 空白窗口，可粘贴/拖入图片
    python ground_test.py screenshot.jpg     # 打开指定图片
"""
import sys
import os
import io
import subprocess
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

_IS_MACOS = sys.platform == 'darwin'


def _create_btn(parent, text, bg_color, fg_color, font, command, padx=12, pady=4, **kw):
    """Cross-platform button — Label on macOS (respects bg), Button on Windows."""
    if _IS_MACOS:
        btn = tk.Label(parent, text=text, font=font, bg=bg_color, fg=fg_color,
                       padx=padx, pady=pady, cursor='hand2', bd=0, **kw)
        if command is not None:
            btn.bind('<Button-1>', lambda e: command())
        def _on_enter(e, b=btn): b.config(relief='solid', bd=1)
        def _on_leave(e, b=btn): b.config(relief='flat', bd=0)
        btn.bind('<Enter>', _on_enter)
        btn.bind('<Leave>', _on_leave)
    else:
        btn = tk.Button(parent, text=text, font=font, bg=bg_color, fg=fg_color,
                        activebackground=bg_color, bd=0, padx=padx, pady=pady,
                        cursor='hand2', command=command, **kw)
    return btn


class GroundTest:
    def __init__(self, root, image=None):
        self.root = root
        self.root.title("Grounding 测试工具")
        self.root.configure(bg='#1e1e1e')

        self.img_original = None
        self.img_display = None
        self.photo = None
        self.scale = 1.0
        self.canvas_w = 960
        self.canvas_h = 680

        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.selection = None

        self._build_ui()

        # Support drag-and-drop
        try:
            from tkinter import dnd
            self.root.drop_target_register(dnd.DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop)
        except Exception:
            pass

        if image:
            self.load_image(image)

    def _build_ui(self):
        # --- Toolbar ---
        toolbar = tk.Frame(self.root, bg='#2c2c2e', padx=10, pady=8)
        toolbar.pack(fill=tk.X)

        tk.Label(toolbar, text="📐 Grounding 测试", font=('system-ui', 14, 'bold'),
                 fg='#f5f5f7', bg='#2c2c2e').pack(side=tk.LEFT, padx=(0, 16))

        _create_btn(toolbar, text="📂 打开图片", bg_color='#3a3a3c', fg_color='#f5f5f7',
                     font=('system-ui', 11), padx=14, pady=5,
                     command=self.load_file).pack(side=tk.LEFT, padx=3)
        _create_btn(toolbar, text="📋 从剪贴板粘贴", bg_color='#3a3a3c', fg_color='#f5f5f7',
                     font=('system-ui', 11), padx=14, pady=5,
                     command=self.load_clipboard_macos).pack(side=tk.LEFT, padx=3)
        _create_btn(toolbar, text="🗑 清除框选", bg_color='#3a3a3c', fg_color='#f5f5f7',
                     font=('system-ui', 11), padx=14, pady=5,
                     command=self.clear_selection).pack(side=tk.LEFT, padx=3)

        self.zoom_var = tk.StringVar(value="适应窗口")
        tk.OptionMenu(toolbar, self.zoom_var, "适应窗口", "100%", "200%", "50%",
                      command=self._on_zoom).pack(side=tk.RIGHT, padx=3)

        # --- Canvas ---
        self.canvas = tk.Canvas(self.root, bg='#161616', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self.canvas.bind('<Button-1>', self._on_press)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_release)
        self.canvas.bind('<Motion>', self._on_motion)
        # Right-click to copy normalized coords
        self.canvas.bind('<Button-3>', lambda e: self._copy_normalized())
        # Ctrl+scroll zoom
        self.canvas.bind('<Control-MouseWheel>', self._on_scroll_zoom)

        # Drop-zone hint (shown when no image loaded)
        self._draw_drop_hint()

        # --- Info bar ---
        self.info_bar = tk.Frame(self.root, bg='#2c2c2e', padx=10, pady=5)
        self.info_bar.pack(fill=tk.X)

        self.mouse_label = tk.Label(self.info_bar, text="",
                                     font=('Menlo', 10), fg='#98989d', bg='#2c2c2e')
        self.mouse_label.pack(side=tk.LEFT)

        self.sel_label = tk.Label(self.info_bar, text="💡 打开图片后拖拽框选",
                                   font=('Menlo', 10), fg='#30d158', bg='#2c2c2e')
        self.sel_label.pack(side=tk.RIGHT)

        # --- Result panel ---
        self.result_panel = tk.Frame(self.root, bg='#1e1e1e', padx=10, pady=6)
        self.result_panel.pack(fill=tk.X)

        tk.Label(self.result_panel, text="📐 坐标结果", font=('system-ui', 12, 'bold'),
                 fg='#f5f5f7', bg='#1e1e1e').pack(anchor=tk.W, pady=(0, 4))

        self.result_text = tk.Text(self.result_panel, font=('Menlo', 11), height=6,
                                    bg='#161616', fg='#f5f5f7', insertbackground='white',
                                    relief='flat', bd=0, padx=8, pady=6)
        self.result_text.pack(fill=tk.X)
        self.result_text.insert('1.0',
            "━━━ 使用方法 ━━━\n"
            "1. 按 📂 打开截图  或  按 📋 从剪贴板粘贴 (Cmd+V 截图)\n"
            "2. 在图片上 拖拽框选 目标区域\n"
            "3. 按 📋复制归一化 得到模型需要的坐标")
        self.result_text.config(state=tk.DISABLED)

        btn_row = tk.Frame(self.result_panel, bg='#1e1e1e')
        btn_row.pack(fill=tk.X, pady=(6, 0))

        _create_btn(btn_row, text="📋 复制归一化 [0.xxx, 0.xxx]",
                     bg_color='#0a84ff', fg_color='white',
                     font=('system-ui', 10), padx=12, pady=4,
                     command=self._copy_normalized).pack(side=tk.LEFT, padx=(0, 6))

        _create_btn(btn_row, text="📋 复制绝对 [x, y]",
                     bg_color='#3a3a3c', fg_color='#f5f5f7',
                     font=('system-ui', 10), padx=12, pady=4,
                     command=self._copy_absolute).pack(side=tk.LEFT, padx=(0, 6))

        _create_btn(btn_row, text="📋 复制全部坐标信息",
                     bg_color='#3a3a3c', fg_color='#f5f5f7',
                     font=('system-ui', 10), padx=12, pady=4,
                     command=self._copy_all).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Drop hint
    # ------------------------------------------------------------------
    def _draw_drop_hint(self):
        self.canvas.delete('hint')
        w = self.canvas.winfo_width() or self.canvas_w
        h = self.canvas.winfo_height() or self.canvas_h
        cx, cy = w // 2, h // 2
        self.canvas.create_text(cx, cy - 20, text="📂", font=('system-ui', 48),
                                fill='#3a3a3c', tags='hint')
        self.canvas.create_text(cx, cy + 35, text="点击 📂 打开截图 或 ⌘V 从剪贴板粘贴",
                                font=('system-ui', 14), fill='#636366', tags='hint')
        self.canvas.create_text(cx, cy + 60, text="macOS 截图: Cmd+Shift+4 选区截图 → 回来点 📋从剪贴板粘贴",
                                font=('system-ui', 10), fill='#48484d', tags='hint')

    # ------------------------------------------------------------------
    # Image loading
    # ------------------------------------------------------------------
    def load_file(self):
        path = filedialog.askopenfilename(
            title="选择截图",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("所有文件", "*.*")]
        )
        if path:
            self.load_image(path)

    def load_clipboard_macos(self):
        """macOS clipboard → PIL Image via pngpaste or osascript."""
        img = None

        # Method 1: pngpaste (brew install pngpaste)
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp_path = tmp.name
            subprocess.run(['pngpaste', tmp_path], capture_output=True, timeout=5, check=True)
            if os.path.getsize(tmp_path) > 100:
                img = Image.open(tmp_path)
            else:
                os.unlink(tmp_path)
        except Exception:
            pass

        # Method 2: osascript + PNG data
        if img is None:
            try:
                script = '''
                use framework "AppKit"
                set pb to current application's NSPasteboard's generalPasteboard
                set imgData to pb's dataForType:(current application's NSPasteboardTypePNG)
                if imgData is not missing value then
                    set tempFile to POSIX path of (current application's NSTemporaryDirectory() as string) & "clipboard.png"
                    imgData's writeToFile:tempFile atomically:true
                    return tempFile
                else
                    return "none"
                end if
                '''
                r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=5)
                tmp_path = r.stdout.strip()
                if tmp_path and tmp_path != 'none' and os.path.exists(tmp_path):
                    img = Image.open(tmp_path)
            except Exception:
                pass

        # Method 3: PIL ImageGrab
        if img is None:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grabclipboard()
            except Exception:
                pass

        if img is None:
            messagebox.showwarning(
                "剪贴板无图片",
                "请先截图 (Cmd+Shift+4 选区截图)\n"
                "截图后剪贴板会自动有图片，再点 📋从剪贴板粘贴"
            )
            return

        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        self.load_image(img)

    def _on_drop(self, event):
        """Handle file drag-and-drop."""
        file_path = event.data.strip().strip('{}').strip()
        if file_path and os.path.isfile(file_path):
            self.load_image(file_path)

    def load_image(self, source):
        if isinstance(source, str):
            self.img_original = Image.open(source)
        elif isinstance(source, Image.Image):
            self.img_original = source
        else:
            return
        self.img_original = self.img_original.convert('RGB')
        self.selection = None
        self.rect_id = None
        self.canvas.delete('hint')
        self._update_display()

    # ------------------------------------------------------------------
    # Display / zoom
    # ------------------------------------------------------------------
    def _calc_scale(self):
        if self.img_original is None:
            return 1.0
        zoom = self.zoom_var.get()
        if zoom == "100%":
            return 1.0
        elif zoom == "200%":
            return 2.0
        elif zoom == "50%":
            return 0.5
        cw = max(self.canvas.winfo_width(), 100)
        ch = max(self.canvas.winfo_height(), 100)
        ow, oh = self.img_original.width, self.img_original.height
        return min(cw / ow, ch / oh, 1.0)

    def _update_display(self):
        if self.img_original is None:
            return
        self.scale = self._calc_scale()
        ow, oh = self.img_original.width, self.img_original.height
        dw, dh = int(ow * self.scale), int(oh * self.scale)
        self.img_display = self.img_original.resize((dw, dh), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(self.img_display)

        self.canvas.delete('all')
        self.canvas.config(scrollregion=(0, 0, dw, dh))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo, tags='bg')
        self.rect_id = None
        self._update_result()

    def _on_zoom(self, _=None):
        self._update_display()

    def _on_scroll_zoom(self, event):
        if event.delta > 0:
            s = min(self.scale * 1.2, 5.0)
        else:
            s = max(self.scale / 1.2, 0.1)
        self.zoom_var.set(f"{int(s * 100)}%")
        self._update_display()

    # ------------------------------------------------------------------
    # Mouse / selection
    # ------------------------------------------------------------------
    def _to_original(self, cx, cy):
        ox = int(cx / self.scale)
        oy = int(cy / self.scale)
        if self.img_original:
            ox = max(0, min(ox, self.img_original.width - 1))
            oy = max(0, min(oy, self.img_original.height - 1))
        return ox, oy

    def _on_press(self, event):
        if self.img_original is None:
            return
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x + 1, self.start_y + 1,
            outline='#30d158', width=2, dash=(4, 2))

    def _on_drag(self, event):
        if self.start_x is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cx, cy)

    def _on_release(self, event):
        if self.start_x is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        x1, y1 = min(self.start_x, cx), min(self.start_y, cy)
        x2, y2 = max(self.start_x, cx), max(self.start_y, cy)
        self.canvas.coords(self.rect_id, x1, y1, x2, y2)
        ox1, oy1 = self._to_original(x1, y1)
        ox2, oy2 = self._to_original(x2, y2)
        self.selection = (ox1, oy1, ox2, oy2)
        self._update_result()
        self.start_x = None
        self.start_y = None

    def _on_motion(self, event):
        if self.img_original is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        ox, oy = self._to_original(cx, cy)
        ow, oh = self.img_original.width, self.img_original.height
        self.mouse_label.config(
            text=f"鼠标: ({ox}, {oy}) px  |  归一化 [{ox/ow:.4f}, {oy/oh:.4f}]  |  图片 {ow}×{oh}  |  缩放 {self.scale:.0%}")

    def clear_selection(self):
        self.selection = None
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self._update_result()

    # ------------------------------------------------------------------
    # Result & copy
    # ------------------------------------------------------------------
    def _update_result(self):
        if self.img_original is None:
            return
        if self.selection is None:
            self.sel_label.config(text="💡 在图片上拖拽框选目标区域")
            return

        ox1, oy1, ox2, oy2 = self.selection
        ow, oh = self.img_original.width, self.img_original.height
        cx = (ox1 + ox2) / 2
        cy = (oy1 + oy2) / 2
        w, h = ox2 - ox1, oy2 - oy1

        lines = [
            f"图片尺寸: {ow} × {oh}",
            f"",
            f"🎯 中心 归一化:  [{cx/ow:.4f}, {cy/oh:.4f}]",
            f"🎯 中心 绝对坐标: [{int(cx)}, {int(cy)}]",
            f"",
            f"📦 框选区域:",
            f"   归一化: [{ox1/ow:.4f}, {oy1/oh:.4f}, {ox2/ow:.4f}, {oy2/oh:.4f}]",
            f"   绝对:   [{ox1}, {oy1}, {ox2}, {oy2}]",
            f"   尺寸:   {w} × {h} px",
            f"",
            f"🤖 start_point: [{cx/ow:.4f}, {cy/oh:.4f}]",
        ]
        self._set_result('\n'.join(lines))
        self.sel_label.config(text=f"框选: ({ox1},{oy1}) → ({ox2},{oy2})  {w}×{h}px")

    def _set_result(self, text):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert('1.0', text)
        self.result_text.config(state=tk.DISABLED)

    def _copy_normalized(self):
        if not self.selection:
            return
        ox1, oy1, ox2, oy2 = self.selection
        ow, oh = self.img_original.width, self.img_original.height
        cx, cy = (ox1 + ox2) / 2, (oy1 + oy2) / 2
        t = f"[{cx/ow:.4f}, {cy/oh:.4f}]"
        self.root.clipboard_clear()
        self.root.clipboard_append(t)
        self.sel_label.config(text=f"✅ 已复制: {t}")

    def _copy_absolute(self):
        if not self.selection:
            return
        ox1, oy1, ox2, oy2 = self.selection
        cx, cy = (ox1 + ox2) / 2, (oy1 + oy2) / 2
        t = f"[{int(cx)}, {int(cy)}]"
        self.root.clipboard_clear()
        self.root.clipboard_append(t)
        self.sel_label.config(text=f"✅ 已复制: {t}")

    def _copy_all(self):
        if not self.selection:
            return
        ox1, oy1, ox2, oy2 = self.selection
        ow, oh = self.img_original.width, self.img_original.height
        cx, cy = (ox1 + ox2) / 2, (oy1 + oy2) / 2
        t = self.result_text.get('1.0', tk.END).strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(t)
        self.sel_label.config(text="✅ 已复制全部坐标信息")


def main():
    root = tk.Tk()
    root.geometry("1000x820")
    root.minsize(700, 600)
    image = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        image = sys.argv[1]
    app = GroundTest(root, image=image)
    root.mainloop()


if __name__ == '__main__':
    main()
