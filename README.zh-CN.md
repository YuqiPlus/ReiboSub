# ReiboSub 中文说明

[English README](README.md)

ReiboSub 是一个面向 YouTube 和本地视频的字幕制作 Agent。它可以下载视频、字幕和封面；用 OCR 提取内嵌硬字幕；用 ASR 从音频识别字幕；生成并审核 glossary；调用 OpenAI-compatible 大模型翻译字幕；精修和转换字幕格式；并把可播放的外挂字幕复制到视频同目录。

这个项目的核心思路是“人机协作”：Agent 可以同时推进多个视频流程，遇到需要你判断的地方会暂停，等你审核 glossary 或确认路线后继续。

## 主要功能

- **Agent 工作台**：输入 YouTube 链接或视频 ID，自动检测字幕源、推荐路线、等待人工确认。
- **按视频分文件夹管理**：每个 YouTube 视频单独一个文件夹，放视频、源字幕、中文字幕、封面和 `project.yaml`。
- **YouTube 字幕下载**：区分作者上传字幕和自动字幕，可选择语言下载。
- **OCR 硬字幕提取**：保留旧版 OCR，并提供相互隔离的 OCR 2.0 稳定流程与 OCR 3.0 几何/分层实验流程。
- **ASR 音频字幕**：使用 `faster-whisper` 从音频生成源字幕，可选 LLM 原文纠错。
- **视频上传流程**：在浏览器里上传本地视频后，直接启动 ASR 中文字幕任务。
- **Hybrid 路线**：可用作者上传字幕的时间轴定轴，同时用 OCR 还原原声语言文本。
- **Glossary 审核**：自动生成术语草稿，UI 中审核人名、昵称、作品名、专有词；支持罗马音、证据原句和盲翻候选。
- **字幕精修**：逐条改字和时间轴、50 步撤回、按单条区间播放并在画面叠加字幕，也支持新增、合并、删除和批量清理。
- **字幕格式转换**：支持 SRT、VTT、ASS/SSA、LRC、TXT、JSON、Bilibili BCC 等格式。
- **视频贴图处理**：上传图片作为水印或遮挡 Logo，调位置和大小后输出新视频。
- **模型服务设置**：在网页中新增 OpenAI-compatible 服务、拉取模型，并给各个 LLM 模块分别绑定服务商和模型。

Agent 路线的设计说明见：[docs/youtube_agent_workflows.md](docs/youtube_agent_workflows.md)。其中包含设计背景和后续构想，不保证每一项都已实现。

> [!IMPORTANT]
> 这是一个可信用户使用的本地工具，Web UI 没有账号或登录鉴权。默认只监听 `127.0.0.1`，不要把服务直接暴露到公网。远程服务器推荐使用 SSH 端口转发，详见 [SECURITY.md](SECURITY.md)。

## 快速开始

先安装系统工具：

- Python 3.10 或更新版本，推荐 Python 3.11。
- `ffmpeg` 需要在 `PATH` 里，用于视频/音频处理和字幕封装。
- 从源码首次运行 Web UI 需要 Node.js 20 或更新版本，因为构建产物不提交到 Git。

克隆项目并创建 Python 环境：

```bash
git clone https://github.com/YuqiPlus/ReiboSub.git
cd ReiboSub
conda create -n reibosub python=3.11 -y
conda activate reibosub
python -m pip install -U pip
python -m pip install -e ".[dev,asr,ocr-cpu]"
```

也可以直接使用提供的 conda 环境文件：

```bash
conda env create -f environment.yml
conda activate reibosub
```

如果只想最小安装，不需要 ASR 和测试依赖：

```bash
python -m pip install -e ".[ocr-cpu]"
```

如果希望直接使用 requirements，标准 CPU OCR + ASR 只需：

```bash
python -m pip install -r requirements.txt
```

测试依赖统一由 `pyproject.toml` 的 `dev` extra 管理：

```bash
python -m pip install -e ".[dev]"
```

GPU OCR 不要安装 CPU requirements，请直接使用下文的 CUDA 安装步骤。

首次从源码运行必须构建前端：

```bash
cd frontend
npm ci
npm run build
cd ..
```

可选：复制唯一的本机启动配置。默认值已经可以直接启动；只有需要修改素材目录、YouTube 代理、监听地址或端口时才需要这个文件。

```bash
cp configs/reibosub.example.yaml configs/reibosub.yaml
```

示例：

```yaml
media_dir: YoutubeDownloads
youtube_proxy: ""
host: 127.0.0.1
port: 7860
```

如果你的网络访问 YouTube 需要代理，只设置 `youtube_proxy`：

```yaml
youtube_proxy: http://127.0.0.1:7890
```

本地 OCR、ASR、LLM 子进程默认不会继承通用 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`，避免 YouTube 代理影响本地处理或大模型请求。

已有安装可以继续保留旧的 `configs/local_runtime.yaml`、`.env` 和 `configs/llm.yaml`，后端仍会兼容读取，不需要迁移或删除。

启动 Agent UI：

```bash
python run_agent_ui.py
```

浏览器打开：

```text
http://127.0.0.1:7860
```

如果跑在远程服务器上，保持服务监听回环地址，并从自己的电脑建立 SSH 隧道：

```bash
ssh -L 7860:127.0.0.1:7860 user@server
```

然后仍在本机打开 `http://127.0.0.1:7860`。只有在可信局域网内才建议显式运行 `python run_agent_ui.py --host 0.0.0.0`。

### 首次配置模型服务

首次打开网页后：

1. 进入 **设置 → 新增服务商**。
2. 填写稳定的 Provider ID、显示名称、OpenAI-compatible API Base URL 和 API Key。
3. 点击“创建并获取模型”；如果服务不支持 `/models`，直接填写静态模型名称即可。
4. 选择该服务商的默认模型，再给翻译、Glossary、OCR 精修等模块选择服务商和模型。

网页会把服务商信息保存在 Git 忽略的 `configs/provider_profiles.yaml`，把连接地址和 API Key 保存在同样被忽略的 `configs/provider_secrets.yaml`。Key 是只写字段，不会从后端回显；新安装无需复制或手工维护 `configs/providers/` 下的文件。

## 前端开发

Python 服务会读取 `frontend/dist`。生产式本地运行使用 `npm ci && npm run build`。开发时可以分别启动 Python 后端和 Vite：

```bash
# 终端 1
python run_agent_ui.py

# 终端 2
cd frontend
npm ci
npm run dev
```

开发服务器默认是 `http://127.0.0.1:5173`，并把 `/api` 转发到 `7860`。提交前仍需运行 `npm run build`。

## 大模型配置

项目使用 OpenAI-compatible Chat Completions API。Web UI 的“设置”页现在可以保存新任务的默认语言、默认服务配置，以及各 LLM 模块使用的模型。

服务商统一在设置页创建和管理。填写 API Base URL 与 Key 后拉取该服务支持的模型，选择默认模型，再给翻译、Glossary、OCR 精修等模块绑定模型。如果服务不支持 `/models`，也可以在同一页维护静态模型列表。

API Key 和 API 地址直接在设置页管理，不需要 `.env`。服务商名称、模型列表和默认模型保存在 `configs/provider_profiles.yaml`；连接地址和密钥保存在 `configs/provider_secrets.yaml`。两者均被 Git 忽略，其中密钥文件权限会强制设为 `0600`。密钥输入是只写的：后端只返回是否已配置和配置来源，绝不会把现有密钥或尾号回显到浏览器。

远程网页允许录入或替换 Key；服务域名跨站变更需要从服务器本机或 SSH 端口转发访问，模型列表 URL 也必须与 API Base URL 同源。由于密钥通过网页提交时仍会经过网络，远程使用请通过 HTTPS 或 SSH 隧道，不要在不可信的明文 HTTP 网络中录入。

设置页也可以新增、编辑和删除本地 OpenAI-compatible 服务商。普通用户不需要手工编辑上述文件。Provider ID 会被已有绑定引用，因此保持不可直接修改；删除服务商时，受影响的绑定会迁移到所选替代服务，并重置为它的默认模型。

旧部署使用的 `.env`、`configs/llm.yaml` 和 `configs/providers/*.yml` 仍然兼容读取，但不再作为新安装的配置方式。

## GPU 和模型缓存

模型缓存默认在项目下的 `models/`。

如果要用 PaddleOCR GPU，请安装匹配 CUDA 的 PaddlePaddle GPU 版本。例如 CUDA 12.6：

```bash
python -m pip uninstall -y paddlepaddle paddlepaddle-gpu
python -m pip install -r requirements-gpu-cu126.txt
python -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
# 可选：开发和测试环境再执行
python -m pip install -e ".[dev]"
```

GPU requirements 文件会安装项目通用依赖、`faster-whisper` 和常用 CUDA Python wheels，但不会安装 CPU Paddle；Paddle GPU 本体由下一条 CUDA 专用源命令安装。

检查 Paddle 是否能看到 CUDA：

```bash
python -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

当 OCR 设备为 `auto` 时，ReiboSub 会自动选择可用设备；各 OCR 路线仍可以显式选择 CPU 或具体 GPU。旧本机运行配置里的高级设备覆盖仍然兼容。

ASR 使用 `faster-whisper` 时，项目会尝试自动加入 `nvidia-*` Python 包里的 CUDA 库路径。如果仍报 `libcublas.so.12` 或 cuDNN 找不到，请检查环境中的 `nvidia-cublas-cu12` 和 `nvidia-cudnn-cu12`。

## Agent 工作流

典型流程：

1. 在 **Agent** 页输入 YouTube 链接或视频 ID。
2. 如果你知道视频是否有内嵌字幕，先选择“有/没有/不清楚”。
3. Agent 先检测标题、时长和字幕轨道，并直接显示路线选择，不等待整段视频下载。
4. Agent 给出推荐路线；选择后才下载工程视频，已有视频会直接复用，然后继续 OCR / ASR / 字幕路线。
5. 如果需要 OCR，直接抽帧并调整裁剪区域。
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

### OCR 版本怎么选

| 版本 | 流程 | 建议用途 |
| --- | --- | --- |
| OCR 1.0（旧版） | 自动主字幕 OCR → 旧文本清理 → 旧翻译流程 | 复现历史结果或兼容旧任务 |
| OCR 2.0（稳定版） | 区域 OCR → 专属框/轨迹去噪 → 锁定原时间轴翻译 | 常规的底部硬字幕，默认优先选择 |
| OCR 3.0（初版） | 区域 OCR → 几何提示 → 文字纠错 → 画面字/对白分层 → 锁定时间轴翻译 | 同时存在斜字、画面配字和对白字幕时实验 |

Agent 页的抽帧预览可以拖动、缩放字幕区域，并可选一个 Logo/固定字排除框。OCR Lab 会把 2.0 和 3.0 放在独立调试目录；已有 `tracks.json`、`ocr_boxes.json` 时可以只重跑对应精修阶段，不必重新解码视频或重新跑 PaddleOCR。OCR 3.0 仍是实验版本，建议保留 2.0 结果用于对比。

### 字幕精修怎么用

1. 从素材库选择字幕并进入 **字幕精修**；页面会尽量自动找到同项目视频，也可以手工填写视频路径。
2. 直接修改文字和开始/结束时间，或用 `±0.1s`、当前播放时间、接上/下条微调。
3. 点击“播放本条”，播放器会从该条开始时间播放，到结束时间自动暂停，并在画面底部显示正在编辑的外挂字幕。
4. 误改时使用顶部“撤回上一步”；文字、时间、新增、删除、合并和批量清理都进入最多 50 步的历史。
5. 选择覆盖原文件或另存为 `edited.srt`。保存后仍可撤回，但撤回出的版本会重新标为“未保存”，需要再次保存才会落盘。

## 常用命令

Web UI 不需要额外的流水线配置。只有使用高级 YAML CLI 时，才复制并修改专用示例：

```bash
cp examples/cli/run.yaml configs/run.yaml
```

新的公开命令是 `reibosub`。旧命令 `video-translate`、内部 Python
模块名 `video_translate` 以及 `VIDEO_TRANSLATE_*` 配置键继续保留，避免已有脚本和本机配置失效。

如果当前环境在改名前安装过本项目，执行一次下面的命令刷新 editable 包元数据：

```bash
python -m pip uninstall -y video-translate
python -m pip install --no-deps -e .
```

检查依赖和缓存路径：

```bash
reibosub doctor
```

读取 `configs/run.yaml` 运行：

```bash
python run_from_config.py
# 或
reibosub run-config configs/run.yaml
```

从本地视频 OCR 提取字幕：

```bash
reibosub extract "input.mp4" --lang korean --out "outputs/demo"
```

开启全屏辅助 OCR：

```bash
reibosub extract "input.mp4" --lang korean --out "outputs/demo" --scan-full-frame
```

翻译已有 SRT：

```bash
reibosub translate-volcengine "outputs/demo/source.srt" \
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

- `configs/provider_secrets.yaml`
- `configs/provider_profiles.yaml`
- `configs/providers/*.yml`、`*.yaml`（旧版兼容配置）
- `configs/reibosub.yaml`
- `configs/app_settings.yaml`
- `.env*`
- 旧版/高级本机文件：`configs/local_runtime.yaml`、`configs/run.yaml`、`configs/llm.yaml`
- `YoutubeDownloads/`
- `outputs/`
- `models/`
- 生成的视频/字幕文件，例如 `*.mp4`、`*.srt`、`*.vtt`、`*.ass`、`*.bcc`
- 日志、Cookie、私钥、证书和服务账号 JSON

可复用 glossary 示例放在 `configs/glossaries/examples/`。每个任务生成的 glossary 草稿建议放在 `outputs/agent_tasks/<task-id>/` 或其他被忽略的工作目录。

发布分支前至少运行：

```bash
git status --short --ignored
git diff --check
git diff --cached --name-only
```

本仓库不包含用户视频、字幕、模型缓存或真实凭据。请只处理和分享你有权使用的素材，并遵守来源平台与模型服务商的条款。更完整的部署和泄漏处理建议见 [SECURITY.md](SECURITY.md)。

## 常见问题

- **页面提示前端未构建**：运行 `cd frontend && npm ci && npm run build`，然后刷新页面。
- **不知道 Conda 环境装到哪里**：运行 `conda info --envs` 和 `conda config --show envs_dirs`；也可以用 `conda env create -p /path/to/envs/reibosub -f environment.yml` 显式指定位置。
- **提示安装的是 CPU 版 Paddle，无法用 GPU**：把 OCR 设备改为 `cpu`/`auto`，或先卸载 `paddlepaddle`，再按 CUDA 版本安装匹配的 `paddlepaddle-gpu`；不要同时保留 CPU/GPU 两个包。
- **服务商获取不到模型**：很多兼容接口没有 `/models`；在设置页维护静态模型 ID，仍然可以正常发起任务。
- **YouTube 无法连接**：在 `configs/reibosub.yaml` 设置 `youtube_proxy`；它只作用于下载，不会代理 OCR/ASR。
- **OCR 明明有字却漏识别**：先核对语言、绿色字幕裁框、Logo 排除框和 OCR 版本；首次运行还要等待模型下载。2.0 与 3.0 应在各自目录比较。
- **出现 `h264 mmco: unref short failure`**：通常是解码警告；只要 OCR 进度仍增长，不代表任务崩溃。
- **重启后正在运行的步骤不再继续**：活动 job、运行日志和执行进程在内存中；Agent 任务记录与已有产物仍会保留，可从任务记录、素材库或 OCR Lab 继续并重跑对应阶段。

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

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源许可证。
