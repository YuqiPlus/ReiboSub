# OCR 开发与迁移指南

本文档说明 OCR Lab 的版本边界、调试产物、免重跑入口，以及在不同机器之间迁移实验数据的方法。文档只使用占位路径；真实视频、字幕、API Key 和调试目录都不应提交到 Git。

## 1. 三套 OCR 流程

| 版本 | 提取与后处理 | 定位 |
| --- | --- | --- |
| OCR 1.0 | 自动主字幕 OCR、旧文本清理、旧翻译流程 | 兼容历史任务 |
| OCR 2.0 | 区域 OCR、框/轨迹证据去噪、锁定原时间轴翻译 | 保留兼容版 |
| OCR 3.0 | 区域 OCR、几何软提示、文字纠错、画面字/对白分层、锁定时间轴翻译 | 当前稳定版、Agent 默认 |

OCR 2.0 和 3.0 的调试目录、按钮和最终 SRT 相互隔离。同一个视频可以保留两套目录做对照；切换新任务默认值不会改写既有任务保存的版本。

## 2. OCR Lab 能做什么

- 从素材库或本地路径选择视频。
- 抽取一帧并拖动、缩放字幕区域。
- 可选一个 Logo/固定画面字排除框。
- 调整语言、采样 FPS、置信度和边界平滑参数。
- 完整运行 PaddleOCR，保存逐帧框、轨迹和机器字幕。
- 复用已有 JSON，只重建或重跑某个 LLM 精修阶段。
- 在素材库中分别查看 OCR 2.0、OCR 3.0 及其产物。

调试目录位于：

```text
${VIDEO_TRANSLATE_DOWNLOAD_DIR}/debug/<video-title>/
${VIDEO_TRANSLATE_DOWNLOAD_DIR}/debug/<video-title>__ocr3_<shape-mode>/
```

其中 `<shape-mode>` 例如 `horizontal_preferred`。目录名只是版本隔离手段，不应写死到代码或公开文档。

## 3. 主要调试产物

所有版本通常会用到：

```text
run.yaml
tracks.json
ocr_boxes.json
ocr_sample_frames.json
tracks_debug.csv
```

OCR 2.0 常见字幕产物：

```text
source.machine.srt
source.rebuilt.srt
source.refined.srt
source.track_refined.srt
source.layered.srt
ocr_layers.json
```

OCR 3.0 独立产物：

```text
source.geometry_refined.srt
ocr_geometry.json
source.v3.refined.srt
source.v3.layered.srt
ocr_v3_layers.json
```

具体文件是否存在取决于运行过哪些阶段。素材库会优先把相应版本的最终成品识别为当前源字幕。

当前 OCR 3.0 分层策略包含 `v3.1-moving-surface-v1` 修订：没有物体随动证据的斜体节目花字仍受保护；
明显倾斜且随画面物体一起移动的文字会标记为物品表面候选。只有当同一 cue 另有更大、水平且稳定的
节目主文案时，分层模型才会结合逐帧文字与上下文判断物品字和小尺寸图标噪声。几何提示始终是软证据，
单靠倾角或一次运动信号不会在服务端硬删字幕。

`v3.1-moving-surface-v1` 是 OCR 3.0 稳定基线的不可变策略标记。后续若调整识别策略，必须使用新的
revision 和缓存隔离值，不能原地改变该标记对应的行为；这样已有 3.0 成品和调试结果可以持续复现。

## 4. 什么时候不需要重新跑 OCR

如果已有 `tracks.json` 和 `ocr_boxes.json`，可以跳过耗时的视频解码与 PaddleOCR：

- **OCR 2.0 从 JSON 重建 + 轨迹精修**：重建机器字幕并运行 2.0 轨迹型 LLM 精修。
- **OCR 2.0 仅跑分层精修**：复用已有字幕与框证据。
- **OCR 3.0 几何精修**：复用轨迹与框，只生成几何/语义提示。
- **OCR 3.0 文字 + 分层精修**：复用机器字幕、框、轨迹和可选几何提示。
- **OCR 3.0 仅重跑分层**：复用 `source.v3.refined.srt`，是最快的 3.0 调参入口。

日志出现类似下面的信息，说明确实跳过了视频 OCR：

```text
rebuild: using existing OCR JSON; video decoding is skipped
layered_refine: using existing refined SRT/OCR boxes; video decoding is skipped
```

## 5. 迁移到另一台机器

代码通过 Git 迁移；本机配置和 OCR 证据需要安全地单独迁移。

Git 不包含以下文件：

- `configs/provider_secrets.yaml`
- `configs/provider_profiles.yaml`
- `configs/reibosub.yaml`
- `configs/local_runtime.yaml`
- `configs/app_settings.yaml`
- 仍在使用时才迁移旧版 `configs/llm.yaml`、`configs/providers/*.yml` 或高级 CLI 的 `configs/run.yaml`
- `YoutubeDownloads/`、`outputs/`、`models/`

不要把真实 API Key 写进交接文档、聊天记录或 Git 提交。优先在目标机器的设置页重新录入；必须传输时使用 SSH、密码管理器或服务器 Secret 管理。

只继续 JSON 重建/LLM 精修时，最少迁移：

```text
tracks.json
ocr_boxes.json
run.yaml
```

为了对照结果，建议连同机器字幕、精修字幕、CSV 和采样帧 JSON 一起迁移。只有需要播放器人工核对或重新 OCR 时才需要原视频。

示例打包：

```bash
tar -caf ocr-debug-handoff.tar.gz \
  -C "$VIDEO_TRANSLATE_DOWNLOAD_DIR/debug" \
  "<video-title>"
```

目标机器解压：

```bash
mkdir -p "$VIDEO_TRANSLATE_DOWNLOAD_DIR/debug"
tar -xaf ocr-debug-handoff.tar.gz \
  -C "$VIDEO_TRANSLATE_DOWNLOAD_DIR/debug"
```

后端会限制可访问路径。调试目录必须位于配置的下载根目录下，不能指向任意系统目录。

## 6. 环境准备

推荐从仓库环境文件创建环境：

```bash
conda env create -f environment.yml
conda activate reibosub
cd frontend
npm ci
npm run build
cd ..
```

复制本机启动模板（可选）：

```bash
cp configs/reibosub.example.yaml configs/reibosub.yaml
```

重新运行 PaddleOCR 时，安装与 CUDA 匹配的 PaddlePaddle GPU 包。旧机器若已经在 `configs/local_runtime.yaml` 配置了设备，会继续兼容读取；临时指定设备也可以使用：

```bash
VIDEO_TRANSLATE_OCR_DEVICE=gpu:0 python run_agent_ui.py
```

只复用 JSON 执行 LLM 精修时，不需要重新下载 OCR 模型或重新解码视频。模型缓存 `models/` 可以安全地重新生成，也可以在机器之间单独复制。

## 7. 验收建议

先验证代码：

```bash
python -m pytest -q
cd frontend && npm run build && cd ..
python run_agent_ui.py
```

再用一段你有权处理的短视频建立自己的回归样例，记录：

- 总字幕条数。
- 极短字幕数量。
- 孤立单字、拉丁字母或数字噪声数量。
- 渐进出现字幕是否被完整合并。
- 画面配字和下方对白是否按预期分层。
- 时间轴是否保持稳定、相邻字幕是否意外重叠。

不要把真实回归视频或生成字幕放进仓库。若需要公开测试夹具，请自行制作或使用明确允许再分发的短素材，并删除人名、频道、路径和任务 ID。

## 8. 运行注意事项

- 活动 job、运行日志和执行进程在内存中，重启后不会继续；Agent 任务记录和已经写入磁盘的产物仍会保留。
- OCR 或 LLM 任务运行时不要重启服务；先在任务日志中确认没有运行中的任务。
- `h264 mmco: unref short failure` 是视频解码器警告，不等于 OCR 卡死；如果进度继续增长，可以先观察。
- 每轮实验保留带版本含义的独立 SRT，避免覆盖后无法对比。
- 优先调整证据、分类和动作约束；不要让 LLM 自由改写时间段或把所有逐帧候选直接拼接。
