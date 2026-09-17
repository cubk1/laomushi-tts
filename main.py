# -*- coding: utf-8 -*-
import os, sys, io, contextlib, time, logging, warnings

HERE = os.path.dirname(os.path.abspath(__file__))
GSV_HOME = os.environ.get("GSV_HOME")
if not GSV_HOME or not os.path.isdir(GSV_HOME):
    sys.exit("GSV_HOME is missing!")
sys.path.insert(0, GSV_HOME)
sys.path.insert(0, os.path.join(GSV_HOME, "GPT_SoVITS"))
sys.path.insert(0, os.path.join(GSV_HOME, "GPT_SoVITS", "eres2net"))
os.environ["TQDM_DISABLE"] = "1"
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")
try:
    import nltk; nltk.pathsec.ALLOW_PROXIED_FETCH = True
except Exception:
    pass
import soundfile as sf

SOVITS = os.path.join(HERE, "weights", "laomushi_v2_e16.pth")
GPT = os.path.join(HERE, "weights", "laomushi-e20.ckpt")
REF = os.path.join(HERE, "ref", "ref.wav")
REF_TEXT = "今天天气不错，我们一起出去走走吧。"
DEVICE = os.environ.get("TTS_DEVICE", "cuda")


@contextlib.contextmanager
def _quiet():
    d = io.StringIO(); o, e = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = d, d; yield
    finally:
        sys.stdout, sys.stderr = o, e


def tts_cli(input_text=None, output_path=None):
    if output_path:
        output_path = os.path.abspath(output_path)
    os.chdir(GSV_HOME)
    from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
    cfg = TTS_Config(os.path.join(GSV_HOME, "GPT_SoVITS/configs/tts_infer.yaml"))
    cfg.device = DEVICE; cfg.is_half = (DEVICE == "cuda"); cfg.version = "v2Pro"
    cfg.t2s_weights_path = GPT; cfg.vits_weights_path = SOVITS
    print("[loading]")
    with _quiet():
        engine = TTS(cfg)

    def run(text, out, play=True):
        req = {"text": text, "text_lang": "zh", "ref_audio_path": REF,
               "prompt_text": REF_TEXT, "prompt_lang": "zh", "top_k": 15, "top_p": 1.0,
               "temperature": 1.0, "speed_factor": 1.0, "batch_size": 1,
               "split_bucket": False, "parallel_infer": True, "fragment_interval": 0.3}
        with _quiet():
            sr, audio = next(engine.run(req))
        sf.write(out, audio, sr)
        if not play:
            return
        print(f"[saved] {out}")
        try:
            import winsound; winsound.PlaySound(out, winsound.SND_FILENAME)
        except Exception:
            import subprocess, shutil
            ff = shutil.which("ffplay")
            if ff:
                subprocess.run([ff, "-nodisp", "-autoexit", "-loglevel", "quiet", out])

    with _quiet():
        run("预热。", os.path.join(HERE, "_warmup.wav"), play=False)
    print("[ready]")

    out_dir = os.path.join(HERE, "tts_out"); os.makedirs(out_dir, exist_ok=True)
    if input_text:
        run(input_text, output_path or os.path.join(out_dir, f"{int(time.time())}.wav"))
    else:
        i = 0
        while True:
            try:
                t = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not t:
                continue
            i += 1
            run(t, os.path.join(out_dir, f"{i:03d}.wav"))


if __name__ == "__main__":
    tts_cli(sys.argv[1] if len(sys.argv) > 1 else None,
            sys.argv[2] if len(sys.argv) > 2 else None)
