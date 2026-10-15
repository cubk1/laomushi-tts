# -*- coding: utf-8 -*-
"""老牧师口音合成器 - 引擎层（与界面解耦，可单独使用）

设计要点（相对上游 main.py 的改动动机）:
1. 不修改上游任何文件，只把「加载引擎」与「合成一句」抽成可复用类；
2. 引擎只加载一次，之后每句合成为秒级 —— 这是 GUI 必须的前提；
3. 上游 main.py 用 _quiet() 把 stdout/stderr 全吞了，出错只会静默无反应；
   这里改为可注入的 log 回调，异常原样抛出；
4. 上游 main.py 会 os.chdir(GSV_HOME)，这里进出都恢复 cwd，避免影响 GUI 进程。
"""

import os
import sys
import time
import contextlib
import logging
import warnings

# 配置只存一行文本：GPT-SoVITS 整合包的绝对路径（见 gui/config.local.txt）。
# 用「一行文本」而不是 json，是为了让 run_gui.bat / setup.bat 也能直接读，
# 否则 .bat 得靠 findstr 解析 json，很容易出问题。
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.txt")
DEFAULT_REF_TEXT = "今天天气不错，我们一起出去走走吧。"


def read_config():
    """读配置。文件可能由 .bat（系统 ANSI）或本程序（UTF-8）写入，两种编码都试。"""
    try:
        with open(CONFIG_FILE, "rb") as f:
            raw = f.read()
    except Exception:
        return None
    for enc in ("utf-8-sig", "mbcs", "gbk"):
        try:
            text = raw.decode(enc)
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return None


def write_config(path):
    """写入配置。刻意用系统 ANSI 编码，好让 .bat 里的 for/f 正确读到中文路径。"""
    p = os.path.abspath(path)
    enc = "mbcs" if os.name == "nt" else "utf-8"
    with open(CONFIG_FILE, "wb") as f:
        f.write((p + "\n").encode(enc, "replace"))
    return p


def is_gsv_home(path):
    """目录是否像一个 GPT-SoVITS 整合包。"""
    if not path or not os.path.isdir(path):
        return False
    return (os.path.isfile(os.path.join(path, "runtime", "python.exe"))
            or os.path.isdir(os.path.join(path, "GPT_SoVITS")))


def find_python(gsv_home):
    """整合包自带的解释器（优先无控制台版）。"""
    for name in ("pythonw.exe", "python.exe"):
        p = os.path.join(gsv_home, "runtime", name)
        if os.path.isfile(p):
            return p
    return None


def _scan_common_locations():
    """兜底：在常见盘符下找名字像 GPT-SoVITS 的目录，省得用户手填路径。"""
    found = []
    for drive in ("C:\\", "D:\\", "E:\\", "F:\\"):
        try:
            entries = os.listdir(drive)
        except Exception:
            continue
        for name in entries:
            low = name.lower()
            if "sovits" in low or low.startswith("gsv"):
                p = os.path.join(drive, name)
                if is_gsv_home(p):
                    found.append(p)
    return found


def resolve_gsv_home(explicit=None):
    """定位 GPT-SoVITS 整合包：参数 → 环境变量 GSV_HOME → 配置文件 → 常见位置扫描。"""
    tried = []
    candidates = [explicit, os.environ.get("GSV_HOME"), read_config()]
    candidates += _scan_common_locations()
    for cand in candidates:
        if not cand:
            continue
        tried.append(cand)
        if is_gsv_home(cand):
            return os.path.abspath(cand)
    raise RuntimeError(
        "找不到 GPT-SoVITS 整合包（该目录里应有 runtime\\ 和 GPT_SoVITS\\）。\n"
        "请双击 gui\\setup.bat 选一次目录，或设置环境变量 GSV_HOME。\n"
        "已尝试：%s" % ("；".join(tried) if tried else "（没有可用的候选路径）")
    )


class _LineWriter(object):
    """把引擎的输出按行转发给回调（GUI 日志面板用）。

    谨慎处理三件事，否则会把推理进程拖死：
    1. 进度条用 '\\r' 更新、可能长时间没有 '\\n'，必须把 '\\r' 也当行分隔；
    2. 缓冲区必须有上限，否则无换行输出会累积到 GB 级；
    3. 相同内容的重复进度更新要丢弃（去重）。
    """

    MAX_BUF = 4096

    def __init__(self, emit):
        self._emit = emit
        self._buf = ""
        self._last = None

    def write(self, s):
        if not s:
            return 0
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        self._buf += s
        if len(self._buf) > self.MAX_BUF:
            self._buf = self._buf[-self.MAX_BUF:]
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line and line != self._last:
                self._last = line
                self._emit(line)
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


@contextlib.contextmanager
def _redirect(emit):
    """stdout/stderr 一起接到安全 writer 上。

    用 pythonw.exe 启动时 sys.stdout 可能是 None，任何 print 都会 AttributeError，
    所以这个重定向同时也是「防崩溃」措施。
    """
    writer = _LineWriter(emit)
    with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
        yield


class LaomushiEngine(object):
    """常驻式推理引擎：构造后调用 load() 一次，之后可反复 synth()。"""

    def __init__(self, project_dir, gsv_home=None, device=None, log=None):
        self.project_dir = os.path.abspath(project_dir)
        self.gsv_home = None          # load() 时才解析
        self._gsv_home_arg = gsv_home
        self.device = device or os.environ.get("TTS_DEVICE") or "cuda"
        self.ref_audio = os.path.join(self.project_dir, "ref", "ref.wav")
        self.ref_text = DEFAULT_REF_TEXT
        self.engine = None
        self.loaded = False
        self.load_seconds = None
        self._log = log or (lambda msg: None)
        self._prev_cwd = None

    # ---------------------------------------------------------------- 内部
    def _prepare(self):
        os.environ.setdefault("TQDM_DISABLE", "1")
        logging.disable(logging.WARNING)
        warnings.filterwarnings("ignore")
        gsv = resolve_gsv_home(self._gsv_home_arg)
        self.gsv_home = gsv
        for p in (gsv, os.path.join(gsv, "GPT_SoVITS"), os.path.join(gsv, "GPT_SoVITS", "eres2net")):
            if p not in sys.path:
                sys.path.insert(0, p)
        return gsv

    def weights(self):
        return (
            os.path.join(self.project_dir, "weights", "laomushi-e20.ckpt"),
            os.path.join(self.project_dir, "weights", "laomushi_v2_e16.pth"),
        )

    # ---------------------------------------------------------------- 加载
    def load(self, warmup=True, on_stage=None):
        """加载权重并预热。on_stage(stage, text) 用于界面显示进度。"""

        def stage(name, text):
            self._log(text)
            if on_stage:
                on_stage(name, text)

        gsv = self._prepare()
        gpt, sovits = self.weights()
        for p in (gpt, sovits, self.ref_audio):
            if not os.path.isfile(p):
                raise RuntimeError("缺少必需文件：%s" % p)

        stage("import", "正在导入推理模块 …")
        t0 = time.time()
        self._prev_cwd = os.getcwd()
        with _redirect(self._log):
            os.chdir(gsv)
            from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config

            stage("config", "正在读取 tts_infer.yaml 配置 …")
            cfg = TTS_Config(os.path.join(gsv, "GPT_SoVITS", "configs", "tts_infer.yaml"))
            cfg.device = self.device
            cfg.is_half = (self.device == "cuda")
            cfg.version = "v2Pro"
            cfg.t2s_weights_path = gpt
            cfg.vits_weights_path = sovits

            stage("weights", "正在加载老牧师 GPT / SoVITS 权重（首次约 1 分钟）…")
            self.engine = TTS(cfg)

            if warmup:
                stage("warmup", "正在预热（首次 CUDA 初始化，请稍候）…")
                self._synth_raw("预热。", os.path.join(self.project_dir, "_warmup_gui.wav"))

        self.load_seconds = round(time.time() - t0, 1)
        self.loaded = True
        stage("ready", "模型就绪（加载耗时 %.1fs，设备 %s）" % (self.load_seconds, self.device))
        return self.load_seconds

    # ---------------------------------------------------------------- 合成
    def _synth_raw(self, text, out_path, speed=1.0, seed=None,
                   top_k=15, top_p=1.0, temperature=1.0,
                   ref_audio=None, ref_text=None):
        import soundfile as sf

        req = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": ref_audio or self.ref_audio,
            "prompt_text": ref_text if ref_text is not None else self.ref_text,
            "prompt_lang": "zh",
            "top_k": top_k,
            "top_p": top_p,
            "temperature": temperature,
            "speed_factor": speed,
            "batch_size": 1,
            "split_bucket": False,
            "parallel_infer": True,
            "fragment_interval": 0.3,
        }
        if seed is not None and seed >= 0:
            req["seed"] = int(seed)
        sr, audio = next(self.engine.run(req))
        sf.write(out_path, audio, sr)
        return sr, audio

    def synth(self, text, out_path=None, **kw):
        """合成一句，返回 {path, seconds, duration, samplerate}。"""
        if not self.loaded:
            raise RuntimeError("引擎尚未加载，请先调用 load()")
        text = (text or "").strip()
        if not text:
            raise ValueError("文本为空")
        if out_path is None:
            out_dir = os.path.join(self.project_dir, "tts_out")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "%d.wav" % int(time.time()))
        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        t0 = time.time()
        with _redirect(self._log):
            sr, audio = self._synth_raw(text, out_path, **kw)
        seconds = round(time.time() - t0, 2)
        try:
            duration = round(len(audio) / float(sr), 2)
        except Exception:
            duration = None
        return {"path": out_path, "seconds": seconds,
                "duration": duration, "samplerate": sr}

    # ---------------------------------------------------------------- 关闭
    def release(self):
        try:
            self.engine = None
            self.loaded = False
        finally:
            if self._prev_cwd:
                try:
                    os.chdir(self._prev_cwd)
                except Exception:
                    pass
