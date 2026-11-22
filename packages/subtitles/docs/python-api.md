# ReiboSub 编程 API（0.1.2 独立工具包）

`reibosub` 是新增的公开 Python 入口。它不要求网页运行，不创建 Agent 工程，不访问项目数据库，也不自动读取 `.env`、服务商配置或网页密钥。现有 `video_translate`、网页和旧命令行继续保持原来的调用方式，本轮没有迁移或替换它们。

这是 0.x 阶段的公开接口草案，后续变更应记录兼容性说明。可独立安装 Python 工具包，也可以从源码进行二次开发；完整网页部署仍按仓库 README 操作。

## 安装与运行

在独立的 Python 3.10+ 虚拟环境中执行：

```bash
python -m pip install reibosub
python -c "from reibosub import Subtitle, Cue; print(Subtitle((Cue(1, 0, 1, 'Hello'),)).to_text())"
```

默认安装只含 OpenCC 与 packaging，不安装网页、数据库或 OCR/ASR。核心代码位于本产品的 `src/reibosub`，不导入仓库根目录的网页代码。0.1.1 开始仅分发独立工具包；已发布的 PyPI 0.1.0 保持原样，旧识别选装组与命令的迁移见 [CHANGELOG](../CHANGELOG.md)。

源码开发从仓库根目录执行 `python -m pip install -e "./packages/subtitles[dev]"`，然后：

```bash
cd packages/subtitles
python -m pytest tests -q
python examples/python_api/subtitle_basics.py --out-dir /tmp/reibosub-api-demo
```

### 依赖检测与明确授权安装

```python
from reibosub import check_feature, ensure_feature
status = check_feature("core")  # 只读，不安装
ensure_feature("core")
# ensure_feature("core", install=True)  # 仅在独立环境中明确授权补齐轻量依赖
```

0.1.2 新增 `asr/ocr/ocr-cpu/video` 诊断，不导入识别库、不下载模型；0.1.1 的诊断范围仍只有 `core`。识别依赖必须提前显式选装，`ensure_feature(..., install=True)` 不会为这些功能运行 pip；只有 `core` 支持上述轻量修复。网页和下载的依赖管理仍属于[网页应用](../../../docs/web-application.md)。简繁转换仍支持显式 `install_missing=True`；默认不改环境。安装只使用当前解释器的 pip 子进程，要求虚拟环境、环境内锁，拒绝已加载识别库的进程；错误不回显私有索引凭据。不要修改运行中网站使用的环境。源码更新后需重新安装，让元数据与代码一致。

## OCR 与 ASR：可选识别接口（0.1.2 起）

以下新增接口从 **0.1.2** 起提供；0.1.1 没有这些接口或选装组。不要在运行网站的环境中重新安装；先建独立虚拟环境。

普通用户不需要克隆仓库，也不需要填写源码路径，直接按功能选装：

```bash
python -m pip install "reibosub[asr]>=0.1.2,<0.2"
python -m pip install "reibosub[ocr-cpu,video]>=0.1.2,<0.2"  # CPU
python -m pip install "reibosub[ocr,video]>=0.1.2,<0.2"      # CUDA 引擎需要另装
```

使用源码时，从仓库根目录安装；一般使用者不用 `-e`，二次开发者才需要可编辑安装：

```bash
python -m pip install "./packages/subtitles[ocr-cpu,video]"
# 修改源码后希望立即生效的开发安装：
python -m pip install -e "./packages/subtitles[asr,ocr-cpu,video,dev]"
# CUDA 则把 ocr-cpu 改成 ocr，并另装匹配的 GPU Paddle 引擎。
```

安装命令里的 `./packages/subtitles` 是源码产品位置，`[ocr,video]` 是功能依赖选择；二者都不是模型保存路径。安装包由当前 Python 环境管理，模型位置由下述 `cache_dir` 或本地模型目录参数管理，不需要新建网页配置文件。

| 选装组 | 用途 | 不会安装什么 |
| --- | --- | --- |
| `asr` | faster-whisper 语音识别，自带 PyAV 解码依赖 | Paddle、网页、独立 FFmpeg 可执行程序 |
| `ocr` | PaddleOCR 3.x 接口，由你选择 Paddle 引擎 | CPU/GPU Paddle 引擎、网页 |
| `ocr-cpu` | PaddleOCR + CPU Paddle 引擎 | GPU Paddle、网页 |
| `video` | PyAV 视频解码与 NumPy 图像数组，不额外安装另一份 OpenCV | OCR/ASR 引擎与模型 |

不要同时安装 CPU 和 GPU Paddle。依赖的 Python/系统/架构支持取决于第三方 wheel；推荐在 Python 3.11 独立环境先跑通 CPU。GPU/CUDA 不会自动安装，也不会因 GPU 不可用悄悄退到 CPU。`ocr-cpu` 与网页上的同名选装组是两个产品各自的元数据，不会安装网页。

### 模型生命周期

1. `import reibosub`、创建 `ASR()`/`OCR()`、`check_feature()`：不导入模型运行库、不下载权重。
2. 首次 `transcribe()` / `read_image()` / `extract_subtitles()`：导入对应库，检查模型目录/缓存，必要时由上游加载器下载。依赖缺失则报安装提示，**不调用 pip**。
3. 同一后端实例重复调用：复用内存中的模型；后续进程复用磁盘缓存，不把模型塞进安装包。
4. `backend.prepare()`：显式预热，适合部署时提前准备；`backend.close()`：释放该实例的引用（显存何时归还由运行库的分配器决定）。

### 缓存目录与路径优先级

OCR 与 ASR 都支持 `cache_dir`，默认 `None`，不填也可以直接调用。默认使用 Hugging Face 标准用户缓存，通常为 `~/.cache/huggingface/hub`，遵循上游 `HF_HOME/HF_HUB_CACHE` 等设置；不是仓库目录，也不是安装包目录。OCR 模型来自 `PaddlePaddle` 官方模型仓库，只下载推理资产，不执行远程仓库代码。

```python
from reibosub import OCR

automatic = OCR(language="korean")  # 无需配置路径
custom = OCR(language="korean", cache_dir="./models/ocr")
cuda = OCR(language="korean", device="gpu:0", cache_dir="./models/ocr")
```

优先级为：**显式本地模型目录 > `cache_dir` > 上游默认用户缓存**。OCR 检测、识别两套模型分别应用此规则，因此可以一套本地、一套缓存；显式目录错误不会改用缓存或在线下载。相对路径在创建对象时按当前工作目录固定为绝对路径，支持 `~`，之后即使切换工作目录也不改变位置。

创建对象不会创建缓存目录。首次调用先检查完整缓存，只有缺失时才下载；同一实例复用内存，跨实例/进程复用磁盘快照。可在线恢复不完整的缓存下载；离线缺文件则报错。下载/并发文件锁由 Hugging Face 管理，目录是版本化快照结构，不要把缓存根目录误当作一个可直接填入 `recognition_model_dir` 的模型目录。权限/网络错误不会静默换到其他缓存或模型。

每个实例只传自己的缓存参数，不全局改写 `HOME`、`PADDLE_PDX_CACHE_HOME`、代理或网页配置。Paddle 运行库可能另存辅助缓存，但模型权重由所选 Hub 缓存或显式目录提供；原网页仍沿用自己的路径。此前未发布工具包版本使用的 `~/.paddlex/official_models` 不会自动搬动，需要复用时可显式传入其模型子目录。

下载可能使用上游的用户缓存、网络/代理环境；不会读取网页配置或网页密钥。首次下载需要网络和磁盘空间，模型许可证也需要调用方遵守。缺少 Python 依赖只提示安装，不会在推理途中自动调用 pip。

### ASR：音视频转字幕

```python
from reibosub import ASR

recognizer = ASR(
    model="small", device="cpu", compute_type="int8",
    cache_dir="./models/asr",
)
subtitle = recognizer.transcribe(
    "input.mp4", language="ko",  # None 自动判断；也支持 zh/ja/en 等
    on_progress=lambda event: print(event.stage, event.completed, event.total),
)
subtitle.save("speech.ko.srt")
subtitle.to_simplified().save("speech.hans.srt")  # 仅中文文本有实际简繁变化
```

支持本地音频/视频文件，不接受 URL 下载；路径错误在加载模型前报告。ASR 进度单位是已处理音频毫秒，不是“字幕条数”；字幕按原始音频的绝对秒数返回。`vad_filter=True`、`beam_size=5` 可在构造时调整。零时长/空文本片段不会编造结束时间，会跳过并记录在 `subtitle.notices`；其他非法时间会报错。基础 ASR 不做说话人分离、LLM 纠错或精确强制对齐，准确性仍需验收。

离线/预下载示例：

```python
from pathlib import Path
from reibosub import ASR

offline = ASR(model="small", cache_dir="./models/asr", local_files_only=True)
# 或 model=Path("./converted-whisper-model")，指向完整 CTranslate2 模型目录。
offline.transcribe("speech.wav", language="zh").to_simplified().save("speech.zh.srt")
```

`local_files_only=True` 交给 faster-whisper/Hub 禁止模型下载，缓存缺失立即报 `ModelUnavailableError`，不会切换模型或供应商。需要严格离线部署时也应由部署环境禁用外网，并提前准备完整权重、分词器和配置。

### OCR：图片与视频字幕

```python
from reibosub import OCR

reader = OCR(language="korean", device="cpu", cache_dir="./models/ocr")
# cache_dir 可完全省略；CUDA 使用 device="gpu:0"，前提是装好了匹配的 GPU Paddle。
regions = reader.read_image("frame.png")
for region in regions:
    print(region.text, region.confidence, region.polygon)

reader.extract_subtitles(
    "input.mp4", sample_fps=3,
    crop=(0, 0.65, 1, 1),
    exclude=((0.8, 0, 1, 0.15),),  # 可传多个 Logo 遮罩
    start=0, end=60, min_confidence=0.5, language="ko",
).save("screen.ko.srt")
```

OCR 引擎语言码用 `korean/japan/ch/chinese_cht/en`，不是 ASR 的 `ko/ja/zh/en`。`extract_subtitles(language=...)` 只是结果元数据，不会重建引擎；识别语言在 `OCR(language=...)` 时选择。`read_image` 接受本地图片路径或 OpenCV 的 BGR ndarray，返回不可变 `TextRegion(text, confidence, polygon)`，坐标是输入图片上的像素。置信度来自引擎，不代表真值。

视频裁剪与遮罩用相对**完整画面**的 `(左, 上, 右, 下)` 比例，范围 0–1；遮罩先涂黑再送 OCR。PyAV 顺序解码，使用实际帧时间戳，区间外帧跳过识别；SRT 使用整片的绝对时间。相邻采样文字完全一致才合并，空白采样会切断；时间误差约为采样间隔，末帧结束仍参考容器平均 FPS。默认全幅识别，字幕区域已知时请传 `crop`，否则物品文字/Logo 可能进入结果。解码提前失败不会假装整片成功；回调可用于进度展示，`cancelled=lambda: ...` 在帧间协作取消，但不能打断正在执行的原生单次推理/下载。

这是**基础抽帧 OCR**，不等同网页稳定 OCR 3.0 的轨迹精修、LLM 去噪、逐字字幕恢复、边界校准，更不会自动调用 LLM。网页 OCR/ASR 及实验 Agent 代码不迁入工具包，本轮不改变它们。CPU 默认 `enable_mkldnn=False`，避免部分 Paddle/oneDNN 组合的推理兼容问题；你验证过环境后可显式打开优化。

离线 OCR 可以复用先前下载到 `cache_dir` 的两套模型，也可以指定已有的本地模型目录。为兼容上游版本，在启动 Python 前禁用 Paddle 的联网探测：

```bash
# 启动 Python 前设置；工具包不会悄悄修改进程的全局环境。
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
```

```python
from reibosub import OCR

reader = OCR(
    language="korean", cache_dir="./models/ocr", local_files_only=True,
)
reader.read_image("frame.png")  # 缓存缺失直接报错，不下载

# 或者使用已有的完整模型目录，优先级高于缓存：
local = OCR(
    language="korean", device="cpu", local_files_only=True,
    detection_model_dir="./models/detection",
    recognition_model_dir="./models/korean-recognition",
    # 自训练模型还可传 detection_model_name / recognition_model_name。
)
local.read_image("frame.png")
```

每个显式目录至少需要 `inference.pdiparams` 和 `inference.json` 或 `inference.pdmodel`；还应保留原下载中的配置文件，模型名称/配置必须与上游 PaddleOCR 匹配。显式目录缺文件、未关闭上游联网探测时，会在导入运行库前拒绝启动；缓存模式要先解析语言/模型名称，再查本地快照，缺失时报 `ModelUnavailableError`，不会下载。工具包不会自行寻找网页模型或把不完整的显式目录降级为在线下载。

### 自定义识别后端

```python
from reibosub import ASR, OCR, Cue, Subtitle, TextRegion

class MySpeechBackend:
    def transcribe(self, source, *, language, on_progress, cancelled):
        # 对接你自己的模型/API；协作处理取消和进度，不读取网页密钥。
        return Subtitle((Cue(1, 0.1, 1.8, "Hello"),), language=language)

class MyImageBackend:
    def recognize(self, image):
        return (TextRegion("Hello", 0.9, ((0, 0), (80, 0), (80, 24), (0, 24))),)

speech = ASR(backend=MySpeechBackend())
images = OCR(backend=MyImageBackend())
```

对应结构化协议为 `ASRBackend` 和 `OCRBackend`。自定义后端无需安装默认引擎；视频解码仍需 `video`。远程识别的上传、收费、认证、缓存与隐私由后端自己明确实现，不自动切服务商。错误类型：缺依赖 `MissingDependencyError`，模型加载失败 `ModelUnavailableError`，推理/结果格式异常 `RecognitionError`，取消 `OperationCancelled`。内置错误不回显上游异常正文，避免泄露下载凭据；需要排查时检查引擎自身日志。

## 统一数据结构

```python
from reibosub import Cue, Subtitle

subtitle = Subtitle((
    Cue(index=1, start=0.5, end=2.0, text="第一句", speaker="Speaker 1"),
    Cue(index=2, start=3.0, end=5.0, text="第二句", confidence=0.93),
), language="zh")
data = subtitle.to_dict()
restored = Subtitle.from_dict(data)
```

- `Cue`：唯一正整数 `index`、以秒为单位的有限数值 `start/end`、`text`，以及可选 `speaker/confidence`。要求 `0 <= start < end`；允许时间重叠，以便表达原有字幕，不会自动修时间。
- `Subtitle`：不可变的 `cues` 元组、可选语言、读取格式 `source_format` 和格式限制说明 `notices`。可遍历、用下标访问、用 `len()` 统计。
- `SubtitleIssue`：`code/message/cue_indexes/severity`；`subtitle.check()` 返回空文本、乱序与重叠提示，不修改字幕。
- `Progress`：`completed/total/stage`，供翻译进度回调使用。
- `to_dict()/from_dict()` 使用 `version: 1` JSON 数据结构，保留公开 Cue 字段。`confidence` 是来源识别置信度，翻译后保留它不代表对译文质量重新打分。

## 字幕读写、转换与简繁

```python
from reibosub import Subtitle, convert

source = Subtitle.load("input.srt")
source.save("output.vtt")
source.to_simplified().save("simplified.srt")
source.to_traditional().save("traditional.srt")
print(source.to_text())
print(source.to_text(timestamps=True))

convert("input.srt", "converted.ass")
content = source.dumps("json")
restored = Subtitle.loads(content, format="json")
```

文件编码默认读取 UTF-8/BOM、写入 UTF-8；其他编码显式传 `encoding="gb18030"` 等。无扩展名文件需显式传 `format`。函数不限制调用者的文件目录，也不会把文件登记进素材库；路径访问权限由你的应用负责控制。

所有文本变换返回新 `Subtitle`，不修改原对象。保存默认拒绝覆盖，包括已有符号链接；只有显式 `overwrite=True` 才替换已有文件。文件先写入同目录临时文件，再原子发布；默认不覆盖的发布方式需要文件系统支持硬链接，不支持时报告 `OSError`，不会悄悄降级成覆盖。临时文件会清理。

### 格式范围与损失

| 格式 | 支持范围与限制 |
| --- | --- |
| SRT | 毫秒时间与正文，保留数字索引；不做字体渲染 |
| WebVTT | 正文与时间；cue 标识、区域、位置设置不保留 |
| JSON | `version/language/cues`，完整保留公开 Cue 字段；也可读取旧的 cues 数组 |
| BCC | `body` 中的时间与正文；外观和位置不保留 |
| ASS/SSA | Dialogue 时间、正文、Name 说话人；写出默认样式，原样式、绘图、位置、特效不保留，时间精度为厘秒 |
| LRC | 支持多时间标签；结束时间推断，最后一条默认 3 秒；导出不保留原结束时间 |
| TXT | 纯文字；读取时按每个非空行 3 秒生成合成时间，绝不是音频对齐 |

转换经统一模型进行，**不承诺原生文件无损往返**。尤其不要把 API 的 ASS 简繁转换当作网页工具箱的原生样式保留转换；网页的对应实现本轮未改。读取限制可查看 `subtitle.notices`。过短时间段若无法用目标格式精度表达，会报错而不是写出零时长。

## 翻译：内置服务与自定义后端

```python
import os
from reibosub import Subtitle, Translator

translator = Translator(
    base_url="https://your-provider.example/v1",  # 替换成自己的服务
    api_key=os.environ["MY_TRANSLATION_API_KEY"],
    model="your-model-id",
    glossary={"ReiboSub": "ReiboSub"},
    extra_prompt="保留说话人标签。",
    timeout=60,
)
result = translator.translate(
    Subtitle.load("input.srt"), target_language="en", batch_size=40,
    on_progress=lambda event: print(event.completed, event.total),
)
result.save("output.en.srt")
```

内置 `Translator` 使用 [Chat Completions 请求/响应协议](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)，适配提供该协议的服务，不承诺任意模型或所有厂商都兼容。服务地址可填 API 根路径或完整 `/chat/completions` 地址；模型由调用方指定，不硬编码、不自动选供应商。目标语言为非空语言名称/代码，`zh` 约定为简体、`zh-Hant` 为繁体；来源默认取 `subtitle.language`，否则 `auto`。

调用会把正文、固定译名与补充要求发给所选服务并可能产生费用；时间轴不发送给模型，也不让模型改动。要求模型按 ID 返回完整 JSON，批次有遗漏、重复 ID、空译文或截断时抛出 `TranslationError`。外层翻译还会验证条数，严格保留 index、时间、speaker、confidence。语义准确性仍需调用方验收。

不读取网站或用户目录配置；示例中的环境变量是示例程序自己显式读取的。默认不继承环境代理，可用 `proxy="http://127.0.0.1:7890"` 指定。禁止自动重定向以免转发密钥；不自动重试、不自动切换模型/服务。密钥不会出现在对象 repr、HTTP 错误正文或库的错误消息中。

### 接入自己的模型

```python
from reibosub import Subtitle, translate

class MyTranslator:
    def translate_batch(self, texts, *, source_language, target_language):
        # 调用本地模型/其他 SDK，并保证一入一出、顺序不变。
        return [my_model(text, target_language) for text in texts]

result = translate(
    Subtitle.load("input.srt"), translator=MyTranslator(), target_language="en",
)
```

上述 `my_model` 由使用者提供；可直接运行的离线后端示例见下方。实现 `TranslationBackend` 协议即可，无需继承类或修改本项目。输出必须是字符串序列（如 list/tuple），与输入同序同条数；语义对应关系由后端负责。

### 进度、取消与错误

`translate(..., cancelled=event.is_set)` 支持协作取消，在每批请求前后检查；不能强行打断正在进行的 HTTP 请求，最迟等该请求返回或超时。`on_progress` 在开始时报告 0、之后每批报告完成条数。回调自身的异常原样传给调用者。取消/失败不返回部分字幕，不写文件，也不改变源对象；自行再次请求可能重复产生费用，本版本不提供断点续翻。

公开异常：`ReiboSubError`、`ValidationError`、`SubtitleFormatError`、`MissingDependencyError`、`TranslationError`、`OperationCancelled`。文件不存在、覆盖冲突、编码及系统 I/O 错误保留标准 Python 异常类型。自定义翻译器意外异常包装为 `TranslationError`，不复制可能含密钥的异常正文。

## 自定义字幕格式

```python
from reibosub import FormatRegistry, Subtitle

registry = FormatRegistry()
registry.register("myformat", MyCodec())
subtitle = Subtitle.loads(content, format="myformat", registry=registry)
subtitle.save("output.myformat", registry=registry)
```

`MyCodec` 实现 `loads(text: str) -> Subtitle`、`dumps(subtitle: Subtitle) -> str`，对应 `SubtitleCodec` 协议。注册只影响这个实例；重复注册默认报错，覆盖需要 `replace_existing=True`。示例 TSV codec 演示了实际用法。

## 可运行的二次开发示例

在仓库根目录、完成安装后运行，输出目录/文件请使用新路径：

```bash
python examples/python_api/subtitle_basics.py --out-dir /tmp/reibosub-api-demo
python examples/python_api/custom_backend.py --out /tmp/reibosub-custom.en.srt
python examples/python_api/custom_format.py --out /tmp/reibosub-custom.tsv
```

前三个都是离线示例，不使用网页配置或真实视频。`examples/python_api/translate_service.py --help` 展示显式模型服务调用方式；只有你自行提供地址、模型和 `MY_TRANSLATION_API_KEY` 并运行它，才会发请求。本轮测试使用本地模拟服务，没有调用付费模型。

回归测试：

```bash
python -m pytest tests/test_public_api.py tests/test_public_translation_http.py -q
```

独立工具包只构建字幕 API；网页、识别与 Agent 是另一个产品。每次发布均需增加工具包版本并完成独立构建、安装与兼容性验收。

安装保护只能识别当前进程已加载的模块和本工具自己的环境锁，不能证明同一环境没有其他进程正在使用。请在独立环境测试，或先停止共享该环境的服务；不要因为使用了新终端就认为修改共享环境没有影响。
