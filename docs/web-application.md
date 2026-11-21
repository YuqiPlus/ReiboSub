# ReiboSub 网页应用

这是同仓库中独立于 Python 工具包的网页产品，项目名为 `reibosub-web`。
为兼容既有部署，后端 `video_translate/`、前端 `frontend/`、配置目录、素材目录和
`run_agent_ui.py` 启动路径继续保留在仓库根目录，不搬迁现有用户数据。

## 安装与启动

在仓库根目录、独立环境中执行：

```bash
# 本地开发同时安装工具包和网页，避免误用另一个旧版本的工具包。
python -m pip install -e ./packages/subtitles -e ".[web]"
# 需要 CPU OCR/ASR 时：python -m pip install -r requirements.txt
# GPU 使用 requirements-gpu-cu126.txt，并单独安装匹配的 GPU Paddle。
cd frontend
npm ci --include=dev
npm run build
cd ..
python run_agent_ui.py
# 同一入口也可运行：reibosub-web
```

系统工具 FFmpeg/Node、模型、CUDA、服务商密钥按 [中文部署说明](../README.zh-CN.md)
准备。本页仅描述结构拆分，原有模型选择、OCR/ASR 实验版和 Agent 行为不变。
目录拆分尚未发布，因此开发此分支时务必同时安装同仓库的工具包；不要把已发布
0.1.0 中附带的旧网页代码与新版网页混用。全程使用独立环境，不在线修改生产环境。

## 依赖与职责

根目录 `pyproject.toml` 只构建网页后端，依赖公开的 `reibosub>=0.1.0,<0.2`；
PyPI 工具包在 `packages/subtitles` 独立构建，不能导入网页或访问其配置。
网页通过公开的 `Subtitle` API 复用中文简繁转换；原生 ASS 样式保留、上传限制、
任务调度、素材登记和模型配置仍由网页负责，不能为了复用而改变既有输出语义。

识别/下载/网页的选装组 `translate/download/video/ocr/ocr-cpu/asr/diarization/web/all-cpu`
归网页项目维护，不再作为新工具包版本的 extras。已发布的 PyPI 0.1.0 保持原样。
旧 `video-translate` 命令属于网页，独立的 `reibosub` 命令只做字幕工具。

```bash
python -m video_translate.dependencies doctor web --json
python -m video_translate.dependencies setup asr --dry-run
# 只有显式 --yes 才安装；不要改运行中服务使用的环境。
```

## 测试与开发

```bash
python -m pip install -e "./packages/subtitles[dev]" -e ".[web,dev]"
python -m pytest tests/test_web_bootstrap.py tests/test_optional_features.py tests/test_product_boundaries.py tests/test_chinese_asr_output.py tests/test_subtitle_toolbox.py tests/test_release_distribution.py -q
# 安装了相应识别/数值计算依赖的开发环境可再运行：python -m pytest tests -q
cd frontend
node --test src/*.test.mjs           # 网页前端
npm run build
```

以上是无 OCR/ASR 框架的网页基础集成测试；全量回归还覆盖识别模块，例如 ASR
测试需要 NumPy 等可选依赖。工具包测试单独在 `packages/subtitles` 运行，不需要网页依赖或用户配置。
回归测试请在干净副本和独立环境执行，不连接真实用户配置或数据库。
本次不修改、发布或迁移本地存储实现，不自动重启服务。
