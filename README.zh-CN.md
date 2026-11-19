# ReiboSub 中文说明

[English README](README.md)

ReiboSub 是一个面向 YouTube、Bilibili 普通投稿和本地视频的字幕制作 Agent。它可以下载视频、字幕和封面；用 OCR 提取内嵌硬字幕；用 ASR 从音频识别字幕；生成并审核 glossary；调用 OpenAI-compatible 大模型翻译字幕；精修和转换字幕格式；并把可播放的外挂字幕复制到视频同目录。

这个项目的核心思路是“人机协作”：Agent 可以同时推进多个视频流程，遇到需要你判断的地方会暂停，等你审核 glossary 或确认路线后继续。

[安装与启动](#快速开始) · [B站与多语言](#b-站与多语言) · [素材库与术语审核](#素材库与术语审核) · [模型配置](#大模型配置) · [GPU 与实验版要求](#gpu-和模型缓存) · [常见问题](#常见问题)

## 主要功能

- **Agent 工作台**：输入 YouTube / B 站普通视频链接或视频 ID，自动检测字幕源、推荐路线、等待人工确认。
- **素材与字幕关联**：每个视频或 B 站分 P 有独立素材目录；素材库同时展示该项目关联的任务原文、目标语言译文和历史版本，字幕不必复制到视频旁。
- **平台字幕下载**：区分人工和自动字幕，可选择语言下载；B 站弹幕不作为字幕。
- **OCR 硬字幕提取**：Agent 默认使用 OCR 3.0 稳定流程，同时保留相互隔离的 OCR 1.0、2.0 兼容路线。
- **ASR 音频字幕**：使用 `faster-whisper` 从音频生成源字幕，可选 LLM 原文纠错。
- **视频上传流程**：在浏览器里上传本地视频后，直接启动 ASR 中文字幕任务。
- **Hybrid 路线**：可用作者上传字幕的时间轴定轴，同时用 OCR 还原原声语言文本。
- **Glossary 审核**：自动生成术语草稿，UI 中审核人名、昵称、作品名、专有词；支持罗马音、证据原句和原句参考译文。可在术语卡片内播放关联视频/音频的证据片段，切换多处证据、慢速/重复播放，并查看前后文；默认前后各 3 秒，可扩大到各 10 秒，播放不会确认或改写译名。
- **随手翻译器**：术语审核页内置中、英、日、韩互译，可自动识别原文语言、交换方向、带入术语原句和复制译文；结果只供参考，不自动确认术语。
- **字幕精修**：逐条改字和时间轴、50 步撤回、按单条区间播放并在画面叠加字幕，也支持新增、合并、删除和批量清理。
- **字幕格式转换**：支持 SRT、VTT、ASS/SSA、LRC、TXT、JSON、Bilibili BCC 等格式。
- **视频贴图处理**：上传图片作为水印或遮挡 Logo，调位置和大小后输出新视频。
- **模型服务设置**：在网页中管理服务商，搜索选择一个通用模型；视觉模型可单独指定，逐模块覆盖收在高级设置里。

Agent 路线的设计说明见：[docs/youtube_agent_workflows.md](docs/youtube_agent_workflows.md)。其中包含设计背景和后续构想，不保证每一项都已实现。

### 独立自主 Agent 实验

在字幕助手选择“自主 Agent · 实验”，输入 YouTube 或 B 站普通视频链接即可，不需要手工选择测试区间。新任务使用目标驱动控制器：模型根据已返回的工具证据逐次选择行动、修订短计划，并决定何时交付；不是把所有工具按固定阶段运行一遍。“经典工作流”和已经保存的旧版实验任务保留原有执行协议。

可用能力包括字幕检测和下载、现成目标语言字幕检查、指定字幕上下文读取、自选时间点抽帧/视觉分析、OCR 试跑、整片 ASR 和 4–30 秒局部音频核查、不同来源对照、局部修订与译文检查。画面分析需要在设置中绑定支持图片的模型；音频和 OCR 工具仍需相应本地依赖。模型只能选择当前有权限、有输入且未超预算的工具，不能执行任意命令、指定任意文件或自行换服务商。

新建的自主任务以视频内嵌字幕为优先原文：先查看至少 4 个跨越视频 60% 时长的抽样画面；只要发现内嵌对白或配字，就以 OCR 3.0 提取的画面文字为底本，外挂字幕和局部语音识别仅作辅助。抽查尚未完成时不能直接转整片 ASR。多处抽查仍未见内嵌字幕，才允许采用外挂或 ASR 底本；抽查结论不代表整片视觉真值。OCR 框选保留左右全宽、下缘及较宽的上方余量，避免按少数单行样本裁掉后续双行字幕。历史实验和明确限定输入的续测不自动迁移。

该实验路线先独立保存原始 OCR，再有限分组审核比赛 HUD、固定选手 ID 和物品文字等候选噪声。原语言文字及相邻姓名/数字片段受保护，不确定组保留为证据；不会把“纯英文/数字”直接等同于噪声。机器稿按帧优先保留原语言对白，避免下方未确认的选手 ID 压掉字幕。原始轨迹、隔离记录和成品分别保存。成品复用既有 V3 精修器，在独立子进程中限制请求数、超时及输出，并关闭 Doubao 2.1 的思考模式；OCR Lab 的稳定流程和默认请求方式不改变。

网页显示简短证据摘要、当前行动、核对目标和可调整计划，不展示模型内部思维过程。原文候选和模型多数意见不等于音频真值；结构检查和语义抽查也不代表整片人工核准。遇到真实疑点可以局部取证，证据仍不足才询问用户。需要正式翻译时，Glossary 人工审核不能跳过；可用的现成目标语言字幕可在检查后原样另存交付，不强制生成词表或重译，仍须满足画面核查要求。

正常新任务同时交付本地视频与所选目标语言字幕。Agent 可以先检查字幕、确定方案，再安排视频下载；已有对应视频直接复用。缺少视频时不会把任务标为完成，即便已有可用译文。网页显示视频保存状态并提供视频下载入口。明确限定为验收、局部复核或复用原文的历史续测，不会因此擅自扩大为重新下载整片。

新控制器使用独立字幕产物，不覆盖旧结果。当前整片下载/重识别工具限 1 小时素材，每轮最多 24 次决策，并有单工具预算；尚不支持无上限自主运行。工具连续失败会保留现场并明确报错，不伪装成需要用户“确认通过”的字幕问题。

验收会定位具体空译文、条数或时间不匹配，而非笼统要求重新识别。仅对提案与独立复核共同批准、且被相邻原句及重叠时间覆盖的韩语重复词尾空条，允许在交付副本中合并；原稿和原编号到发布编号的映射保留。其他空条仍需修复，不默认放行，也不填占位词凑数。

> [!IMPORTANT]
> 这是一个可信用户使用的本地工具，Web UI 没有账号或登录鉴权。默认只监听 `127.0.0.1`，不要把服务直接暴露到公网。远程服务器推荐使用 SSH 端口转发，详见 [SECURITY.md](SECURITY.md)。

## 快速开始

### 先了解安装边界

这是源码项目，不是下载后双击即用的安装包。仓库不包含 `frontend/dist`、模型权重、API Key、用户视频和本机配置。完成安装后可以先打开网页；识别模型会在首次使用时下载，翻译与 Agent 判断需要你自己的模型服务。

推荐先在 **Linux x86_64 或 WSL2 + Python 3.11** 上跑通网页、翻译与 CPU OCR，再配置 GPU。Python 元数据允许 3.10+，但 OCR/ASR 能否安装还取决于对应平台的第三方 wheel；不要直接照搬服务器的 CUDA 环境。

| 使用方式 | 额外需要什么 |
| --- | --- |
| 下载视频、字幕转换、字幕精修 | FFmpeg/ffprobe；YouTube 还需 Node.js 22.12+ 和可访问的网络 |
| 翻译现有字幕、生成术语 | 你自己的 OpenAI-compatible 模型服务与额度 |
| OCR 1.0 / 2.0 / 3.0 | PaddlePaddle CPU 或 GPU 引擎、识别模型；LLM 精修另需模型服务 |
| 网页 ASR 2.2 | faster-whisper、Whisper 权重和 NVIDIA CUDA 运行环境；当前网页按 CUDA/float16 提交，CPU 识别可用下文的 CLI |
| 自主 Agent 的画面分析 | 支持图片输入的模型；可以与通用模型相同 |

标准安装使用文件保存任务与字幕，不需要配置数据库，也不需要复制维护者的 `.env`。Qwen/多模型 ASR 实验不是标准依赖安装后即用的能力，见下文实验版说明。

### 1. 克隆并安装（推荐 CPU 入门）

先安装 Git 和 Conda/Miniforge。在准备存放项目的位置执行。若 GitHub 提示认证或返回 404，需先确认仓库访问权限；已授权的 SSH 用户也可用 `git clone git@github.com:YuqiPlus/ReiboSub.git`，安装命令不会改变仓库可见性。

```bash
git clone https://github.com/YuqiPlus/ReiboSub.git
cd ReiboSub
conda create -n reibosub --override-channels -c conda-forge python=3.11 pip ffmpeg "nodejs>=22.12" -y
conda activate reibosub
python -m pip install -r requirements.txt
```

请保留 `--override-channels -c conda-forge`：该命令只使用 conda-forge，不追加全局配置中的软件源，无需改全局 `.condarc` 或为本项目接受 Anaconda 默认源条款。这里限制的是 **Conda 软件源**；Python 依赖仍由 pip 从 PyPI 安装，GPU Paddle 按下文从官方索引安装。

仓库仍提供含 `conda-forge` / `nodefaults` 的 `environment.yml`，供使用环境文件的用户选择。`nodefaults` 会阻止求解器追加默认源，但部分 Anaconda 条款插件会在读取清单前检查全局源；若遇到这种情况，请使用上面的显式创建命令。项目不会自动接受条款或修改全局配置。格式行为见 [Conda 官方环境格式说明](https://conda.org/learn/specifications/exchange/environment-yml/)。

这一条路线安装 Python 3.11、FFmpeg/ffprobe、Node.js 22.12+，以及 CPU OCR 和 faster-whisper。首次安装和首次下载模型需要联网；CPU 处理长视频可能很慢。**要直接配置 GPU OCR 的用户请跳到 [GPU 和模型缓存](#gpu-和模型缓存)，不要先安装 CPU Paddle。**

已有合适的 Python 环境时，可跳过创建环境，直接按以下方式安装；FFmpeg/ffprobe、Node.js 22.12+ 仍需自行安装并加入 `PATH`：

```bash
python -m pip install -U pip
python -m pip install -r requirements.txt
```

只处理现有字幕或下载视频、不运行识别时，可安装 `python -m pip install -e .`；它不安装 PaddlePaddle 推理引擎和 faster-whisper。需要时再安装 `.[ocr-cpu]` 或 `.[asr]`。测试依赖是可选的 `.[dev]`，普通使用无需安装。

`yt-dlp[default]` 会一并安装 YouTube JS 解题组件；项目会启用 `PATH` 中的 Node.js。只有 Node、没有解题组件，或使用过旧的 Node，都可能出现“能打开视频但下载失败”。要求依据见 [yt-dlp EJS 官方说明](https://github.com/yt-dlp/yt-dlp/wiki/EJS)。

### 2. 检查是不是用了同一个环境

```bash
python -c "import sys, shutil; print(sys.executable); print('ffmpeg:', shutil.which('ffmpeg')); print('ffprobe:', shutil.which('ffprobe')); print('node:', shutil.which('node'))"
ffmpeg -version
ffprobe -version
node --version
python -m pip check
```

前三个工具路径不应是 `None`，Node 应为 22.12 或更新版本。必须在激活后的同一终端启动服务；只写某个环境的 Python 完整路径，并不会自动把它的 `bin` 目录加入 `PATH`。`reibosub doctor` 可以补查部分 Python 包和缓存位置，但不检查全部外部工具、CUDA、模型下载和 API 可用性。

### 3. 构建网页

```bash
cd frontend
npm ci --include=dev
npm run build
cd ..
```

这一步不能省略。服务读取的是构建后的 `frontend/dist`，不是直接打开 `frontend/src`；Git 更新前端后也需要重新构建。

前端要求 Node.js **至少 22.12**；建议使用受支持 LTS 分支的最新补丁，不要固定在旧的 22.12 发行包。Vite 和 Vue 构建插件属于开发依赖，但构建网页时必须安装，因此命令显式带 `--include=dev`。网页构建完由 Python 提供静态文件，正式服务不需要运行 Vite；从 `npm ci --omit=dev` 得到的安装不能用来构建。

### 4. 本机配置（可选）

可选：复制唯一的本机启动配置。默认值已经可以直接启动；需要修改素材目录、平台代理、B 站 Cookie、监听地址或端口时才需要这个文件。

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

### 5. 启动网页

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

### 6. 在网页中配置模型服务

首次打开网页后：

1. 进入 **设置 → 服务商管理 → 新增服务商**。空白安装没有默认可用的密钥。
2. 填写稳定的 Provider ID、显示名称、OpenAI-compatible API Base URL 和 API Key。
3. 点击“创建并获取模型”；如果服务不支持 `/models`，直接填写静态模型名称即可。
4. 返回 **常用设置**，选择默认服务商和通用模型，点击 **保存设置**。翻译、术语、OCR 整理与 Agent 判断可以共用一个模型，不必逐项配置。
5. 画面分析需要支持图片输入。通用模型支持图片时，视觉模型选择跟随；否则单独选择视觉服务商和模型。模型支持搜索；无候选列表时可手填 ID。

获取模型列表只说明服务返回了模型名称，不代表该账号有调用额度，也不保证模型支持图片。新手无需展开逐模块高级设置。旧安装想统一文本模块，可点击“统一文本模块到通用模型”，确认保留视觉配置后保存。

网页会把服务商信息保存在 Git 忽略的 `configs/provider_profiles.yaml`，把连接地址和 API Key 保存在同样被忽略的 `configs/provider_secrets.yaml`。Key 是只写字段，不会从后端回显；新安装无需复制或手工维护 `configs/providers/` 下的文件。

### 7. 第一次建议先跑短素材

1. 先用 **下载与链接** 下载一段你有权处理的视频，或在 **素材库 → 导入素材** 上传本地视频。只下载不需要启动 Agent，也不需要 LLM。
2. 在 **OCR Lab** 选择 3.0 测试有内嵌字幕的短片；已配置 NVIDIA CUDA 的机器可在 **ASR Lab** 选择 2.2 测试纯人声素材。CPU 用户先使用下文的语音识别 CLI，不要把 CPU 安装等同于网页 ASR 已就绪。首次识别会下载模型，不能据此误判卡死。
3. 验证识别和模型服务后，再到 **字幕助手** 输入 YouTube 或 B 站普通视频链接，检查音源和目标语言。正式翻译前会停在术语审核：填写或确认人名和专名，再保存继续。
4. 完成页下载 SRT，或在 **素材库** 精修字幕。**所有任务** 显示阶段、产物和重跑入口；删除任务会删除任务目录中的产物，但保留已下载视频，删除前请先下载要保留的字幕。

自动检查不是人工逐字核准。先测试短片，再跑长片，避免在模型、网络或设备没有配好时反复消耗时间和 API 额度。

## B 站与多语言

### 支持的链接与分 P

**下载与链接**、**字幕助手**都接受 YouTube 链接/视频 ID，以及 B 站普通投稿的 BV/av 号、完整视频链接和 `b23.tv` 短链接。下面的 `BVxxxxxxxxxx` 是占位符，请换成你有权处理的真实 BV 号：

```text
BVxxxxxxxxxx
https://www.bilibili.com/video/BVxxxxxxxxxx
https://www.bilibili.com/video/BVxxxxxxxxxx?p=2
```

每次只处理一个分 P；未带 `p` 时为 P1，`?p=2` 为 P2。不同分 P 有独立任务标识和素材目录，不会凭相似标题复用另一 P 的 OCR。想处理多 P，请逐 P 新建任务。当前不支持番剧、直播、整合集或自动下载全部分 P；弹幕不是 CC 字幕，不会作为对白底本。短链接解析失败时，改用浏览器地址栏里的完整 BV 链接。

### 只下载视频，不翻译

1. 打开 **下载与链接**，粘贴链接。页面会自动读取这个视频可下载的画质；也可以点击 **刷新画质**。
2. 选实际可用格式，或保留“兼容下载 · 最高 1080p · H.264 / MP4 优先”，点击 **下载视频**。无需先检测字幕，也不需要模型 Key。
3. 如需 CC 字幕，另点 **查看字幕与视频信息**，选择语言和人工/自动轨道再下载；没有轨道不代表画面没有内嵌字幕。
4. 到 **素材库** 找到视频，可预览或用于后续处理。下载封面在 **封面与下载说明** 中。

最高画质以当前账号和视频实际可用列表为准。MP4 是容器，H.264、HEVC、AV1 是编码，不是同一个概念；追求浏览器/OCR 兼容性时先选兼容模式，不要把“最高画质”理解为“保证 H.264”。

### 从链接生成目标语言字幕

1. 点击侧栏 **新建字幕任务**，粘贴完整链接；多 P 视频要保留对应的 `?p=N`。
2. 检查输入区的 **音源语言**、**译成** 和 **处理模式**。选“自主 Agent · 实验”会按证据调用工具，不需要填写测试区间。
3. 点击 **开始制作字幕**。Agent 保存本地视频，抽帧核查画面；有内嵌对白或配字时优先 OCR 3.0，无内嵌的证据充分后才使用可靠外挂或 ASR。模型服务及本地识别依赖需已按快速开始配置。
4. 需要翻译时会进入 **术语审核**：确认人名、作品名和固定译法，全部确认后点击 **全部已确认，保存并开始翻译**。无需再回 Agent 点第二次确认。现成目标字幕经检查可直接交付的分支不强制重译或生成术语表。
5. 完成后下载原文和目标语言 SRT，或在 **素材库** 打开字幕精修。**所有任务** 可查看产物与重跑入口；不要仅因暂时看不到译文就新建整片重翻。

新建任务的默认方向：

| 来源 | 默认音源语言 | 默认目标语言 |
| --- | --- | --- |
| B 站 | 中文 | 英语 |
| YouTube | 设置中保存的原文语言（初始为韩语） | 中文 |

两侧都能手动修改，目标支持中文、英语、日语、韩语。手动选择在当前草稿内优先，即使换了链接也不会自动清空；点击 **新建字幕任务** 恢复平台默认。已保存任务继续使用原来的语言，不受新设置影响。B 站视频也不一定说中文，请按实际内容改音源语言。

### 翻译已有字幕与输出语言

从 **字幕工具 → 翻译与转换** 选择或填写字幕路径，设置 **原文语言** 和 **译成**；需要固定译名时先从字幕生成术语表并审核，再翻译。这个手动入口与 Agent 的强制人工术语审核不同，术语表是可选的；格式转换本身不调用翻译模型。

术语表的译名、原句参考译文和最终验收跟随该任务的目标语言，不要求外语译文包含汉字。换目标语言时请生成并审核对应的新术语表，不要直接复用另一个目标语言的表。没有 `target_language` 的旧表仍按中文解释；YAML/JSON 的 `zh`、`suggested_zh` 是兼容字段名，外语任务里存的是对应外语译名。

目标语言代码分别是 `zh`（中文）、`en`（英语）、`ja`（日语）、`ko`（韩语）。常规产物可叫 `en.srt` / `<标题>.en.srt`；自主 Agent 另存结果可能叫 `en.review_<标记>.srt`，原文可能叫 `source.review_<标记>.srt`，不是丢失或命名错误。请以任务的下载按钮和素材库文件路径为准，不要只找 `zh.srt`。

### B 站登录、代理与权限

B 站默认直连，不使用 `youtube_proxy`。部分画质、CC 字幕和视频需要登录或相应账号权限。如有需要，在你自己的 `configs/reibosub.yaml` 中增加可选字段，再重启服务：

```yaml
bilibili_proxy: ""  # 仅在 B 站确需代理时填写，不影响 YouTube 设置
bilibili_cookie_file: /private/path/bilibili.cookies.txt
```

把示例 Cookie 路径替换为服务器上真实、可读的文件路径；文件须是你自己导出的 Netscape 格式 Cookie，并存放在仓库外。Cookie 等同于敏感登录信息，不要分享、截图或提交到 Git。该功能不绕过会员、付费或地区限制。旧的 `video_translate.youtube.*` 命令名称继续兼容 B 站普通视频和指定分 P。

## 素材库与术语审核

### 在素材库找到字幕和历史版本

1. 打开 **素材库**，按标题或文件名搜索；也可以按视频、音频、字幕筛选。
2. 在素材卡片点 **文件与更多**。详情的 **字幕** 区会列出原文、目标语言译文及可用的历史版本；任务结果带有“第 N 轮”，归档结果另标“历史版本”。
3. 用 **下载** 保存文件，或点对应条目的 **精修字幕**。同项目的视频会一并带入编辑器；卡片上的快捷精修优先选择当前轮译文，不会因为归档文件刚复制过就选中旧稿。
4. 新结果尚未出现时点击素材库 **刷新**。已完成 OCR/ASR 的原文可以先出现，译文须等翻译阶段完成；运行中或失败的翻译草稿不会被当作最终译文发布。

这是按任务中记录的确切项目/视频路径做关联，不是按标题猜测，也不会复制或覆盖字幕。视频仍在素材目录，独立字幕仍在 `outputs/agent_tasks/<task-id>/` 或该任务的归档目录；这也适用于已记录了正确素材路径、文件仍存在的历史任务。没有绑定信息的独立产物可能仍需从任务历史或独立处理结果打开。

**素材库能显示字幕，不代表播放器已自动加载。** 自主 Agent 通常保留独立文件，不一定生成视频旁的字幕副本。请在播放器里手动加载下载的 SRT，或将字幕放到视频旁并按播放器要求命名。备份项目时不要只复制视频目录，还要保留需要的任务字幕；删除任务会移除其任务目录和其中的独立字幕，操作前先下载或备份。

### 审核术语并核对原声

Agent 进入人工审核时会自动打开术语表；手动操作也可从 **字幕工具 → 术语审核 → 术语文件与高级编辑** 加载已有表。根据本次目标语言填写译名，逐条 **确认**；修改自动保存。**播放证据片段** 可听原声、看画面和前后文，也能切换多处证据、降低语速或重复播放。识别文字、罗马音和参考译文都是线索，不是官方译名认证。

自主翻译任务需要确认所有待办后点击 **全部已确认，保存并开始翻译**，Agent 才会继续。手动打开的术语表使用 **保存审核结果**；两种入口的用途不同，不要把“播放片段”或“复制参考译文”当作确认操作。

### 使用术语页的随手翻译器

1. 打开 **术语审核** 页上方的 **随手翻译**。无需先加载术语表，收起后可点 **展开**。
2. 左侧选原文语言，或保留 **自动识别**；右侧选中文、英语、日语或韩语。右侧初始跟随当前术语表目标语言，之后可以独立更改，不会修改任务的翻译方向。
3. 输入最多 4000 个字符，点击 **翻译**；输入框也支持 `Ctrl+Enter` / `⌘+Enter`。可在术语卡片点击 **放入翻译器**，带入证据原句并将左侧切回自动识别。
4. 明确选择左侧语种后可点 **⇄** 交换方向；有当前有效译文时会将它带到左侧，交换后需重新点击翻译。左侧为自动识别或正在请求时不能交换。
5. 用 **复制译文** 或手动选择文字复制。改动输入/语种后旧译文会标为待重译；过时的回复不会覆盖新输入，需再次点翻译。

翻译器复用 **设置** 中的字幕翻译模型（未单独覆盖时跟随通用模型），无需新增服务商或 Key。输入会发给该模型服务并消耗对应额度。它只处理这段文字，不重翻整片，不自动填入、保存或确认术语；需要采用时由你复制到译名输入框并确认。离开页面前请自行复制要保留的结果。提示服务不可用时检查模型配置、权限和额度；复制受浏览器限制时可手动选取文字。

## 前端开发

Python 服务会读取 `frontend/dist`。生产式本地运行使用 `npm ci --include=dev && npm run build`。开发时可以分别启动 Python 后端和 Vite：

```bash
# 终端 1
python run_agent_ui.py

# 终端 2
cd frontend
npm ci --include=dev
npm run dev
```

开发服务器默认是 `http://127.0.0.1:5173`，并把 `/api` 转发到 `7860`。提交前仍需运行 `npm run build`。

构建成功不代表依赖没有安全告警。在 `frontend` 中运行 `npm run audit:deps`，检查包含开发依赖的完整锁定依赖树；运行 `npm test` 做前端测试。本次使用仍受维护的 Vite 7.3 补丁线和 Vue 3.5 修复版，Node 要求与 [Vite 7 官方迁移说明](https://v7.vite.dev/guide/migration#node-js-support) 对齐。后续安全公告会变化，更新时应重新审计、测试和构建，而不是使用 `--omit=dev` 隐藏构建依赖告警。不要把 Vite 开发服务器暴露到公网，也不要未经测试直接用 `npm audit fix --force` 跨大版本升级。

## 大模型配置

项目使用 OpenAI-compatible Chat Completions API。Web UI 的“设置”页现在可以保存新任务的默认语言、默认服务配置，以及各 LLM 模块使用的模型。

服务商统一在设置页创建和管理。填写 API Base URL 与 Key 后拉取模型，日常只需选择一个通用模型；视觉模型必须支持图片输入。旧的逐模块配置保留在高级设置中，不会静默清空。点击“统一文本模块到通用模型”会将 8 个文本模块切换为继承，保留视觉配置，保存后生效。共用模型不等于合并处理步骤，每步仍独立调用和校验。如果服务不支持 `/models`，可手填 ID 或维护静态列表。

API Key 和 API 地址直接在设置页管理，不需要 `.env`。服务商名称、模型列表和默认模型保存在 `configs/provider_profiles.yaml`；连接地址和密钥保存在 `configs/provider_secrets.yaml`。两者均被 Git 忽略，其中密钥文件权限会强制设为 `0600`。密钥输入是只写的：后端只返回是否已配置和配置来源，绝不会把现有密钥或尾号回显到浏览器。

远程网页允许录入或替换 Key；服务域名跨站变更需要从服务器本机或 SSH 端口转发访问，模型列表 URL 也必须与 API Base URL 同源。由于密钥通过网页提交时仍会经过网络，远程使用请通过 HTTPS 或 SSH 隧道，不要在不可信的明文 HTTP 网络中录入。

设置页也可以新增、编辑和删除本地 OpenAI-compatible 服务商。普通用户不需要手工编辑上述文件。Provider ID 会被已有绑定引用，因此保持不可直接修改；删除服务商时，受影响的绑定会迁移到所选替代服务，并重置为它的默认模型。

旧部署使用的 `.env`、`configs/llm.yaml` 和 `configs/providers/*.yml` 仍然兼容读取，但不再作为新安装的配置方式。

## GPU 和模型缓存

识别模型不随 Git 下载。项目会配置 `models/` 等本地缓存路径，部分上游组件也可能使用自己的缓存；首次识别需要能访问对应模型源并预留磁盘空间。通用 LLM 通常通过 API 调用，不会自动下载为本地模型。

GPU 安装与 CPU 入门路线二选一。新机器先克隆仓库，在仓库根目录创建不含 CPU Paddle 的环境：

```bash
conda create -n reibosub --override-channels -c conda-forge python=3.11 pip ffmpeg "nodejs>=22.12" -y
conda activate reibosub
```

下面只是 **Linux NVIDIA / CUDA 12.6** 的安装示例，不是适用于所有显卡和驱动的命令。先核对驱动及 Paddle 官方兼容要求，再选择对应安装源；[PaddleOCR 安装说明](https://www.paddleocr.ai/main/en/quick_start.html)也明确区分了推理引擎和 OCR 包。

```bash
python -m pip uninstall -y paddlepaddle paddlepaddle-gpu
python -m pip install -r requirements-gpu-cu126.txt
python -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
# 可选：开发和测试环境再执行
python -m pip install -e ".[dev]"
```

GPU requirements 文件会安装项目通用依赖、`faster-whisper` 和常用 CUDA Python wheels，但不会安装 CPU Paddle；Paddle GPU 本体由下一条 CUDA 专用源命令安装。

完成后回到上面的第 2–6 步，检查工具、构建前端并配置服务。不要再执行 CPU 的 `requirements.txt` 或 `environment.yml` 安装路线，否则可能把 CPU Paddle 装回来。

检查 Paddle 是否能看到 CUDA：

```bash
python -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

当 OCR 设备为 `auto` 时，ReiboSub 会自动选择可用设备；各 OCR 路线仍可以显式选择 CPU 或具体 GPU。旧本机运行配置里的高级设备覆盖仍然兼容。

ASR 使用 `faster-whisper` 时，项目会尝试自动加入 `nvidia-*` Python 包里的 CUDA 库路径。如果仍报 `libcublas.so.12` 或 cuDNN 找不到，请检查环境中的 `nvidia-cublas-cu12` 和 `nvidia-cudnn-cu12`。

当前网页 ASR 入口按 CUDA/float16 启动，安装了 CPU Paddle 并不意味着 ASR 也能用 CPU。无 NVIDIA GPU 时可先用基础识别 CLI：

```bash
python -m video_translate.tools.transcribe_audio "input.mp4" \
  --out "outputs/demo/source.srt" --language ko \
  --model-size small --device cpu --compute-type int8
```

这条命令是基础 faster-whisper 转录，不等同于自动跑完整 ASR Lab 2.2 的补漏、复核和翻译。CUDA/cuDNN 的上游要求请同时核对 [faster-whisper 官方安装说明](https://github.com/SYSTRAN/faster-whisper#requirements)。

### ASR 实验版不是标准安装的一部分

ASR 2.2 是常规路线。ASR Lab 的 Qwen 多模型复核和自主实验版另需独立 Qwen Python 环境、`models/asr3/Qwen3-ASR-1.7B` 与 `models/asr3/Qwen3-ForcedAligner-0.6B` 权重，以及两张 NVIDIA GPU；当前实验入口还仅接受韩语。可用 `REIBOSUB_QWEN_PYTHON` 指定该环境的 Python。标准 requirements 不会自动建立它，也不会下载这些实验权重；未准备这些资源时，请不要选择实验版。

### 更新代码后

先等任务完成并停止服务，再在原环境中更新：

```bash
conda activate reibosub
git pull --ff-only
python -m pip install -e .
cd frontend
npm ci --include=dev
npm run build
cd ..
python run_agent_ui.py
```

`pip install -e .` 更新基础依赖，不会主动安装 CPU Paddle 覆盖已有 GPU 安装。忽略的本地配置与素材通常不受 Git 更新影响，仍建议先备份。没有自动更新和常驻进程管理器；远程长期运行应自行配置进程管理，并始终从正确的环境启动。

## Agent 工作流

默认的“自主 Agent · 实验”只需输入链接，由模型选工具；常规 ASR、OCR、视觉 API 的依赖仍需按上文准备。Glossary 始终由人审核后才正式翻译。若希望手动决定路线，切换到“经典工作流”，其典型流程是：

1. 在 **字幕助手** 输入 YouTube / B 站普通视频链接或视频 ID，检查音源与目标语言。
2. 如果你知道视频是否有内嵌字幕，先选择“有/没有/不清楚”。
3. Agent 先检测标题、时长和字幕轨道，并直接显示路线选择，不等待整段视频下载。
4. Agent 给出推荐路线；选择后才下载工程视频，已有视频会直接复用，然后继续 OCR / ASR / 字幕路线。
5. 如果需要 OCR，直接抽帧并调整裁剪区域。
6. 生成 glossary 草稿，进入审核页确认术语。
7. 保存 glossary 后，Agent 会继续当前视频流程并翻译。
8. 根据需要进入字幕精修或格式转换。

Agent 支持多个视频流程并行。运行中的 session 会独立轮询；某个流程等待确认或 glossary 审核时，点击它的卡片处理即可，不会阻塞其他流程。

常见路线：

- **已有目标语言字幕**：检查后可直接采用，可转换格式或整理命名。
- **有原声语言作者字幕**：锁定作者字幕时间轴，用 glossary 引导翻译。
- **只有自动字幕**：可先原文纠错，再生成 glossary 和翻译。
- **视频内嵌硬字幕**：用 OCR 提取源文，再 glossary 和翻译。
- **只有人声**：用 ASR 识别源文，可纠错后翻译。
- **英文定轴 + 原声 OCR**：用作者上传英文字幕的时间轴做锚点，同时 OCR 还原原声语言内容。

### OCR 版本怎么选

| 版本 | 流程 | 建议用途 |
| --- | --- | --- |
| OCR 1.0（旧版） | 自动主字幕 OCR → 旧文本清理 → 旧翻译流程 | 复现历史结果或兼容旧任务 |
| OCR 2.0（保留版） | 区域 OCR → 专属框/轨迹去噪 → 锁定原时间轴翻译 | 复现既有 2.0 结果或作为对照 |
| OCR 3.0（稳定版，默认） | 区域 OCR → 几何提示 → 文字纠错 → 画面字/对白分层 → 锁定时间轴翻译 | 新建 Agent 任务及包含斜字、画面配字和对白字幕的视频 |

Agent 页的抽帧预览可以拖动、缩放字幕区域，并可选一个 Logo/固定字排除框。OCR Lab 会把 2.0 和 3.0 放在独立调试目录；已有 `tracks.json`、`ocr_boxes.json` 时可以只重跑对应精修阶段，不必重新解码视频或重新跑 PaddleOCR。已有任务继续使用任务中记录的版本，不会因默认值变化而改线。

该默认值用于整片 OCR 和 ASR + OCR 参考路线。“英文定轴 + 原声 OCR”有自己的定轴融合实现，本次不会被静默切换成 OCR 3.0。

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

平台下载和字幕工具（命令中的示例链接/路径需换成自己的）：

```bash
python -m video_translate.youtube.download_subtitles "https://www.youtube.com/watch?v=..." --sub-langs ko,en
python -m video_translate.youtube.download_video "https://www.youtube.com/watch?v=..."
python -m video_translate.tools.generate_glossary "YoutubeDownloads/example.ko.srt" --out "outputs/example/glossary.draft.yaml"
python -m video_translate.tools.translate_subtitles "YoutubeDownloads/example.ko.srt" --glossary "outputs/example/glossary.draft.yaml"
python -m video_translate.tools.convert_subtitle "YoutubeDownloads/example.zh.srt" --format bcc
```

例如，已有 `source.zh.srt`，想按“中文 → 英语”生成术语表并翻译，使用与网页一致的模型设置：

```bash
python -m video_translate.tools.generate_glossary "source.zh.srt" \
  --source-language chinese --target-language english \
  --out "outputs/demo/glossary.en.yaml"
# 先在网页术语审核页加载这份 glossary，填写并保存译名，再执行：
python -m video_translate.tools.translate_subtitles "source.zh.srt" \
  --target-language english --glossary "outputs/demo/glossary.en.yaml" \
  --out "outputs/demo/en.srt"
```

下载 B 站 P2 的 CLI 示例：`python -m video_translate.youtube.download_video "https://www.bilibili.com/video/BVxxxxxxxxxx?p=2"`。`BVxxxxxxxxxx` 同样需要替换为真实 BV 号；命令名称中的 `youtube` 只是兼容旧脚本，不限制来源平台。

`scripts/` 目录下也保留了对应的薄封装脚本，方便手动运行。

## 输出目录

默认下载目录：

```text
YoutubeDownloads/<视频标题>/
```

视频目录中的常见文件（字幕副本只在相应流程启用复制时出现）：

```text
<视频标题>.mp4
<视频标题>.jpg
<视频标题>.source.srt
<视频标题>.zh.srt
<视频标题>.en.srt
project.yaml
```

B 站素材标题/目录会附带 `[BV号 Pn]`，用于区分分 P。素材目录可由本机 `media_dir` 设置更改；历史默认目录名称 `YoutubeDownloads` 也用于 B 站，不必因此改名。

Agent 任务状态和中间产物：

```text
outputs/agent_tasks/<task-id>/
outputs/agent_jobs/<job-id>/
```

自主 Agent 独立交付文件常在任务目录中，例如 `source.review_<标记>.srt` 与 `en.review_<标记>.srt`；旧轮次可在任务的 `runs/generation_*/` 下保留。素材库通过任务记录关联这些文件，不会为了显示它们而覆盖原视频旁的字幕。

常见流水线输出：

- `source.srt`：OCR/ASR/下载得到的源语言字幕。
- `zh.srt` / `en.srt` / `ja.srt` / `ko.srt`：对应目标语言的字幕；具体另存文件可能带审核标记。
- `tracks.json`：OCR 文本轨迹、框位置和元信息。
- `ignored_tracks.json`：被判断为固定水印/噪声的文本轨迹。
- `tracks_debug.csv`：方便表格查看的 OCR 调试信息。
- `*.bcc`：Bilibili 字幕 JSON。

如果该流程开启 sidecar 复制，生成的字幕才会被复制到视频同目录，方便播放器加载；自主 Agent 的独立结果并不保证有此副本。查看或下载最终文件请以任务结果和素材库关联为准。

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

- **页面提示前端未构建**：运行 `cd frontend && npm ci --include=dev && npm run build`，然后刷新页面。
- **`ffmpeg` 已安装但服务说找不到**：先激活项目环境，检查 `python`、`ffmpeg`、`ffprobe` 的实际路径，再从同一个终端启动；安装 Python 包不会自动安装系统 FFmpeg。
- **YouTube 提示没有 JS runtime / challenge solver**：检查 Node.js 22.12+ 在服务 `PATH` 中，执行 `python -m pip install -U "yt-dlp[default]"` 后重启。代理、平台登录限制和地区限制仍可能另行影响下载。
- **`libGL.so.1` / `libgomp.so.1` 缺失**：这是系统动态库，不是模型或 API Key 问题；在 Ubuntu/Debian 可由管理员安装 `libgl1 libglib2.0-0 libgomp1`，其他发行版使用对应软件包。
- **不知道 Conda 环境装到哪里**：运行 `conda info --envs` 和 `conda config --show envs_dirs`；也可以将创建命令中的 `-n reibosub` 换成 `-p /path/to/envs/reibosub`，保留 `--override-channels -c conda-forge`，随后用 `conda activate /path/to/envs/reibosub` 激活。
- **Conda 提示需要接受 Anaconda 默认源条款**：使用上面的 `conda create ... --override-channels -c conda-forge ...`，再用 pip 安装项目。某些前置插件仍会拦截 `conda env create`，即使清单有 `nodefaults`；不必接受条款或改全局源。不要把 `nodefaults` 当作下载源传给 `-c`。
- **Vite 提示 Node 版本不支持或构建时报 crypto 错误**：检查激活环境后的 `node --version`，至少为 22.12；旧的 Node 22.0–22.11 不满足要求。升级后重新执行 `npm ci --include=dev` 和构建，不要用已有 `dist` 推断依赖已就绪。
- **提示安装的是 CPU 版 Paddle，无法用 GPU**：把 OCR 设备改为 `cpu`/`auto`，或先卸载 `paddlepaddle`，再按 CUDA 版本安装匹配的 `paddlepaddle-gpu`；不要同时保留 CPU/GPU 两个包。
- **服务商获取不到模型**：很多兼容接口没有 `/models`；在设置页维护静态模型 ID，仍然可以正常发起任务。
- **有模型列表却翻译失败**：再检查 Base URL 是否为兼容接口的根地址、Key 权限、额度和模型调用权限；列表成功不等于推理请求成功。
- **CPU 机器 ASR 报 CUDA 或 float16 错误**：网页入口目前使用 CUDA/float16。基础 CLI 显式设置 `--device cpu --compute-type int8`，或准备完整 NVIDIA CUDA 环境后再用网页 ASR。
- **YouTube 无法连接**：在 `configs/reibosub.yaml` 设置 `youtube_proxy`；它只作用于下载，不会代理 OCR/ASR。
- **B 站画质少、CC 不可见或提示需登录**：核对账号权限及 `bilibili_cookie_file`，修改后重启；B 站不使用 YouTube 代理。没有 CC 时，有内嵌字幕可用 OCR，纯语音则需 ASR，不能把弹幕当对白字幕。
- **切换链接后语言没变**：手动选择在当前草稿优先；点 **新建字幕任务** 才会恢复平台默认。已经保存的任务不会自动改成新的语言方向。
- **任务完成却在视频文件夹找不到字幕**：自主 Agent 常另存到任务目录；到 **素材库 → 文件与更多 → 字幕** 查看，或从任务结果下载。列表未更新先点 **刷新**，不要为此重跑整片。
- **术语翻译器报错或仍显示旧译文**：检查字幕翻译/通用模型的设置、权限与额度；修改输入或语种后要重新点 **翻译**。新前端还需配套更新并重启后端，不能只复制网页构建文件。
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

也可直接运行 `npm test`；依赖审计运行 `npm run audit:deps`，该命令包含开发依赖且在存在漏洞时返回非零退出码。

前端构建：

```bash
cd frontend
npm run build
```

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源许可证。
