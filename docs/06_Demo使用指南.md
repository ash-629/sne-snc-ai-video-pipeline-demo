# Demo 使用指南

## 1. 运行离线处理流程

在仓库根目录执行：

```sh
python demo/run_demo.py
```

Python 3.10+ 即可。程序以真实 SNE 前四轮原稿及词时间、SNC 前四组三语文本为输入，直接调用仓库内的字幕和检查模块。

结果位于 `demo/output/`：

| 文件 | 用途 |
|---|---|
| `report.json` | 七项检查的汇总结果 |
| `sne/全片.ass` | 生成的逐词高亮字幕 |
| `02_real_sample_tts_check.txt` | 正常样本漏读检查 |
| `05_detect_truncated_cache.txt` | 缺词负例检测 |
| `06_detect_missing_pinyin.txt` | 缺拼音音节检测 |
| `offset_plus_1s.srt` | 配合一秒软开场的时间偏移结果 |

负例检查器返回退出码 1 是预期行为。Demo 会将实际退出码与预期值比较，只有全部检查满足预期时，主程序才返回 0。

## 2. 预览 ComfyUI 批量任务

```sh
python source/skills/dialogue-portrait-videos/scripts/generate.py --config source/skills/dialogue-portrait-videos/examples/demo.example.json --dry-run
```

命令列出 Maya、Ethan 各 5 个片段任务，不会提交推理。可用 `--limit 2` 只查看前两个任务。配置文件引用仓库内两张立绘；完整的 41 节点工作流为相邻的 `wan_api.json`。

实际执行前需要安装匹配的模型和自定义节点、配置 ComfyUI input/output 目录并启动服务。具体参数与限制见 [ComfyUI 说明](08_ComfyUI角色片段生成.md)。

## 3. 查看生成效果

- `cases/comfyui/`：人物立绘和历史生成动作片段。
- `cases/sne/`、`cases/snc/`：一分钟成片预览、封面、字幕及制作记录。

视频样例可以下载后本地播放。它们用于查看实际效果，不是运行离线 Demo 时重新生成的产物。

## 4. 使用自己的输入

保留 `demo/fixtures/` 作为基准样本，在单独目录准备新的脚本和识别结果，再调用对应的生产脚本。各步骤的数据契约见 [架构与数据流](02_架构与数据流.md)。

仅运行字幕与结构检查时不需要在线凭据。配音、模型识别、ComfyUI 生成和平台发布分别需要各自运行环境，不能通过离线检查结果推断这些服务已配置完成。
