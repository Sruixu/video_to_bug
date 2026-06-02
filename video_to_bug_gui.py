#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video_to_bug_gui.py - video_to_bug 的图形界面

特性:
    - 蓝色主题
    - 走 MCP 模式（默认推荐），无需 API key
    - 多线程处理，UI 不卡
    - 文件拖入即可添加
    - 实时进度 + 结果预览
    - 一键复制 / 保存
"""

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# 拖放支持（可选依赖，没装也能跑）
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

# 导入后端
try:
    import video_to_bug as v2b
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import video_to_bug as v2b


# ========== 主题配置 ==========
class Theme:
    """蓝色 UI 主题"""
    PRIMARY = "#1976D2"
    PRIMARY_DARK = "#0D47A1"
    PRIMARY_LIGHT = "#42A5F5"
    PRIMARY_PALE = "#E3F2FD"
    ACCENT = "#2196F3"
    BG = "#F5F7FA"
    CARD = "#FFFFFF"
    CARD_BORDER = "#E0E6ED"
    TEXT = "#1A2332"
    TEXT_SECONDARY = "#5A6878"
    TEXT_LIGHT = "#8A95A5"
    DIVIDER = "#E8ECF1"
    SUCCESS = "#4CAF50"
    WARNING = "#FF9800"
    ERROR = "#F44336"
    FONT = ("Microsoft YaHei", 10)
    FONT_BOLD = ("Microsoft YaHei", 10, "bold")
    FONT_TITLE = ("Microsoft YaHei", 18, "bold")
    FONT_SUBTITLE = ("Microsoft YaHei", 12, "bold")
    FONT_SMALL = ("Microsoft YaHei", 9)
    FONT_MONO = ("Consolas", 10)


# ========== 主窗口 ==========
class Video2BugApp:
    def __init__(self, root):
        self.root = root
        self.root.title("video_to_bug  ·  录屏视频一键转 BUG 单")
        self.root.geometry("1100x860")
        self.root.minsize(960, 720)
        self.root.configure(bg=Theme.BG)

        # 状态
        self.video_files = []
        self.results = []
        self.is_processing = False
        self.event_queue = queue.Queue()

        # 应用选项
        self.var_save = tk.BooleanVar(value=True)
        self.var_clipboard = tk.BooleanVar(value=True)
        self.var_clipboard_each = tk.BooleanVar(value=False)
        self.var_output_dir = tk.StringVar(value=str(Path(__file__).parent / "output"))

        self._build_ui()

        # 注册拖放：拖视频到窗口任意位置即可添加
        if DND_AVAILABLE:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind("<<Drop>>", self._on_drop_window)
            except Exception:
                pass

        self._poll_queue()

    # ---------- 界面构建 ----------
    def _build_ui(self):
        self._build_header()
        main = ttk.Frame(self.root, style="TFrame")
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        paned = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(paned, style="TFrame", padding=4)
        paned.add(left, weight=2)
        right = ttk.Frame(paned, style="TFrame", padding=4)
        paned.add(right, weight=3)
        self._build_left_panel(left)
        self._build_right_panel(right)
        self._build_status_bar()

    def _build_header(self):
        """蓝色顶部标题栏"""
        header = tk.Frame(self.root, bg=Theme.PRIMARY, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        left = tk.Frame(header, bg=Theme.PRIMARY)
        left.pack(side=tk.LEFT, padx=20, pady=10)
        logo_canvas = tk.Canvas(left, width=36, height=36, bg=Theme.PRIMARY, highlightthickness=0)
        logo_canvas.pack(side=tk.LEFT, padx=(0, 12))
        logo_canvas.create_rectangle(2, 2, 34, 34, fill=Theme.PRIMARY_LIGHT, outline="", width=0)
        logo_canvas.create_text(18, 19, text="V", fill="white", font=("Microsoft YaHei", 18, "bold"))
        title_frame = tk.Frame(left, bg=Theme.PRIMARY)
        title_frame.pack(side=tk.LEFT)
        tk.Label(title_frame, text="video_to_bug", bg=Theme.PRIMARY, fg="white",
                 font=("Microsoft YaHei", 16, "bold")).pack(anchor=tk.W)
        tk.Label(title_frame, text="录屏视频一键转 BUG 单  ·  MCP 模式", bg=Theme.PRIMARY, fg="#BBDEFB",
                 font=("Microsoft YaHei", 9)).pack(anchor=tk.W)

    def _build_left_panel(self, parent):
        """左侧：文件列表 + 选项 + 操作按钮"""
        # MCP 提示（精简信息卡）
        hint = ttk.LabelFrame(parent, text="ℹ  MCP 模式", style="Card.TLabelframe", padding=10)
        hint.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            hint,
            text="✅ 走本机 mavis + matrix MCP 服务，无需 API key。\n"
                 "   使用前请确保 mavis CLI 已装好，且 matrix MCP 已配置。",
            style="Card.TLabel", justify=tk.LEFT,
        ).pack(anchor=tk.W)

        # 文件列表卡片
        self._build_file_list_card(parent)

        # 操作区
        self._build_action_bar(parent)

    def _build_file_list_card(self, parent):
        card = ttk.LabelFrame(parent, text="📁  待处理视频", style="Card.TLabelframe", padding=8)
        card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        btn_bar = ttk.Frame(card, style="Card.TFrame")
        btn_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btn_bar, text="➕ 选择文件", command=self._on_add_files, style="Secondary.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="📂 选择文件夹", command=self._on_add_folder, style="Secondary.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="🗑 清空", command=self._on_clear, style="Secondary.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="✕ 移除选中", command=self._on_remove_selected, style="Secondary.TButton").pack(side=tk.LEFT, padx=2)

        tree_frame = ttk.Frame(card, style="Card.TFrame")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            tree_frame, columns=("name", "size", "status"),
            show="headings", selectmode="extended", height=6,
        )
        self.tree.heading("name", text="文件名")
        self.tree.heading("size", text="大小")
        self.tree.heading("status", text="状态")
        self.tree.column("name", width=180, anchor=tk.W)
        self.tree.column("size", width=70, anchor=tk.E)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.config(yscrollcommand=sb.set)

    def _build_action_bar(self, parent):
        """处理选项 + 进度 + 操作按钮（合并到一张卡）"""
        card = ttk.LabelFrame(parent, text="⚡  处理选项 & 操作", style="Card.TLabelframe", padding=12)
        card.pack(fill=tk.X)

        check_kwargs = dict(
            bg=Theme.CARD, fg=Theme.TEXT,
            selectcolor=Theme.CARD,
            activebackground=Theme.CARD,
            activeforeground=Theme.PRIMARY,
            font=Theme.FONT, anchor=tk.W, padx=2,
        )
        tk.Checkbutton(card, text="自动复制到剪贴板", variable=self.var_clipboard, **check_kwargs).grid(row=0, column=0, sticky=tk.W, pady=2)
        tk.Checkbutton(card, text="每个单独复制", variable=self.var_clipboard_each, **check_kwargs).grid(row=0, column=1, sticky=tk.W, pady=2)
        tk.Checkbutton(card, text="保存到 .md", variable=self.var_save, **check_kwargs).grid(row=1, column=0, sticky=tk.W, pady=2)

        ttk.Label(card, text="输出目录:", style="Card.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        out_row = ttk.Frame(card, style="Card.TFrame")
        out_row.grid(row=2, column=1, sticky=tk.EW, pady=(8, 0), padx=4)
        ttk.Entry(out_row, textvariable=self.var_output_dir, font=Theme.FONT_MONO).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(out_row, text="浏览", command=self._on_browse_output, style="Secondary.TButton").pack(side=tk.LEFT)
        card.columnconfigure(1, weight=1)

        action_frame = ttk.Frame(card, style="Card.TFrame")
        action_frame.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(12, 0))

        progress_frame = ttk.Frame(action_frame, style="Card.TFrame")
        progress_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.progress = ttk.Progressbar(progress_frame, mode="determinate", style="Horizontal.TProgressbar")
        self.progress.pack(fill=tk.X, pady=(0, 2))
        self.lbl_progress = ttk.Label(progress_frame, text="等待开始", style="Status.TLabel")
        self.lbl_progress.pack(fill=tk.X)

        self.btn_start = ttk.Button(action_frame, text="▶  开始处理", style="Primary.TButton", command=self._on_start)
        self.btn_start.pack(side=tk.LEFT, padx=2)
        self.btn_copy_all = ttk.Button(action_frame, text="📋  全部复制", style="Secondary.TButton", command=self._on_copy_all, state=tk.DISABLED)
        self.btn_copy_all.pack(side=tk.LEFT, padx=2)

    def _build_right_panel(self, parent):
        card = ttk.LabelFrame(parent, text="📋  BUG 单预览", style="Card.TLabelframe", padding=8)
        card.pack(fill=tk.BOTH, expand=True)
        top_bar = ttk.Frame(card, style="Card.TFrame")
        top_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(top_bar, text="实时生成的 BUG 单，可直接复制或保存", style="Hint.TLabel").pack(side=tk.LEFT)
        ttk.Button(top_bar, text="🗑  清空", style="Secondary.TButton", command=self._on_clear_results).pack(side=tk.RIGHT, padx=2)
        ttk.Button(top_bar, text="📋  复制全部", style="Secondary.TButton", command=self._on_copy_all).pack(side=tk.RIGHT, padx=2)

        text_frame = ttk.Frame(card, style="Card.TFrame")
        text_frame.pack(fill=tk.BOTH, expand=True)
        self.result_text = scrolledtext.ScrolledText(
            text_frame, wrap=tk.WORD, font=Theme.FONT_MONO,
            state=tk.DISABLED, background="#FAFBFC", foreground=Theme.TEXT,
            relief="flat", borderwidth=1, padx=12, pady=12,
        )
        self.result_text.pack(fill=tk.BOTH, expand=True)

    def _build_status_bar(self):
        status = tk.Frame(self.root, bg=Theme.PRIMARY_PALE, height=28)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        status.pack_propagate(False)
        self.lbl_status = tk.Label(
            status, text="● 就绪", bg=Theme.PRIMARY_PALE, fg=Theme.PRIMARY_DARK,
            font=("Microsoft YaHei", 9), anchor=tk.W, padx=16,
        )
        self.lbl_status.pack(fill=tk.X)

    # ---------- 事件：文件 ----------
    def _on_add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择视频文件",
            filetypes=[("视频文件", "*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v *.3gp *.wmv"), ("所有文件", "*.*")],
        )
        for p in paths:
            self._add_video(p)

    def _on_add_folder(self):
        folder = filedialog.askdirectory(title="选择视频文件夹")
        if not folder:
            return
        videos = v2b.expand_video_inputs(folder)
        added = sum(1 for p in videos if self._add_video(p))
        self._set_status(f"从文件夹添加 {added} 个视频")

    def _on_browse_output(self):
        folder = filedialog.askdirectory(title="选择输出目录", initialdir=self.var_output_dir.get())
        if folder:
            self.var_output_dir.set(folder)

    def _on_clear(self):
        if self.is_processing:
            messagebox.showwarning("提示", "处理进行中，无法清空")
            return
        self.video_files.clear()
        self.results.clear()
        self._refresh_tree()
        self._clear_results_text()
        self._set_status("已清空")
        self.btn_copy_all.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.NORMAL)
        self.lbl_progress.config(text="等待开始")

    def _on_remove_selected(self):
        if self.is_processing:
            messagebox.showwarning("提示", "处理进行中，无法移除")
            return
        selected = self.tree.selection()
        for item in selected:
            path = self.tree.item(item)["values"][0]
            self.video_files = [p for p in self.video_files if str(p) != str(path)]
        self._refresh_tree()

    def _on_drop_window(self, event):
        """
        拖放文件到窗口任意位置时触发。
        支持拖入单文件、多文件、文件夹。
        """
        if self.is_processing:
            return
        # 解析拖入的数据
        data = event.data
        # tkinterdnd2 返回的路径可能用 { } 包裹含空格的路径
        if data.startswith("{") and data.endswith("}"):
            data = data[1:-1]
        # Windows 上用空格分隔多个路径
        raw_paths = self.root.tk.splitlist(data)

        added = 0
        for raw in raw_paths:
            p = str(raw).strip('{}')
            if os.path.isdir(p):
                # 拖入文件夹：递归扫描视频
                videos = v2b.expand_video_inputs(p)
                for v in videos:
                    if self._add_video(v):
                        added += 1
            else:
                if self._add_video(p):
                    added += 1

        if added:
            self._set_status(f"拖入 {added} 个视频")
        else:
            self._set_status("拖入的文件不是视频格式")

    # ---------- 事件：开始处理 / 复制 ----------
    def _on_start(self):
        if self.is_processing:
            return
        if not self.video_files:
            messagebox.showinfo("提示", "请先添加视频文件")
            return

        self.is_processing = True
        self.btn_start.config(state=tk.DISABLED, text="处理中...")
        self.results.clear()
        self._clear_results_text()
        self.progress["value"] = 0
        self.progress["maximum"] = len(self.video_files)
        self.btn_copy_all.config(state=tk.DISABLED)

        t = threading.Thread(target=self._worker, daemon=True)
        t.start()

    def _on_copy_all(self):
        if not self.results:
            return
        ok_results = [r for r in self.results if r["report"]]
        if not ok_results:
            return
        parts = [r["raw"] for r in ok_results]
        combined = "\n\n---\n\n".join(parts)
        if v2b.copy_to_clipboard(combined):
            self._set_status(f"已复制 {len(ok_results)} 个 BUG 单到剪贴板")
        else:
            self._set_status("复制到剪贴板失败，请手动复制")

    def _on_clear_results(self):
        self._clear_results_text()

    # ---------- 后台处理 ----------
    def _worker(self):
        output_dir = self.var_output_dir.get()
        save = self.var_save.get()
        clipboard = self.var_clipboard.get()
        clipboard_each = self.var_clipboard_each.get()

        for i, video_path in enumerate(self.video_files, 1):
            self.event_queue.put(("progress", i - 1, Path(video_path).name))
            self.event_queue.put(("tree_status", video_path, f"处理中 {i}/{len(self.video_files)}"))
            result = v2b.process_single_video(video_path)
            self.results.append(result)
            self.event_queue.put(("done_one", result, i, len(self.video_files)))

        if save:
            try:
                os.makedirs(output_dir, exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                for r in self.results:
                    if r["report"]:
                        out = v2b.save_bug_report(r["report"], r["video"], output_dir, timestamp)
                        self.event_queue.put(("log", f"[已保存] {out}"))
                if len(self.video_files) > 1:
                    summary = v2b.save_batch_report(self.results, output_dir)
                    self.event_queue.put(("log", f"[汇总] {summary}"))
            except Exception as e:
                self.event_queue.put(("log", f"[错误] 保存失败: {e}"))

        if clipboard:
            ok = [r for r in self.results if r["report"]]
            if ok:
                if len(ok) == 1 or clipboard_each:
                    v2b.copy_to_clipboard(ok[-1]["raw"])
                    self.event_queue.put(("log", "[OK] 已复制最新 BUG 单到剪贴板"))
                else:
                    combined = "\n\n---\n\n".join(r["raw"] for r in ok)
                    v2b.copy_to_clipboard(combined)
                    self.event_queue.put(("log", f"[OK] 已复制 {len(ok)} 个 BUG 单到剪贴板"))

        self.event_queue.put(("finished",))

    # ---------- 队列消费 ----------
    def _poll_queue(self):
        try:
            while True:
                event = self.event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_event(self, event):
        if event[0] == "progress":
            _, i, name = event
            self.progress["value"] = i
            self.lbl_progress.config(text=f"处理中 ({i}/{len(self.video_files)}): {name}")
            self._set_status(f"处理中 ({i}/{len(self.video_files)}): {name}")
        elif event[0] == "tree_status":
            _, path, status = event
            self._update_tree_status(path, status)
        elif event[0] == "log":
            self._set_status(event[1])
        elif event[0] == "done_one":
            _, result, i, total = event
            self.progress["value"] = i
            status = "✓ 完成" if result["report"] else "✗ 失败"
            self._update_tree_status(result["video"], status)
            self._append_result_to_text(result, i, total)
            self.lbl_progress.config(text=f"已完成 {i}/{total}")
            self._set_status(f"已完成 {i}/{total}: {Path(result['video']).name}")
        elif event[0] == "finished":
            self.is_processing = False
            self.btn_start.config(state=tk.NORMAL, text="▶  开始处理")
            if any(r["report"] for r in self.results):
                self.btn_copy_all.config(state=tk.NORMAL)
            ok = sum(1 for r in self.results if r["report"])
            self._set_status(f"处理完成：{ok}/{len(self.results)} 成功")

    # ---------- 辅助方法 ----------
    def _add_video(self, path):
        path = str(Path(path).resolve())
        if path in self.video_files:
            return False
        if Path(path).suffix.lower() not in v2b.VIDEO_EXTENSIONS:
            return False
        self.video_files.append(path)
        self._refresh_tree()
        return True

    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for p in self.video_files:
            size_mb = os.path.getsize(p) / 1024 / 1024 if os.path.exists(p) else 0
            self.tree.insert("", tk.END, values=(Path(p).name, f"{size_mb:.1f} MB", "待处理"))

    def _update_tree_status(self, path, status):
        for item in self.tree.get_children():
            if self.tree.item(item)["values"][0] == Path(str(path)).name:
                values = list(self.tree.item(item)["values"])
                values[2] = status
                self.tree.item(item, values=values)
                break

    def _set_status(self, msg):
        self.lbl_status.config(text=f"● {msg}")

    def _clear_results_text(self):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        self.result_text.config(state=tk.DISABLED)

    def _append_result_to_text(self, result, index, total):
        """把单个 BUG 单追加到结果区。**不显示头部信息**，只显示 BUG 单内容。"""
        self.result_text.config(state=tk.NORMAL)
        if index == 1:
            self.result_text.delete("1.0", tk.END)
        if result["report"]:
            content = result["raw"] + "\n"
        else:
            content = f"❌ 处理失败: {Path(result['video']).name}\n   错误: {result['error']}\n"
        if index > 1:
            self.result_text.insert(tk.END, "\n" + "─" * 60 + "\n\n")
        self.result_text.insert(tk.END, content)
        self.result_text.see(tk.END)
        self.result_text.config(state=tk.DISABLED)


# ========== 入口 ==========
def main():
    # 如果装了 tkinterdnd2，用它替代 tk.Tk（必须！）
    if DND_AVAILABLE and TkinterDnD is not None:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    # ttk 主题
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "winnative" in style.theme_names():
            style.theme_use("winnative")
    except Exception:
        pass
    app = Video2BugApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
