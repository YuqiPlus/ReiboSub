# OCR 开发与服务器迁移交接

更新日期：2026-07-13

## 1. 当前目标

当前工作聚焦于 OCR 开发测试流程，不重新翻译，也不要求重新执行视频 OCR：

1. 从已有 `tracks.json` 和 `ocr_boxes.json` 重建 `source.rebuilt.srt`。
2. 将逐帧 OCR 压缩为轨迹证据摘要。
3. 让 LLM 先分类字幕类型，再执行保留、删除、替换或合并。
4. 输出 `source.track_refined.srt`，用于播放器人工检查。

目标是同时解决以下问题：

- 渐进出现的字幕被切成多个短片段。
- 同一行 OCR 框错序，例如句首小框被放到句尾。
- OCR 稳定误字需要结合少数正确帧和语言规则修正。
- 衣服、Logo、角标、英文数字残片和单帧乱码混入字幕。
- LLM 将 `machine_text` 与逐帧候选错误串接，产生重复句子。

## 2. Git 状态

当前仓库：`YuqiPlus/Video_Translate`

- 当前分支：`main`
- 当前提交：`bd9ae44 Add region OCR exclusion controls`
- 远端：`github git@github.com:YuqiPlus/Video_Translate.git`
- 当前 OCR 开发改动尚未提交，也未推送到远端。

主要未提交文件：

- `frontend/src/App.vue`
- `frontend/src/styles.css`
- `frontend/src/components/OcrDevPanel.vue`（新文件）
- `video_translate/ocr/extractor.py`
- `video_translate/ocr/llm_refine.py`
- `video_translate/pipeline.py`
- `video_translate/run_config.py`
- `video_translate/web_agent.py`
- `tests/test_ocr_extractor.py`
- `tests/test_ocr_llm_refine.py`
- `tests/test_text_pipeline.py`
- `tests/test_web_agent.py`

推荐先在当前机器创建独立分支并提交，再去另一台服务器继续：

```bash
git switch -c codex/ocr-track-refine
git add frontend/src/App.vue frontend/src/styles.css frontend/src/components/OcrDevPanel.vue
git add video_translate/ocr/extractor.py video_translate/ocr/llm_refine.py
git add video_translate/pipeline.py video_translate/run_config.py video_translate/web_agent.py
git add tests/test_ocr_extractor.py tests/test_ocr_llm_refine.py tests/test_text_pipeline.py tests/test_web_agent.py
git add docs/OCR_DEVELOPMENT_HANDOFF.md
git commit -m "Develop OCR track refinement workflow"
git push -u github codex/ocr-track-refine
```

如果明确要直接进入主分支，也可以在 `main` 提交并执行 `git push github main`。当前阶段仍属于实验迭代，独立分支更容易对比和回退。

另一台服务器已有仓库时：

```bash
git fetch github
git switch codex/ocr-track-refine
git pull --ff-only
```

没有仓库时：

```bash
git clone git@github.com:YuqiPlus/Video_Translate.git
cd Video_Translate
git switch codex/ocr-track-refine
```

## 3. 当前实现

### OCR Lab

Web UI 新增独立 OCR 调试区域，支持：

- 本地视频和素材库选择。
- OCR 区域、Logo 排除框、置信度、采样 FPS。
- 精确时间边界和短闪段平滑参数。
- 输出 `source.srt`、逐采样帧 JSON、OCR 框 JSON 和轨迹 JSON。
- 将视频和字幕整理到下载目录下的 `debug/<视频名>/`。
- 对已有 SRT 单独运行 LLM 去噪。
- 使用已有 JSON 执行“从 JSON 重建 + LLM 精修”，不重新解码视频、不重新跑 PaddleOCR。

### 轨迹型 LLM 精修

当前 `video_translate/ocr/llm_refine.py` 已改为：

1. 每条字幕统计持续时间、采样帧数、区域支持度。
2. 汇总完整阅读候选及其出现帧数。
3. 汇总文字块候选、支持比例、平均置信度和平均坐标。
4. 将证据标为 `stable`、`weak` 或 `single_sample`。
5. 要求 LLM 分类为：
   - `subtitle`
   - `program_caption`
   - `scene_text`
   - `noise`
6. LLM 返回绑定原字幕 ID 的动作：
   - `keep`
   - `drop`
   - `replace`
   - `merge`
7. 每个目标 ID 必须且只能被一个动作覆盖。
8. 未参与合并的孤立单采样条目会被强制删除。
9. 相邻、相同或存在包含关系的短片段会进行保守合并。

这样可避免模型自由生成新时间段，也可避免把机器字幕和逐帧候选当作前后两句话串接。

## 4. 已知测试样例

重点视频：

```text
EXAMPLE_VIDEO_TITLE
```

### 14 秒样例

时间：

```text
00:00:13,947 --> 00:00:16,491
```

画面真实字幕：

```text
아 뭔가 두고 갔어!
```

历史错误包括：

```text
뭔가 두고갔에! 아
뭔가 아 뭔가 두고 갔어!
```

原因分别是视觉行排序错误，以及 LLM 将两套候选串接。当前证据摘要中可看到：

- `아` 位于同一行最左侧，并跨多帧出现。
- `뭔가` 稳定出现。
- 多数帧误识别为 `갔에`，但至少一帧正确识别为 `갔어!`。

### 已发现噪声

上一版真实结果出现过：

```text
똑똑똑 V0
기기
Unabel
U0R
GUN '19 ...
EEEE ZL
```

最新证据摘要会将 `V0` 等候选的帧支持、置信度和位置单独暴露给 LLM，不再直接把逐帧完整行当成可信字幕。

## 5. 当前验证状态

后端完整测试：

```text
273 passed
```

服务启动命令：

```bash
python run_agent_ui.py
```

默认地址：

```text
http://127.0.0.1:7860
```

重要：最终“轨迹证据分类 + 动作校验”版本已经通过单元测试和真实 JSON 的本地证据生成检查，但尚未完成一次新的全片 LLM 精修结果验收。

当前调试目录中：

- `source.rebuilt.srt` 修改时间为 2026-07-13 16:14。
- `source.track_refined.srt` 修改时间为 2026-07-13 15:20，仍是上一版产生的含噪结果。

因此另一台服务器上的第一项工作应是重新运行一次“从 JSON 重建 + LLM 精修”，然后统计短条目、英文数字条目，并人工检查 14 秒、40–51 秒、560–675 秒附近。

## 6. 必须迁移的非 Git 文件

以下文件均被 `.gitignore` 排除，不能依赖 Git：

### 配置和密钥

- `.env`
- `configs/llm.yaml`

不要把真实 API Key 写进本交接文档或提交到 Git。通过 SSH、密码管理器或服务器 Secret 管理单独传输。

至少检查这些配置：

```text
LLM_API_KEY
LLM_BASE_URL
LLM_MODEL
LLM_REQUEST_TIMEOUT
LLM_REQUEST_RETRIES
VIDEO_TRANSLATE_HOST
VIDEO_TRANSLATE_PORT
VIDEO_TRANSLATE_DOWNLOAD_DIR
VIDEO_TRANSLATE_CACHE_DIR
VIDEO_TRANSLATE_OCR_DEVICE
```

### OCR 调试数据

当前源机器目录：

```text
C:\path\to\Video_Translate\YoutubeDownloads\debug\EXAMPLE_VIDEO_TITLE
```

仅继续 JSON 重建和 LLM 精修时，最少需要：

```text
tracks.json
ocr_boxes.json
run.yaml
```

推荐一并携带：

```text
source.before_cleanup.srt
source.rebuilt.srt
source.track_refined.srt
tracks_debug.csv
ocr_sample_frames.json
```

如果需要播放器人工检查，再携带同名 MP4。视频约 207 MB；仅 JSON 重建不需要视频文件。

目标目录必须放在：

```text
${VIDEO_TRANSLATE_DOWNLOAD_DIR}/debug/<视频名>/
```

后端会限制可访问路径，放到任意其他目录可能无法从 OCR Lab 选择。

可以先在源机器打包整个调试文件夹：

```powershell
$debugRoot = 'C:\path\to\Video_Translate\YoutubeDownloads\debug'
$folder = 'EXAMPLE_VIDEO_TITLE'
tar -caf ocr-debug-handoff.tar.gz -C $debugRoot $folder
```

传到目标服务器后解压：

```bash
mkdir -p "$VIDEO_TRANSLATE_DOWNLOAD_DIR/debug"
tar -xaf ocr-debug-handoff.tar.gz -C "$VIDEO_TRANSLATE_DOWNLOAD_DIR/debug"
```

## 7. 目标服务器环境

推荐使用项目环境文件：

```bash
conda env create -f environment.yml
conda activate video-translate
```

该环境使用 Python 3.11，并包含 FFmpeg 和 Node.js 20+。

前端构建：

```bash
cd frontend
npm install
npm run build
cd ..
```

启动前复制配置模板：

```bash
cp .env.example .env
cp configs/llm.example.yaml configs/llm.yaml
```

然后使用安全传输过来的真实配置覆盖对应值。

如果目标服务器还要重新运行 PaddleOCR，需要安装与 CUDA 匹配的 PaddlePaddle GPU 包，并设置 `VIDEO_TRANSLATE_OCR_DEVICE=gpu:0`。仅使用已有 JSON 进行 LLM 精修时，不需要重新下载 OCR 模型或重新解码视频。

模型缓存目录 `models/` 也不在 Git 中。可以复制以避免重新下载，也可以在目标服务器重新生成。

## 8. 目标服务器验收步骤

```bash
python -m pytest -q
cd frontend && npm run build && cd ..
python run_agent_ui.py
```

打开 OCR Lab 后：

1. 刷新调试素材库。
2. 确认目标 debug 文件夹可见。
3. 点击“从 JSON 重建 + LLM 精修”。
4. 日志应先打印 `ocr_refine_model: <模型名>`。
5. 等待全部批次完成，不要在任务运行期间重启服务。
6. 检查 debug 目录中新生成的 `source.track_refined.srt`。

建议验收脚本或人工检查以下指标：

- 总字幕条数。
- 时长小于 0.5 秒的条数。
- 含英文或数字的条数。
- 孤立单字符/双字符条数。
- 14 秒是否为 `아 뭔가 두고 갔어!`。
- 是否仍出现 `V0`、`Unabel`、`GUN '19` 等噪声。

## 9. 运行注意事项

- Web 任务列表保存在内存中，重启服务会清空任务状态。
- OCR 或 LLM 任务运行时不要重启服务；先检查 `/api/jobs` 中是否存在 `queued`、`running` 或 `cancel_requested`。
- `h264 mmco: unref short failure` 是视频解码警告，不等同于 OCR 卡死。
- 从已有 JSON 重建时，日志应显示 `rebuild: using existing OCR JSON; video decoding is skipped`。
- Git 只迁移代码，不能迁移正在运行的任务进程。目标服务器需要从已有 JSON 重新发起 LLM 精修。

## 10. 下一步开发建议

1. 完成最终轨迹分类版本的第一次全片真实 LLM 运行。
2. 对比本次结果与上一版 `source.track_refined.srt`。
3. 如果仍保留大量噪声，优先调整分类证据和动作约束，不要重新放开逐帧原文直接拼接。
4. 如果字幕被误删，检查 `single_sample` 强制规则是否需要结合邻近轨迹进一步放宽。
5. 为每次实验保留带版本后缀的 SRT，避免覆盖后无法对比，例如：

```text
source.track_refined.v1.srt
source.track_refined.track-evidence.srt
```
