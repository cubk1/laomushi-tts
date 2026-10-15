# 老牧师口音GPT-SoVITS生成器

- 前往[Releases](https://github.com/cubk1/laomushi-tts/releases)下载两个文件
    * `laomushi-e20.ckpt`
    * `laomushi_v2_e16.pth`
- 放置这两个文件到`weights`文件夹
- 安装[GPT-SoVITS](https://huggingface.co/lj1995/GPT-SoVITS-windows-package)
- 设置环境变量：`set GSV_HOME=GPT-SoVITS路径`
- 使用GPT-SoVITS中的venv运行main.py

```bash
GPT-SoVITS\venv\Scripts\python.exe main.py
```

输出音频保存在本目录 `tts_out/` 下。

## 图形界面（可选）

不想一句一句敲命令行的话，`gui/` 下有一个 Windows 桌面窗口（tkinter，零额外依赖）：

1. 把两个权重文件放进 `weights/`
2. 双击 `gui\run_gui.bat`，首次会提示选择 GPT-SoVITS 目录，选一次即记住

窗口支持：多行编辑重发、语速/随机种子/参考音频可调、合成历史双击播放、进度条与运行日志。
详见 [gui/README.md](gui/README.md)。