# SNE / SNC — AI Video Production Demo

面向英语与中文学习内容的 AI 视频生产 Demo，展示从 **ComfyUI 角色片段生成 → 分句配音 → 字幕对齐与质检 → 视频合成 → 多语言字幕发布** 的处理流程。

代码与样例来自 Simply Natural English（SNE）和 Simply Natural Chinese（SNC）的实际内容制作。提供可离线运行的字幕与质检演示、Wan2.2 工作流、人物片段以及两期完整制作案例。

## 功能

- **角色片段生成**：ComfyUI / Wan2.2 首尾帧工作流，Python 参数覆盖、任务提交、状态轮询与批量归档。
- **语音与画面组装**：Azure Speech 分句合成、角色素材选取、按音频时长拼接和 FFmpeg 封装。
- **字幕处理**：原稿与 Whisper 词时间对齐，生成逐词高亮 ASS 和独立 SRT。
- **质量检查**：漏读与句尾截断检测、中文拼音结构检查、字幕时间偏移。
- **发布集成**：YouTube 上传、字幕轨道管理、状态回读和学习文档生成。

## 快速开始

### 离线字幕与质检 Demo

Python 3.10+，无需密钥、GPU、FFmpeg 或第三方 Python 包：

```sh
python demo/run_demo.py
```

Windows 也可双击 `运行离线演示.cmd`。结果写入 `demo/output/`，包括 ASS 字幕、检查日志、时间偏移示例和 `report.json`。

演示使用真实脚本与已有识别结果，验证正常样本、缺词负例和缺拼音负例。不会调用模型或上传视频。[演示指南](docs/06_Demo使用指南.md) · [验证记录](docs/07_验证记录.md)

### ComfyUI 批量生成任务预览

```sh
python source/skills/dialogue-portrait-videos/scripts/generate.py --config source/skills/dialogue-portrait-videos/examples/demo.example.json --dry-run
```

预览两位角色共 10 个任务，无需启动 ComfyUI。实际生成需要配置模型、自定义节点及输入输出目录。[工作流与 API 调用说明](docs/08_ComfyUI角色片段生成.md)

## 作品与素材

| SNE · Fair Enough | SNC · 差不多 |
|---|---|
| ![SNE](cases/sne/cover.png) | ![SNC](cases/snc/cover.png) |
| [60 秒预览](cases/sne/preview_60s.mp4) · [完整视频](https://www.youtube.com/watch?v=ysUnLJgMOKk) | [60 秒预览](cases/snc/preview_60s.mp4) · [完整视频](https://www.youtube.com/watch?v=ZbZs0fHt7Vc) |

ComfyUI 输入与历史输出：[Maya 立绘](cases/comfyui/maya_portrait.png) / [动作片段](cases/comfyui/maya_clip_001.mp4)，[Ethan 立绘](cases/comfyui/ethan_portrait.png) / [动作片段](cases/comfyui/ethan_clip_001.mp4)。

## 项目结构

| 路径 | 内容 |
|---|---|
| `source/skills/` | Python 处理模块、ComfyUI API 工作流和配置 |
| `demo/fixtures/` | SNE 原稿与词时间、SNC 三语文本 |
| `demo/output/` | 离线演示输出与检查报告 |
| `cases/` | 封面、人物素材、视频片段、字幕和制作记录 |
| `docs/` | 架构、源码说明、使用指南和已知限制 |
| `SOURCE_MANIFEST.json` | 代码与样例的来源、摘要和适配记录 |

[项目说明](docs/01_项目说明.md) · [架构与数据流](docs/02_架构与数据流.md) · [源码导读](docs/03_源码导读.md) · [案例](docs/04_案例与作品.md) · [已知限制与后续方向](docs/05_工程边界与改进.md)

## 完整环境与运行范围

完整生产流程使用 Python、ComfyUI/Wan2.2、Azure Speech、faster-whisper、FFmpeg/ffprobe、Google API 与 python-docx。`source/requirements.production-snapshot.txt` 为原环境依赖记录，离线 Demo 不需要安装这些依赖。

当前实现以 CLI 和文件式流程为主；角色素材生成、配音、媒体加工与发布分阶段执行。图像生成、内容翻译和最终质量复核包含交互式 AI 与人工处理环节。Web 界面、数据库和任务队列属于后续方向。

模型权重、完整角色素材库和账号凭据不随仓库分发。在线步骤需要自己的配置；正式 TTS 前先用 1–2 句探针确认非空 WAV、PCM 16-bit、48 kHz、单声道。源程序包含真实上传功能，离线演示不会执行这些操作。

## 来源

本项目从实际频道工作流提取，代码结合 AI 辅助开发和持续生产反馈迭代。来源及样例适配记录见 `SOURCE_MANIFEST.json`。历史作品与生成片段为已有产物，离线 Demo 使用缓存的识别结果验证处理逻辑。

仓库未附通用开源许可；作品、角色与素材的使用范围应单独确认。
