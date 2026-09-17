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