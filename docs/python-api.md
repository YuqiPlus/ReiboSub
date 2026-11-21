# ReiboSub 编程 API（0.1.0 首版）

`reibosub` 是新增的公开 Python 入口。它不要求网页运行，不创建 Agent 工程，不访问项目数据库，也不自动读取 `.env`、服务商配置或网页密钥。现有 `video_translate`、网页和旧命令行继续保持原来的调用方式，本轮没有迁移或替换它们。

这是 0.x 阶段的公开接口草案，后续变更应记录兼容性说明。可独立安装 Python 工具包，也可以从源码进行二次开发；完整网页部署仍按仓库 README 操作。

## 安装与运行

在独立的 Python 3.10+ 虚拟环境中执行：

```bash
python -m pip install reibosub
python -c "from reibosub import Subtitle, Cue; print(Subtitle((Cue(1, 0, 1, 'Hello'),)).to_text())"
```

默认安装只含轻量的 OpenCC 与 packaging，不安装 OCR/ASR。字幕读写、格式转换、检查和内置 HTTP 翻译器只使用标准库；简繁转换才延迟导入 OpenCC，功能诊断才使用 packaging。网页、下载、OCR/ASR 以 extras 选装，详见 [README 的功能安装表](../README.zh-CN.md#只安装需要的功能)。旧命令入口 `video-translate` 保留；`reibosub convert/script/text/translate/doctor/setup` 使用轻量入口，原有 OCR 命令名仍按需转交旧实现。

### 检测依赖与明确授权安装

```python
from reibosub import check_feature, ensure_feature

status = check_feature("asr")  # 只读，不加载模型、不安装
print(status.ready, status.missing_requirements, status.missing_external)
ensure_feature("asr")         # 缺项时抛出 MissingDependencyError
ensure_feature("asr", install=True)  # 明确授权，只在当前 venv/Conda 环境补 Python 包
```

可检测 `core/translate/download/video/ocr/ocr-cpu/asr/diarization/web/all-cpu`。`FeatureStatus` 提供需求、缺失版本/模块、外部工具、CPU/GPU 冲突和手工步骤。版本要求解析安装包自己的标准元数据，不会自动更换 ReiboSub 版本。源码开发时在仓库根目录执行 `python -m pip install -e .`；源码更新后需重新执行，让安装元数据与代码一致。

缺失简繁依赖时，`subtitle.to_simplified(install_missing=True)` / `to_traditional(install_missing=True)` 可明确开启安装；默认仍报错，不修改环境。安装使用当前解释器的独立 pip 子进程，且有环境内锁；默认不升级、强制重装或卸载，也不代装 GPU 引擎、系统工具或模型。系统 Python、运行中网页/已加载识别库、CPU/GPU 冲突等情况会拒绝安装。缺少外部工具先自行准备，`ocr` 要求用户明确选择引擎；CPU 路线用 `ocr-cpu`。安装失败使用 `DependencyInstallError`，不会回显可能包含凭据的 pip/index 错误正文。安装不具备事务回滚能力；不要在生产进程中改环境。

`check_feature` 只是检查版本和模块/工具路径，不导入识别模型、不检查 CUDA 二进制兼容、工具版本、权重或授权；`.ready` 不是整条业务成功的保证。完整系统的部署诊断仍需按 README 验证。

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

本轮没有新增 ASR/OCR 的公开封装、异步服务、HTTP 上传 API、数据库要求或发布流水线。默认轻量安装与 extras 已拆分；正式发布前仍需验证打包范围、平台矩阵和兼容性策略。

安装保护只能识别当前进程已加载的模块和本工具自己的环境锁，不能证明同一环境没有其他进程正在使用。请在独立环境测试，或先停止共享该环境的服务；不要因为使用了新终端就认为修改共享环境没有影响。
