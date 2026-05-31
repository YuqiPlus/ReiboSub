# Video Translate

硬字幕视频翻译工具的第一版骨架：从视频抽帧 OCR，合并连续字幕，过滤长时间固定出现的 logo/节目名/水印，再导出原文 SRT、待翻译 JSON 和忽略轨道。

## 当前能力

- 抽取视频底部字幕区域进行 OCR。
- 按时间、位置、文本相似度合并跨帧 OCR 结果。
- 将长期固定出现的文字标记为 `persistent_overlay`，默认不进入主字幕。
- 支持术语表/角色名表，为后续大模型翻译提供上下文。
- 导出：
- `source.srt`
- `tracks.json`
- `ignored_tracks.json`
- `translation_batch.json`
- `zh.srt`

## 火山方舟/豆包配置

不要把密钥写进代码。复制 `.env.example` 为 `.env`，填入：

```text
ARK_API_KEY=你的火山方舟 API Key
ARK_MODEL=你的模型名或接入点 ID
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

`.env` 已经加入 `.gitignore`，不会被提交。

## 环境

你提供的 Conda 环境：

```powershell
C:\path\to\conda\envs\video-translate\python.exe
```

安装依赖：

```powershell
C:\path\to\conda\envs\video-translate\python.exe -m pip install -e .
```

如果 PaddleOCR 安装较慢，可以先不安装，使用 `merge-ocr` 命令调试已经保存的 OCR JSON。

## 使用

### PyCharm 运行

复制配置文件：

```powershell
copy configs\run.example.yaml configs\run.yaml
```

修改 `configs\run.yaml` 里的视频路径、语言、输出目录等，然后在 PyCharm 里直接运行项目根目录下的：

```text
run_from_config.py
```

如果 `sidecar.enabled` 为 `true`，每次运行后会把字幕覆盖复制到视频同级目录，例如：

```text
demo.source.srt
demo.zh.srt
```

默认模型缓存会写到项目目录：

```text
C:\path\to\Video_Translate\.cache
```

如果你想改到别的盘：

```powershell
$env:VIDEO_TRANSLATE_CACHE_DIR="C:\path\to\Video_Translate\.cache"
```

检查依赖和缓存路径：

```powershell
C:\path\to\conda\envs\video-translate\python.exe -m video_translate doctor
```

从视频生成原文字幕：

```powershell
video-translate extract "input.mp4" --lang korean --out "outputs\demo"
```

或者不安装命令入口，直接用模块方式：

```powershell
C:\path\to\conda\envs\video-translate\python.exe -m video_translate extract "input.mp4" --lang korean --out "outputs\demo"
```

只合并已有 OCR 采样结果：

```powershell
video-translate merge-ocr "ocr_samples.json" --out "outputs\demo"
```

生成翻译批次 JSON：

```powershell
video-translate prepare-translation "outputs\demo\source.srt" --glossary "configs\glossary.example.yaml" --out "outputs\demo\translation_batch.json"
```

大模型返回 JSON 后生成中文字幕：

```powershell
video-translate apply-translation "outputs\demo\source.srt" "outputs\demo\translated.json" --out "outputs\demo\zh.srt"
```

直接使用火山方舟/豆包翻译：

```powershell
C:\path\to\conda\envs\video-translate\python.exe -m video_translate translate-volcengine "outputs\demo\source.srt" --glossary "configs\glossary.example.yaml" --out "outputs\demo\zh.srt"
```

支持的大模型返回格式：

```json
[
  {"id": 1, "zh": "你好。"},
  {"id": 2, "zh": "今天很冷。"}
]
```

## 下一步

1. 接入真实 LLM 翻译适配器。
2. 增加截图校对界面。
3. 增加 `secondary_caption` 综艺花字的可选翻译流。
4. 使用更细的区域检测，支持手机聊天框、公告牌等屏幕文字。
