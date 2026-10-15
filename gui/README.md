# 老牧师口音合成器 · 桌面界面（tkinter）

给 [laomushi-tts](https://github.com/cubk1/laomushi-tts) 加的一个 Windows 桌面窗口，
不用命令行一句一句敲，模型只加载一次，之后每句合成为秒级。

**零额外依赖**：只用 GPT-SoVITS 整合包自带的 Python（tkinter / soundfile），不用 pip 装任何东西。
原有 `main.py` 一行未改，两者互不影响。

## 快速开始

1. 按主 README 的说明，把两个权重文件放进 `weights/`
   （`laomushi-e20.ckpt`、`laomushi_v2_e16.pth`）
2. 装好 [GPT-SoVITS](https://huggingface.co/lj1995/GPT-SoVITS-windows-package) 整合包（需要它自带的 runtime）
3. 双击 **`run_gui.bat`**
   - 第一次启动会弹出「选择 GPT-SoVITS 目录」，选一次就记住了（写入 `config.local.txt`）
   - 之后窗口顶部显示「正在加载模型 …」，**首次约 1 分钟**（加载权重 + 预热 CUDA），变绿后即可合成

出问题时用 `run_gui.bat --console` 启动，会保留一个控制台窗口显示日志。

## 界面

| 区域 | 说明 |
| --- | --- |
| 顶栏 | 状态灯（红=未就绪 / 橙=加载中 / 绿=就绪）、设备选择（cuda / cpu）、「加载模型 / 重载」、「设置…」 |
| 合成文本 | 多行输入，可反复修改重发；`Ctrl+Enter` 或 `F5` 合成 |
| 参数 | 语速滑条、随机种子（`-1` 每次随机，填具体数字可复现同一句）、参考音频与参考文本 |
| 操作 | 合成、重播、停止、打开输出目录、清空文本 |
| 合成历史 | 双击播放；也会列出 `tts_out/` 里已有的音频；可复制路径、删除 |
| 运行日志 | 底部「显示日志」展开，排查问题时看 |

结果保存在 `tts_out/`，与命令行版本共用同一个目录。

## 命令行参数

```
app.py [--ui-only] [--project DIR] [--device cuda|cpu]
```

- `--ui-only`：只开界面、不加载模型（快速看外观）
- `--project DIR`：指定项目目录（默认是 `gui/` 的上一级，也就是仓库根）
- `--device cpu`：没有兼容的 N 卡时用 CPU 跑（会慢很多）

## 它是怎么找到 GPT-SoVITS 的

按这个顺序找，命中即止：

1. `--gsv-home` 参数 / 环境变量 `GSV_HOME`
2. `gui/config.local.txt`（一行路径，setup.bat 或界面里的「设置…」写入）
3. 在 C:/D:/E:/F: 盘扫一遍名字里带 `sovits` 的目录

都不行才会弹窗让你选目录。

## 已知限制

- **必须用整合包自带的 Python 3.9 运行**（`torch 2.7 + cu128` 只装在那里），系统的 32 位 Python 跑不了
- 首次加载约 1 分钟属正常；显存 8GB 的话，别同时开官方 `webui.py`
- 权重 288MB + 整合包数 GB，所以**不做**便携 exe，只在本机用
- 只在 Windows 上验证过（用到了 `winsound` 播放）

## 文件

- `engine.py` —— 引擎层：加载一次 + 反复合成，与界面解耦，可被别的脚本 import
- `app.py` —— tkinter 界面
- `run_gui.bat` / `setup.bat` —— 启动器与首次配置向导
