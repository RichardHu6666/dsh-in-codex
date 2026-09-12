# 参与开发

欢迎提交问题和 Pull Request。请用中文描述复现步骤、预期行为、实际行为及平台版本，
并避免上传密钥、个人配置和完整任务日志。

## 本地开发

先执行 `npm ci`，然后创建用于开发的 Python 环境：

```sh
python -m venv .venv
```

Windows 后续使用 `.venv\Scripts\python.exe`，Linux 使用 `.venv/bin/python`。
以下以激活该虚拟环境后的 `python` 为例：

```sh
python -m pip install -c constraints.txt -e ".[dev]"
npm test
python -m pytest -q
python -m ruff check src tests scripts
npm pack --dry-run
```

离线测试使用 fake worker，不调用模型。`examples/smoke_project` 是故意包含错误的
验收夹具，不应被修成正确实现；真实测试会将它复制到独立目录。

初始化项目后，用 npm 启动器验证两个 MCP 客户端握手：

```sh
python scripts/smoke_npm.py --root /absolute/path/to/initialized-project
```

如果 Node 不在 PATH，追加 `--node /absolute/path/to/node`。

## 真实验收（可能计费）

仅在明确了解费用且已在本地配置凭证后执行：

```sh
python scripts/smoke_mcp.py --live --isolated
python scripts/smoke_parallel_mcp.py --live --count 2
```

这些脚本在本仓库 `work/` 内创建隔离测试目录；不要指向生产代码。
`--count 8` 用于完整并发验收，但会产生更多模型调用。
必须检查实际工具执行证据、测试数量、`OK`、`HARNESS_TEST_EXIT=0`，
并独立复测。模型回复或仅仅显示 `completed` 都不能视为验收通过。

## 提交要求

- 修改行为时补充测试，涉及进程生命周期的改动在 Windows 和 Linux 上验证。
- 不提交 `.env`、`.runtime`、虚拟环境、npm 依赖或本机 `.codex` 配置。
- 保留失败证据并说明未验证项，不以 fake worker 的结果替代真实 Harness 验收。
- 依赖升级需同时核查 SDK、runtime、npm 锁文件和平台兼容性。

## 发布流程

仓库发布与 npm 发布是两件事，本仓库不会因推送代码而自动发布 npm 包。
正式 npm 发布前需确认包名权限、版本、许可证、包内容和安装测试：

1. 在干净的 Windows、Ubuntu 环境从 npm 压缩包安装，验证 init、doctor 与 MCP 握手。
2. 执行离线测试，人工完成必要的真实模型验收。
3. 检查 `npm pack --dry-run` 不含敏感文件，确认 README 与版本一致。
4. 由维护者单独批准并执行 npm 发布，不在 CI 中存储或输出模型密钥。
