# 验证记录

更新日期：2026-09-12。以下区分本地实测、历史真实模型验收和未完成项目。
原始任务记录包含本地环境及任务内容，不随开源仓库上传。

## 已验证环境

| 平台 | 环境 |
| --- | --- |
| Windows | Python 3.13、Node 24.19.0、官方 Harness Node runtime |
| Ubuntu 24.04 WSL2 | Python 3.12、Node 24.19.0、官方 bundled Linux runtime、bubblewrap 0.9.0 |

以上结果不代表其他 Linux 发行版、macOS 或 ARM64 已验收。

## npm 启动器

2026-09-12 已完成双平台本地源码安装验证：

- `init` 分别创建 Windows/Linux 的独立 Python 环境。
- `doctor` 依赖与配置检查通过。
- Node 启动器测试各 2 项通过。
- `scripts/smoke_npm.py`：两个并发客户端通过 Node 入口连接 MCP，
  均发现 `submit_task`、`get_task`、`wait_task`、`continue_task`、`cancel_task`。
- 此轮没有模型调用，没有修改全局 Codex 配置。

Python 分发名暂保留 `codex-deepseek-harness-mcp`，导入名保持 `harness_mcp`，
以兼容现有环境；面向用户的项目及 npm 命令名为 `dsh-in-codex`。

## 核心离线与真实任务验证

本次开源整理后的本地回归：Windows 与 Ubuntu WSL 均为 `40 passed, 1 skipped`，
两侧 Node 测试各 2 项通过。Windows 另外从 `npm pack` 生成的压缩包安装到独立目录，
完成 `init`、`doctor` 与双客户端五工具握手；复用了本机已有的 Python 依赖环境，
不将此结果描述为全新机器验收。发布包仅包含白名单文件，不含密钥和任务记录。

此前双平台核心离线测试均为 `37 passed, 1 skipped`，Ruff 与 `pip check` 通过。
跳过项是目录符号链接逃逸测试：本机 Windows 权限及 WSL 的 NTFS 挂载目录不支持
该测试所需的链接创建。实现仍包含解析路径后的目录边界检查。
开源整理新增的元数据、配置及 README 链接测试单独纳入回归。

离线测试覆盖多进程启动、并发限额、排队、状态持久化、跨窗口控制、超时、
取消进程树、失效 owner 恢复、事件等待和同目录冲突警告。
fake worker 的结果不代表模型实际完成了任务。

Windows 与 WSL 各完成一次修复后的双客户端、双任务真实 Harness 验收：

- 两个首轮任务各通过 Harness Shell 工具执行 3 个 unittest。
- 每轮包含测试数量、`OK`、`HARNESS_TEST_EXIT=0` 的实际工具证据。
- 独立重新运行测试均退出 0。
- 另一客户端通过原 owner 续接一个任务，保持原 session，执行 5 个测试。
- 跨客户端取消 worker 均确认停止。

曾有一轮 8 个任务的首轮修改和独立测试全部通过，但后续跨窗口续接失败；
续接修复后完成了上述双任务全流程。**尚无修复后完整 8 路加续接的单次验收报告。**

## 已修复的问题

- MCP 服务不再使用全局单实例锁；状态与调度保留短临界区锁。
- Windows 不再将单文件 Harness 可执行程序错误当作 Node 启动辅助工具；
  改用官方 Node CLI 与 SDK 公共 `dsh_bin` 接口，未放宽沙箱策略。
- Linux 使用 `/proc/<pid>/stat` 的稳定启动 tick 标识进程，
  避免 WSL 上 epoch 创建时间漂移引起 owner watchdog 误杀。
- `wait_task` 提供有界等待；只读注解不等于客户端自动批准。
- 跨窗口续接由存活的原 owner 派发给原 worker，不伪装为新 worker 恢复 session。

## 验证边界

- 未承诺原 worker 退出后的持久会话恢复，当前官方 SDK profile 不支持该恢复 RPC。
- 未重新验收所有 Codex 客户端版本的交互式审批界面。
- `doctor` 不验证凭证有效性、网络或沙箱实际执行；这些需要单独探针/真实任务。
- WSL 真实模型测试使用直接 HTTPS，不代表 Windows localhost 代理在 WSL 可用。
- npm 包尚未发布；从公共 registry 安装与干净机器验收仍属正式发布前事项。
- GitHub Actions 配置只运行离线测试，不使用模型凭证，不自动发布 npm 包。

复现方法见 [CONTRIBUTING.md](CONTRIBUTING.md)。
