# Python 包发布

发布使用 `.github/workflows/publish.yml`，只构建 `packages/subtitles`。
根目录是网页项目，禁止从根目录 pyproject 构建并上传到 PyPI。
本次目录拆分未发布，0.1.0 的公开文件保持原样。PyPI Trusted Publishing 绑定：
`YuqiPlus/ReiboSub`、`publish.yml`、环境 `pypi`、项目 `reibosub`。
无需在仓库保存 PyPI Token。建议为 GitHub `pypi` 环境设置维护者审批。

## 发布边界

- 从经过审查的 Git 提交和干净目录构建，不从正在运行网页的脏工作区打包。
- `MANIFEST.in` 限定源码包内容，`scripts/check_distribution.py` 同时检查源码包和 wheel 的文件白名单、元数据和敏感信息特征。
- 不包含配置目录、密钥、用户数据、模型、媒体、前端产物、测试数据或尚未公开的存储迁移。完整网页继续使用源码部署。
- 通用扫描不能识别所有秘密，上传前还需与实际本地凭据逐项比对，并审查新增代码。
- 不在生产网站的环境中安装打包工具或执行安装测试，也不自动重启网站。

## 流程

1. 例如下一版使用 **0.1.1**：同步修改 `packages/subtitles/pyproject.toml` 的 `version` 和 `packages/subtitles/src/reibosub/__init__.py` 的 `__version__`，更新文档后提交推送公开代码；不能夹带本地配置或存储迁移。根目录 `pyproject.toml` 是网页版本，不必跟着修改。网页可以独立修改，不必发 PyPI。
2. 在干净副本执行 `python -m build packages/subtitles --outdir dist`、`python -m twine check --strict dist/*`、`python scripts/check_distribution.py dist`，安装 wheel 和源码包测试。
3. 普通 main 推送和标签推送都不会发布；在 GitHub Actions 手动运行默认只构建和测试，不上传。
4. 确认全部检查后创建与新版本一致的标签，例如 `git tag -a v0.1.1 -m "ReiboSub 0.1.1"`，再执行 `git push origin v0.1.1`。不要重新创建或移动已发布的 `v0.1.0`。
5. 明确决定发布后，手动选择新版本标签运行流程，并将 `publish` 设为 true；必须从与包版本一致的标签运行。Python 3.10–3.13 独立安装、离线功能和 API 测试通过后，独立发布任务通过 OIDC 上传。构建任务没有 PyPI 身份权限，发布任务不执行仓库构建脚本。
6. 查看 Actions 和 PyPI 上的版本，另建干净环境从官方索引安装 `python -m pip install --index-url https://pypi.org/simple reibosub==0.1.1` 验证。若环境要求审批，先由维护者批准。

GitHub 页面操作：打开仓库 **Actions → Check or publish subtitle toolkit → Run workflow**。
只检查时选择 main，保持 `publish` 为 false；正式发布选择新版本标签（如 `v0.1.1`），
将 `publish` 设为 true。流程会检查两处版本与标签是否一致；在 main 上请求发布会明确失败。
这份说明使用 0.1.1 举例，本轮未修改版本号、创建新标签或执行发布。

若网页下拉框不显示标签，可在已登录 GitHub CLI、具有仓库写权限的终端执行：

```bash
gh workflow run publish.yml --repo YuqiPlus/ReiboSub --ref v0.1.1 -F publish=true
```

未准备正式发布时不要执行该命令。使用的是现有 PyPI 可信发布授权，不需要把
PyPI Token 放入仓库或聊天。只想预检可用 `--ref main -F publish=false`。

正式索引不允许用不同文件覆盖同版本。若上传已经成功而后续发现问题，应修复并增加版本；不要移动已成功发布的版本标签。
