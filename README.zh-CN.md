# Video Translate 中文说明

[English README](README.md)

Video Translate 是一个面向 YouTube 和本地视频的字幕制作 Agent。它可以下载视频、字幕和封面；用 OCR 提取内嵌硬字幕；用 ASR 从音频识别字幕；生成并审核 glossary；调用 OpenAI-compatible 大模型翻译字幕；精修和转换字幕格式；并把可播放的外挂字幕复制到视频同目录。

这个项目的核心思路是“人机协作”：Agent 可以同时推进多个视频流程，遇到需要你判断的地方会暂停，等你审核 glossary 或确认路线后继续。

## 主要功能

- **Agent 工作台**：输入 YouTube 链接或视频 ID，自动检测字幕源、推荐路线、等待人工确认。
- **按视频分文件夹管理**：每个 YouTube 视频单独一个文件夹，放视频、源字幕、中文字幕、封面和 `project.yaml`。
- **YouTube 字幕下载**：区分作者上传字幕和自动字幕，可选择语言下载。
- **OCR 硬字幕提取**：支持限定区域、全屏辅助、可视化裁剪预览、源文精修。
- **ASR 音频字幕**：使用 `faster-whisper` 从音频生成源字幕，可选 LLM 原文纠错。
- **Hybrid 路线**：可用作者上传字幕的时间轴定轴，同时用 OCR 还原原声语言文本。
- **Glossary 审核**：自动生成术语草稿，UI 中审核人名、昵称、作品名、专有词；支持罗马音、证据原句和盲翻候选。
- **字幕精修**：逐条改字、合并、删除、去名前缀、去尾逗号、检测半边括号/引号。
- **字幕格式转换**：支持 SRT、VTT、ASS/SSA、LRC、TXT、JSON、Bilibili BCC 等格式。
- **视频贴图处理**：上传图片作为水印或遮挡 Logo，调位置和大小后输出新视频。
- **通用 LLM 配置**：统一使用 `LLM_*` 环境变量和 OpenAI-compatible 配置；示例使用火山方舟/豆包，但命名不绑定供应商。

更详细的 Agent 路线设计见：[docs/youtube_agent_workflows.md](docs/youtube_agent_workflows.md)。

## 快速开始

克隆项目并创建 Python 环境：

```bash
git clone https://github.com/YuqiPlus/Video_Translate.git
cd Video_Translate
conda create -n Video_Translate python=3.11 -y
conda activate Video_Translate
python -m pip install -e ".[dev]"
```

如果要用 ASR：

```bash
python -m pip install -e ".[asr]"
```

复制配置模板：

```bash
cp .env.example .env
cp configs/llm.example.yaml configs/llm.yaml
cp configs/run.example.yaml configs/run.yaml
```

编辑 `.env`：

```text
LLM_API_KEY=你的_API_KEY
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
YTDLP_PROXY=
VIDEO_TRANSLATE_HOST=0.0.0.0
VIDEO_TRANSLATE_PORT=7860
VIDEO_TRANSLATE_DOWNLOAD_DIR=YoutubeDownloads
VIDEO_TRANSLATE_CACHE_DIR=models
VIDEO_TRANSLATE_OCR_DEVICE=auto
```

如果你的网络访问 YouTube 需要代理，只设置 `YTDLP_PROXY`：

```text
YTDLP_PROXY=http://127.0.0.1:7890
```

本地 OCR、ASR、LLM 子进程默认不会继承通用 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`，避免 YouTube 代理影响本地处理或大模型请求。

启动 Agent UI：

```bash
python run_agent_ui.py
```

浏览器打开：

```text
http://127.0.0.1:7860
```

如果跑在服务器上，用服务器 IP 和端口访问，例如：

```text
http://<server-ip>:7860
```

## 前端开发

Python 服务会读取 `frontend/dist`。修改前端代码后需要重新构建：

```bash
cd frontend
npm install
npm run build
cd ..
python run_agent_ui.py
```

## 大模型配置

项目使用 OpenAI-compatible Chat Completions API。更换供应商时通常只需要改：

1. `.env`：更新 `LLM_API_KEY`，必要时更新 `LLM_BASE_URL` / `LLM_MODEL`。
2. `configs/llm.yaml`：如果模型名变化，更新 `defaults.base_url` 和 `defaults.models.*`。

`configs/llm.example.yaml` 示例使用火山方舟/豆包：

```yaml
defaults:
  provider: openai-compatible
  base_url: https://ark.cn-beijing.volces.com/api/coding/v3
  api_key_env: LLM_API_KEY
  models:
    default: doubao-seed-2.0-pro
    pro: doubao-seed-2.0-pro
    lite: doubao-seed-2.0-lite
```

各任务使用哪个模型由 `tasks` 决定。模型选择顺序：

```text
命令行显式 --model
> 任务专用环境变量，例如 ASR_CORRECTION_MODEL
> configs/llm.yaml tasks.<task>.model
> configs/llm.yaml tasks.<task>.model_role 解析到 defaults.models
> .env 全局 LLM_MODEL
> configs/llm.yaml defaults.model
> configs/llm.yaml defaults.models.default
```

旧环境里的 `ARK_*` 变量仍兼容，但新配置建议统一使用 `LLM_*`。

## GPU 和模型缓存

模型缓存默认在项目下的 `models/`。也可以在 `.env` 改：

```text
VIDEO_TRANSLATE_CACHE_DIR=/data/models/video_translate
```

如果要用 PaddleOCR GPU，请安装匹配 CUDA 的 PaddlePaddle GPU 版本。例如 CUDA 12.6：

```bash
python -m pip uninstall -y paddlepaddle
python -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

检查 Paddle 是否能看到 CUDA：

```bash
python -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

当 `ocr.device` 为 `auto` 时，可以用 `.env` 指定默认设备：

```text
VIDEO_TRANSLATE_OCR_DEVICE=gpu:0
```

ASR 使用 `faster-whisper` 时，项目会尝试自动加入 `nvidia-*` Python 包里的 CUDA 库路径。如果仍报 `libcublas.so.12` 或 cuDNN 找不到，请检查环境中的 `nvidia-cublas-cu12` 和 `nvidia-cudnn-cu12`。

## Agent 工作流

典型流程：

1. 在 **Agent** 页输入 YouTube 链接或视频 ID。
2. 如果你知道视频是否有内嵌字幕，先选择“有/没有/不清楚”。
3. Agent 检测标题、时长、字幕轨道，并给出推荐路线。
4. 选择推荐路线，或手动切到 OCR / ASR / 下载字幕路线。
5. 如果需要 OCR，先下载视频并抽帧，调整裁剪区域。
6. 生成 glossary 草稿，进入审核页确认术语。
7. 保存 glossary 后，Agent 会继续当前视频流程并翻译。
8. 根据需要进入字幕精修或格式转换。

Agent 支持多个视频流程并行。运行中的 session 会独立轮询；某个流程等待确认或 glossary 审核时，点击它的卡片处理即可，不会阻塞其他流程。

常见路线：

- **已有中文字幕**：直接下载，可转换格式或整理命名。
- **有原声语言作者字幕**：锁定作者字幕时间轴，用 glossary 引导翻译。
- **只有自动字幕**：可先原文纠错，再生成 glossary 和翻译。
- **视频内嵌硬字幕**：用 OCR 提取源文，再 glossary 和翻译。
- **只有人声**：用 ASR 识别源文，可纠错后翻译。
- **英文定轴 + 原声 OCR**：用作者上传英文字幕的时间轴做锚点，同时 OCR 还原原声语言内容。

## 常用命令

检查依赖和缓存路径：

```bash
python -m video_translate doctor
```

读取 `configs/run.yaml` 运行：

```bash
python run_from_config.py
# 或
video-translate run-config configs/run.yaml
```

从本地视频 OCR 提取字幕：

```bash
python -m video_translate extract "input.mp4" --lang korean --out "outputs/demo"
```

开启全屏辅助 OCR：

```bash
python -m video_translate extract "input.mp4" --lang korean --out "outputs/demo" --scan-full-frame
```

翻译已有 SRT：

```bash
python -m video_translate translate-volcengine "outputs/demo/source.srt" \
  --glossary "configs/glossaries/examples/glossary.example.yaml" \
  --out "outputs/demo/zh.srt"
```

YouTube 和字幕工具：

```bash
python -m video_translate.youtube.download_subtitles "https://www.youtube.com/watch?v=..." --sub-langs ko,en
python -m video_translate.youtube.download_video "https://www.youtube.com/watch?v=..."
python -m video_translate.tools.generate_glossary "YoutubeDownloads/example.ko.srt" --out "outputs/example/glossary.draft.yaml"
python -m video_translate.tools.translate_subtitles "YoutubeDownloads/example.ko.srt" --glossary "outputs/example/glossary.draft.yaml"
python -m video_translate.tools.convert_subtitle "YoutubeDownloads/example.zh.srt" --format bcc
```

`scripts/` 目录下也保留了对应的薄封装脚本，方便手动运行。

## 输出目录

默认下载目录：

```text
YoutubeDownloads/<视频标题>/
```

常见文件：

```text
<视频标题>.mp4
<视频标题>.jpg
<视频标题>.source.srt
<视频标题>.zh.srt
project.yaml
```

Agent 任务状态和中间产物：

```text
outputs/agent_tasks/<task-id>/
outputs/agent_jobs/<job-id>/
```

常见流水线输出：

- `source.srt`：OCR/ASR/下载得到的源语言字幕。
- `zh.srt`：翻译后的中文字幕。
- `tracks.json`：OCR 文本轨迹、框位置和元信息。
- `ignored_tracks.json`：被判断为固定水印/噪声的文本轨迹。
- `tracks_debug.csv`：方便表格查看的 OCR 调试信息。
- `*.bcc`：Bilibili 字幕 JSON。

如果开启 sidecar 复制，生成的字幕会被复制到视频同目录，方便播放器自动加载。

## 不要提交的文件

以下本地数据默认被 Git 忽略：

- `.env`
- `configs/run.yaml`
- `configs/llm.yaml`
- `YoutubeDownloads/`
- `outputs/`
- `models/`
- 生成的视频/字幕文件，例如 `*.mp4`、`*.srt`、`*.vtt`、`*.ass`、`*.bcc`

可复用 glossary 示例放在 `configs/glossaries/examples/`。每个任务生成的 glossary 草稿建议放在 `outputs/agent_tasks/<task-id>/` 或其他被忽略的工作目录。

## 测试

后端测试：

```bash
python -m pytest -q
```

前端单元测试：

```bash
cd frontend
node --test src/*.test.mjs
```

前端构建：

```bash
cd frontend
npm run build
```
