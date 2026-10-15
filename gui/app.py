# -*- coding: utf-8 -*-
"""老牧师口音合成器 —— tkinter 桌面界面

依赖：只用 GPT-SoVITS 整合包 runtime 自带的库（tkinter / soundfile），无需 pip 安装任何东西。
启动：双击 run_gui.bat（它从 config.local.txt 读 GPT-SoVITS 目录，并调用整合包自带的 python）
参数：
    --ui-only        只开界面、不加载模型（快速看外观用）
    --project DIR    指定项目目录（默认 gui/ 的上一级，也就是仓库根）
    --device cuda|cpu

设计意图：把上游「每次启动等一分钟 + 纯 stdin 循环」换成「窗口常驻、模型只加载一次、
文本可编辑重发、参数可调、结果有历史」。
"""

import os
import sys
import time
import queue
import threading
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import winsound
except Exception:                                     # 非 Windows
    winsound = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ARGV = sys.argv[1:]
UI_ONLY = "--ui-only" in ARGV


def _arg_value(name, default=None):
    if name in ARGV:
        i = ARGV.index(name)
        if i + 1 < len(ARGV):
            return ARGV[i + 1]
    return default


# 项目根 = gui/ 的上一级：weights/ 、ref/ 、tts_out/ 都在那里，不需要配置
PROJECT_DIR = os.path.abspath(
    _arg_value("--project", os.environ.get("LAOMUSHI_PROJECT", os.path.dirname(HERE)))
)
OUT_DIR = os.path.join(PROJECT_DIR, "tts_out")

from engine import (  # noqa: E402
    LaomushiEngine, resolve_gsv_home, is_gsv_home, write_config,
)

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 11, "bold")


class App(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("老牧师口音合成器")
        self.geometry("1020x720")
        self.minsize(880, 600)
        self._center()

        self.q = queue.Queue()
        self.engine = None
        self.loading = False
        self.busy = False
        self.last_path = None
        self.playing = None
        self.player_stop = False
        self.history = []          # [(time_str, summary, duration, path)]

        self._init_style()
        self._build_top()
        self._build_main()
        self._build_bottom()
        self._build_log()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-Return>", lambda e: self._on_synth())
        self.bind("<F5>", lambda e: self._on_synth())

        self._scan_existing()
        self._refresh_hint()
        self.after(80, self._pump)
        self.after(200, self._grab_front)
        try:
            self._logf = open(os.path.join(HERE, "gui.log"), "w", encoding="utf-8")
        except Exception:
            self._logf = open(os.devnull, "w")
        if UI_ONLY:
            self._set_state("界面预览模式（未加载模型）", "idle")
            self.btn_load.configure(text="加载模型")
            self._log_line("已跳过模型加载（--ui-only）。点击「加载模型」可实际加载。")
        else:
            self.after(300, self._on_load)

    # ------------------------------------------------------------ 基础设施
    def _grab_front(self):
        """启动时把窗口提到最前（避免被浏览器等盖住），1.5 秒后恢复正常层叠。"""
        try:
            self.lift()
            self.attributes("-topmost", True)
            self.after(1500, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

    def _center(self):
        self.update_idletasks()
        w, h = 1020, 720
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(0, (sh - h) // 2 - 20)))

    def _init_style(self):
        st = ttk.Style()
        for theme in ("vista", "winnative", "clam"):
            if theme in st.theme_names():
                st.theme_use(theme)
                break
        st.configure(".", font=FONT)
        st.configure("TLabel", font=FONT)
        st.configure("TButton", font=FONT, padding=(10, 4))
        st.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))
        st.configure("TLabelframe.Label", font=FONT_TITLE)
        st.configure("Status.TLabel", font=FONT_SMALL)
        st.configure("Treeview", font=FONT_SMALL, rowheight=24)
        st.configure("Treeview.Heading", font=FONT_SMALL)
        self.configure(background="#f4f4f4")

    # ---------------------------------------------------------------- 顶栏
    def _build_top(self):
        top = ttk.Frame(self, padding=(10, 8, 10, 4))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(3, weight=1)

        self.dot = ttk.Label(top, text="●", font=("Segoe UI", 13), foreground="#c00")
        self.dot.grid(row=0, column=0, padx=(0, 6))
        self.lbl_state = ttk.Label(top, text="未加载模型", font=FONT_TITLE)
        self.lbl_state.grid(row=0, column=1, sticky="w")

        self.lbl_hint = ttk.Label(top, text="", style="Status.TLabel", foreground="#666")
        self.lbl_hint.grid(row=1, column=1, sticky="w", columnspan=7)

        ttk.Label(top, text="设备").grid(row=0, column=4, padx=(0, 4))
        self.var_device = tk.StringVar(value="cuda")
        ttk.Combobox(top, textvariable=self.var_device, values=["cuda", "cpu"],
                     width=6, state="readonly").grid(row=0, column=5, padx=(0, 10))
        self.btn_load = ttk.Button(top, text="加载模型", command=self._on_load)
        self.btn_load.grid(row=0, column=6)
        ttk.Button(top, text="设置…", width=7, command=self._on_setup).grid(
            row=0, column=7, padx=(6, 0))

    # ---------------------------------------------------------------- 主体
    def _build_main(self):
        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # ---------- 左：文本 + 参数 + 按钮
        left = ttk.Frame(pane, padding=(0, 0, 6, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        pane.add(left, weight=3)

        box = ttk.Labelframe(left, text=" 合成文本 ", padding=6)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.txt = scrolledtext.ScrolledText(box, wrap="word", font=("Microsoft YaHei UI", 11),
                                             undo=True, height=12)
        self.txt.grid(row=0, column=0, sticky="nsew")
        self.txt.insert("1.0", "老牧师来到了村口，对着大伙儿说：今儿个天气不错啊。")
        ttk.Label(box, text="Ctrl+Enter 合成 / F5 合成 · 支持多行，长文按标点自动切分",
                  style="Status.TLabel", foreground="#777").grid(row=1, column=0, sticky="w", pady=(4, 0))

        params = ttk.Labelframe(left, text=" 参数 ", padding=8)
        params.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        params.columnconfigure(1, weight=1)

        ttk.Label(params, text="语速").grid(row=0, column=0, sticky="w")
        self.var_speed = tk.DoubleVar(value=1.0)
        sp = ttk.Scale(params, from_=0.6, to=1.5, variable=self.var_speed,
                       orient="horizontal", command=lambda v: self.lbl_speed.configure(
                           text="%.2f" % float(v)))
        sp.grid(row=0, column=1, sticky="ew", padx=6)
        self.lbl_speed = ttk.Label(params, text="1.00", width=5)
        self.lbl_speed.grid(row=0, column=2)

        ttk.Label(params, text="随机种子").grid(row=1, column=0, sticky="w", pady=(6, 0))
        f_seed = ttk.Frame(params)
        f_seed.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        self.var_seed = tk.StringVar(value="-1")
        ttk.Entry(f_seed, textvariable=self.var_seed, width=10).pack(side="left")
        ttk.Label(f_seed, text="  -1 = 每次随机（想复现同一句就填具体数字）",
                  style="Status.TLabel", foreground="#777").pack(side="left")

        ttk.Label(params, text="参考音频").grid(row=2, column=0, sticky="w", pady=(6, 0))
        f_ref = ttk.Frame(params)
        f_ref.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        f_ref.columnconfigure(0, weight=1)
        self.var_ref = tk.StringVar(value=os.path.join(PROJECT_DIR, "ref", "ref.wav"))
        ttk.Entry(f_ref, textvariable=self.var_ref).grid(row=0, column=0, sticky="ew")
        ttk.Button(f_ref, text="浏览", command=self._pick_ref, width=6).grid(row=0, column=1, padx=(4, 0))

        ttk.Label(params, text="参考文本").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.var_reftext = tk.StringVar(value="今天天气不错，我们一起出去走走吧。")
        ttk.Entry(params, textvariable=self.var_reftext).grid(row=3, column=1, columnspan=2,
                                                              sticky="ew", pady=(6, 0))

        self.var_autoplay = tk.BooleanVar(value=True)
        ttk.Checkbutton(params, text="合成后自动播放", variable=self.var_autoplay).grid(
            row=4, column=1, sticky="w", pady=(8, 0))

        row = ttk.Frame(left, padding=(0, 8, 0, 0))
        row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.btn_synth = ttk.Button(row, text="▶  合成", style="Accent.TButton",
                                    command=self._on_synth, width=14)
        self.btn_synth.pack(side="left")
        ttk.Button(row, text="🔊 重播", command=self._replay, width=10).pack(side="left", padx=6)
        ttk.Button(row, text="■ 停止", command=self._stop_play, width=8).pack(side="left")
        ttk.Button(row, text="打开输出目录", command=self._open_outdir).pack(side="left", padx=6)
        ttk.Button(row, text="清空文本", command=lambda: self.txt.delete("1.0", "end")).pack(side="left")

        # ---------- 右：历史
        right = ttk.Frame(pane, padding=(6, 0, 0, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        pane.add(right, weight=2)

        hbox = ttk.Labelframe(right, text=" 合成历史 ", padding=6)
        hbox.grid(row=0, column=0, sticky="nsew")
        hbox.columnconfigure(0, weight=1)
        hbox.rowconfigure(0, weight=1)

        cols = ("time", "text", "dur")
        self.tree = ttk.Treeview(hbox, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("time", text="时间")
        self.tree.heading("text", text="内容 / 文件")
        self.tree.heading("dur", text="时长")
        self.tree.column("time", width=64, anchor="w", stretch=False)
        self.tree.column("text", width=260, anchor="w")
        self.tree.column("dur", width=56, anchor="e", stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(hbox, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda e: self._play_selected())

        hbtns = ttk.Frame(hbox)
        hbtns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(hbtns, text="播放", command=self._play_selected, width=8).pack(side="left")
        ttk.Button(hbtns, text="复制路径", command=self._copy_path, width=10).pack(side="left", padx=4)
        ttk.Button(hbtns, text="删除选中", command=self._del_selected, width=10).pack(side="left")
        ttk.Button(hbtns, text="刷新", command=self._scan_existing, width=8).pack(side="left", padx=4)

    # ---------------------------------------------------------------- 底栏
    def _build_bottom(self):
        bot = ttk.Frame(self, padding=(10, 0, 10, 6))
        bot.grid(row=2, column=0, sticky="ew")
        bot.columnconfigure(1, weight=1)

        self.pbar = ttk.Progressbar(bot, mode="indeterminate", length=180)
        self.pbar.grid(row=0, column=0, sticky="w")
        self.lbl_foot = ttk.Label(bot, text="就绪", style="Status.TLabel", foreground="#555")
        self.lbl_foot.grid(row=0, column=1, sticky="w", padx=8)

        self.btn_log = ttk.Button(bot, text="显示日志 ▾", width=12, command=self._toggle_log)
        self.btn_log.grid(row=0, column=2, sticky="e")

    def _build_log(self):
        self.logframe = ttk.Labelframe(self, text=" 运行日志 ", padding=4)
        self.logframe.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.logframe.columnconfigure(0, weight=1)
        self.log = tk.Text(self.logframe, height=6, font=("Consolas", 9), wrap="none",
                           background="#1e1e1e", foreground="#d4d4d4", insertbackground="#d4d4d4")
        self.log.grid(row=0, column=0, sticky="ew")
        self.logframe.grid_remove()
        self.log_visible = False

    # ---------------------------------------------------------------- 线程桥
    def _post(self, kind, **kw):
        self.q.put((kind, kw))

    def _pump(self):
        try:
            while True:
                kind, kw = self.q.get_nowait()
                self._handle(kind, kw)
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _handle(self, kind, kw):
        if kind == "log":
            self._log_line(kw["text"])
        elif kind == "state":
            self._set_state(kw["text"], kw.get("level", "idle"))
        elif kind == "foot":
            self.lbl_foot.configure(text=kw["text"])
        elif kind == "stage":
            self.lbl_foot.configure(text=kw["text"])
        elif kind == "loaded":
            self.loading = False
            self.btn_load.configure(text="重载模型", state="normal")
            self.btn_synth.configure(state="normal")
            self._set_state("模型就绪", "ok")
            self.lbl_hint.configure(text="加载耗时 %.1fs · 设备 %s · GPT-SoVITS：%s" % (
                kw["seconds"], kw["device"], kw.get("gsv", "")))
            self.pbar.stop()
            self._foot("可以开始合成了")
        elif kind == "loadfail":
            self.loading = False
            self.btn_load.configure(text="加载模型", state="normal")
            self._set_state("加载失败", "err")
            self.pbar.stop()
            self._log_line("加载失败：" + kw["error"])
            messagebox.showerror("加载失败", kw["error"], parent=self)
        elif kind == "synth_ok":
            self.busy = False
            self.btn_synth.configure(state="normal", text="▶  合成")
            self.pbar.stop()
            info = kw["info"]
            self.last_path = info["path"]
            self._add_history(info)
            self._foot("合成完成：%.2fs 生成，音频 %.2fs → %s" % (
                info["seconds"], info["duration"] or 0, os.path.basename(info["path"])))
            self._set_state("模型就绪", "ok")
            if self.var_autoplay.get():
                self._play(info["path"])
        elif kind == "synth_fail":
            self.busy = False
            self.btn_synth.configure(state="normal", text="▶  合成")
            self.pbar.stop()
            self._set_state("合成出错", "err")
            self._log_line("合成失败：" + kw["error"])
            messagebox.showerror("合成失败", kw["error"], parent=self)
        elif kind == "playdone":
            self.playing = None

    def _foot(self, text):
        self.lbl_foot.configure(text=text)

    def _log_line(self, text):
        ts = time.strftime("%H:%M:%S")
        line = "[%s] %s" % (ts, text)
        self.log.insert("end", line + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 1500:   # 防止长期运行后日志面板拖慢界面
            self.log.delete("1.0", "200.0")
        self.log.see("end")
        # 注意：绝对不能用 print()。worker 线程里的 sys.stdout 重定向是全局的，
        # 主线程 print 会被同一个 writer 抓回去 → 日志无限自我投递（CPU/内存爆掉）。
        try:
            self._logf.write(line + "\n")
            self._logf.flush()
        except Exception:
            pass

    def _set_state(self, text, level="idle"):
        color = {"idle": "#c00", "ok": "#0a0", "busy": "#e80", "err": "#c00"}.get(level, "#666")
        self.dot.configure(foreground=color)
        self.lbl_state.configure(text=text, foreground=color if level != "idle" else "#333")

    # ---------------------------------------------------------------- 加载
    def _on_load(self):
        if self.loading or self.busy:
            return
        try:
            gsv = resolve_gsv_home()
        except RuntimeError:
            gsv = self._ask_gsv_home()          # 首次使用：在主线程弹窗引导
            if not gsv:
                self._set_state("未配置 GPT-SoVITS 目录", "err")
                self._log_line("未配置 GPT-SoVITS 目录：点右上角「设置…」选一次即可。")
                return

        self.loading = True
        self.btn_load.configure(text="加载中…", state="disabled")
        self._set_state("正在加载模型 …", "busy")
        self.pbar.start(12)
        device = self.var_device.get()

        def work():
            try:
                eng = LaomushiEngine(PROJECT_DIR, gsv_home=gsv, device=device, log=self._mklog())
                eng.ref_audio = self.var_ref.get().strip() or eng.ref_audio
                eng.ref_text = self.var_reftext.get().strip() or eng.ref_text
                secs = eng.load(warmup=True, on_stage=lambda n, t: self._post("stage", text=t))
                self.engine = eng
                self._post("loaded", seconds=secs, device=device, gsv=gsv)
            except Exception:
                self._post("loadfail", error=traceback.format_exc(limit=6))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 目录配置
    def _ask_gsv_home(self):
        messagebox.showinfo(
            "首次使用：指定 GPT-SoVITS 目录",
            "没有找到 GPT-SoVITS 整合包。\n\n"
            "请选择 GPT-SoVITS 所在的文件夹 —— 里面应该有 runtime\\ 和 GPT_SoVITS\\ 两个目录。\n"
            "选一次就会记住，下次直接启动。", parent=self)
        while True:
            d = filedialog.askdirectory(title="选择 GPT-SoVITS 整合包目录", parent=self)
            if not d:
                return None
            if is_gsv_home(d):
                write_config(d)
                self._log_line("已记住 GPT-SoVITS 目录：%s" % d)
                self._refresh_hint()
                return os.path.abspath(d)
            messagebox.showwarning(
                "目录不对",
                "这个目录里既没有 runtime 也没有 GPT_SoVITS，请重新选择。\n\n选中的是：\n%s" % d,
                parent=self)

    def _on_setup(self):
        if self.loading or self.busy:
            messagebox.showinfo("提示", "正在加载或合成，请稍后再改设置。", parent=self)
            return
        d = filedialog.askdirectory(
            title="选择 GPT-SoVITS 整合包目录（里面有 runtime 和 GPT_SoVITS）", parent=self)
        if not d:
            return
        if not is_gsv_home(d):
            messagebox.showwarning("目录不对", "这个目录里既没有 runtime 也没有 GPT_SoVITS。", parent=self)
            return
        write_config(d)
        self._log_line("已记住 GPT-SoVITS 目录：%s" % d)
        self._refresh_hint()
        messagebox.showinfo("已保存", "已记住目录：\n%s\n\n点「重载模型」生效。" % d, parent=self)

    def _refresh_hint(self):
        try:
            gsv = resolve_gsv_home()
            text = "GPT-SoVITS：%s" % gsv
        except RuntimeError:
            text = "尚未配置 GPT-SoVITS 目录 —— 点右上角「设置…」选择一次即可"
        self.lbl_hint.configure(text=text)

    def _mklog(self):
        return lambda s: self._post("log", text=s)

    # ---------------------------------------------------------------- 合成
    def _on_synth(self):
        if self.busy or self.loading:
            return
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("提示", "请先输入要合成的文本", parent=self)
            return
        if self.engine is None or not self.engine.loaded:
            messagebox.showinfo("提示", "模型还没加载好，请先点「加载模型」", parent=self)
            return

        try:
            seed = int(float(self.var_seed.get().strip() or "-1"))
        except Exception:
            seed = -1

        self.busy = True
        self.btn_synth.configure(state="disabled", text="合成中…")
        self._set_state("正在合成 …", "busy")
        self.pbar.start(12)
        self._foot("合成中，请稍候 …")

        kw = dict(speed=float(self.var_speed.get()), seed=seed,
                  ref_audio=self.var_ref.get().strip() or None,
                  ref_text=self.var_reftext.get().strip() or None)
        engine = self.engine

        def work():
            try:
                info = engine.synth(text, **kw)
                self._post("synth_ok", info=info)
            except Exception:
                self._post("synth_fail", error=traceback.format_exc(limit=6))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- 播放
    def _play(self, path):
        if not path or not os.path.isfile(path):
            return
        if winsound is None:
            os.startfile(path)
            return
        self.player_stop = False
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        self._foot("正在播放：%s" % os.path.basename(path))

    def _replay(self):
        self._play(self.last_path)

    def _stop_play(self):
        if winsound is not None:
            winsound.PlaySound(None, winsound.SND_PURGE)
        self._foot("已停止播放")

    # ---------------------------------------------------------------- 历史
    def _add_history(self, info):
        summary = info.get("text") or info.get("summary") or os.path.basename(info["path"])
        summary = summary.replace("\n", " ")
        if len(summary) > 18:
            summary = summary[:18] + "…"
        dur = "%.1fs" % (info["duration"] or 0)
        ts = time.strftime("%H:%M:%S")
        item = (ts, summary, dur, info["path"])
        self.history.append(item)
        iid = self.tree.insert("", 0, values=(ts, summary, dur))
        self.tree.item(iid, tags=(info["path"],))
        self.tree.see(iid)

    def _scan_existing(self):
        """把 tts_out 里已有的音频也列出来（上游 CLI 生成的也一并显示）。"""
        self.tree.delete(*self.tree.get_children())
        if not os.path.isdir(OUT_DIR):
            self._foot("还没有输出目录：%s" % OUT_DIR)
            return
        files = sorted([f for f in os.listdir(OUT_DIR) if f.lower().endswith(".wav")],
                       key=lambda f: os.path.getmtime(os.path.join(OUT_DIR, f)), reverse=True)
        for f in files[:200]:
            full = os.path.join(OUT_DIR, f)
            dur = self._wav_duration(full)
            ts = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(full)))
            iid = self.tree.insert("", "end", values=(ts[6:], f, dur))
            self.tree.item(iid, tags=(full,))
        self._foot("已列出 %d 个已有音频（双击播放）" % min(len(files), 200))

    def _wav_duration(self, path):
        try:
            import soundfile as sf
            info = sf.info(path)
            return "%.1fs" % (info.frames / float(info.samplerate))
        except Exception:
            return "-"

    def _selected_path(self):
        sel = self.tree.selection()
        if not sel:
            return None
        tags = self.tree.item(sel[0], "tags")
        return tags[0] if tags else None

    def _play_selected(self):
        p = self._selected_path()
        if p:
            self._play(p)

    def _copy_path(self):
        p = self._selected_path()
        if p:
            self.clipboard_clear()
            self.clipboard_append(p)
            self._foot("路径已复制：%s" % p)

    def _del_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        p = self._selected_path()
        if p and os.path.isfile(p) and messagebox.askyesno(
                "删除", "同时删除文件吗？\n%s" % p, parent=self):
            try:
                os.remove(p)
            except Exception as e:
                messagebox.showerror("删除失败", str(e), parent=self)
        self.tree.delete(*sel)

    def _pick_ref(self):
        p = filedialog.askopenfilename(parent=self, title="选择参考音频",
                                       filetypes=[("WAV", "*.wav"), ("所有文件", "*.*")],
                                       initialdir=os.path.join(PROJECT_DIR, "ref"))
        if p:
            self.var_ref.set(p)

    def _open_outdir(self):
        os.makedirs(OUT_DIR, exist_ok=True)
        os.startfile(OUT_DIR)

    # ---------------------------------------------------------------- 杂项
    def _toggle_log(self):
        if self.log_visible:
            self.logframe.grid_remove()
            self.btn_log.configure(text="显示日志 ▾")
        else:
            self.logframe.grid()
            self.btn_log.configure(text="隐藏日志 ▴")
        self.log_visible = not self.log_visible

    def _on_close(self):
        if self.busy and not messagebox.askyesno("退出", "正在合成，确定退出吗？", parent=self):
            return
        self._stop_play()
        if self.engine:
            self.engine.release()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
