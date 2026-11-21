# Python 包发布

发布使用 `.github/workflows/publish.yml`，PyPI Trusted Publishing 绑定：
`YuqiPlus/ReiboSub`、`publish.yml`、环境 `pypi`、项目 `reibosub`。
无需在仓库保存 PyPI Token。建议为 GitHub `pypi` 环境设置维护者审批。

## 发布边界

- 从经过审查的 Git 提交和干净目录构建，不从正在运行网页的脏工作区打包。
- `MANIFEST.in` 限定源码包内容，`scripts/check_distribution.py` 同时检查源码包和 wheel 的文件白名单、元数据和敏感信息特征。
- 不包含配置目录、密钥、用户数据、模型、媒体、前端产物、测试数据或尚未公开的存储迁移。完整网页继续使用源码部署。
- 通用扫描不能识别所有秘密，上传前还需与实际本地凭据逐项比对，并审查新增代码。
- 不在生产网站的环境中安装打包工具或执行安装测试，也不自动重启网站。

## 流程

1. 修改 `pyproject.toml` 版本与对应文档，提交公开代码；不能夹带本地 `database` extra 或存储迁移。
2. 在干净副本执行 `python -m build`、`python -m twine check --strict dist/*`、`python scripts/check_distribution.py dist`，安装 wheel 和源码包测试。
3. 普通 main 推送不会发布；可在 GitHub Actions 手动运行该流程，只构建和测试，不上传。
4. 确认全部检查后创建与版本一致的标签，例如 `git tag -a v0.1.0 -m "ReiboSub 0.1.0"`，再执行 `git push origin v0.1.0`。
5. 标签触发重新构建，Python 3.10–3.13 独立安装、离线功能和 API 测试通过后，独立发布任务通过 OIDC 上传。构建任务没有 PyPI 身份权限，发布任务不执行仓库构建脚本。
6. 查看 Actions 和 PyPI 上的版本，另建干净环境从官方索引安装 `reibosub==0.1.0` 验证。若环境要求审批，先由维护者批准。

正式索引不允许用不同文件覆盖同版本。若上传已经成功而后续发现问题，应修复并增加版本；不要移动已成功发布的版本标签。
