# 部署参考：供 Codex 查阅

普通用户请先阅读 [README.md](README.md)。本文保留详细的部署、配置和故障排查资料，
供协助安装的 Codex 按需查阅。不要在未确认目标目录和写入范围前执行安装或注册。

## 给部署代理的执行清单

1. 先确认工具安装目录、当前 Codex 项目，以及在哪个系统运行 Codex。
   不要把 WSL 的路径写进 Windows 客户端配置，也不要混用两侧的 Python 环境。
2. 检查 Git、Node/npm、Python 与平台依赖。已有克隆先检查 remote、版本和未提交修改，
   不重复克隆、不自动覆盖。系统级依赖安装需获得用户确认。
3. 在工具目录执行 `npm ci`，然后在用户可操作的终端执行 `npm run setup`。
   这是 TTY 交互命令，不能用 `echo`、管道或预填答案绕过确认。
4. 密钥由用户在本机隐藏输入。不要读取 `.env` 内容、输出环境变量中的密钥，
   也不要把真实密钥写进工具参数、脚本或聊天。只检查凭证是否已配置。
5. 用户确认项目级或用户级注册后由向导合并配置，不额外改写审批策略。
   无法提供可操作终端时，暂停在此处，告诉用户进入哪个目录执行什么命令。
6. 根据向导结果检查实际 MCP 握手与五工具发现。当前对话尚未加载新 MCP 时，
   明确要求重载或重启；不要用配置文件存在或进程启动代替工具发现证据。
7. 向用户报告任务根目录、配置范围、已验证项目和剩余项。
   API 有效性、Harness Shell 执行和真实任务须另行验证，模型费用要先确认。

遇到失败时，优先查阅本文的“常见问题”和 [SECURITY.md](SECURITY.md)。
保留错误类型与脱敏后的信息，不上传整个 `.runtime`。不自动提交或回滚用户的任务仓库。
Codex CLI 不是 MCP 服务安装本身的依赖；最终使用需要可接入 MCP 的 Codex 客户端。

让 Codex 负责规划与验收，让 DeepSeek Harness 负责具体的代码修改与测试。

这是一个基于 STDIO 的任务级 MCP Server：通过官方 DeepSeek Harness Python SDK
启动 Harness 的 `sdk` profile，对外提供提交、等待、查询、续接和取消任务的接口。
它不是 TUI 自动化，也不是直接调用模型 API 的简化替代品。

**非官方社区项目，与 OpenAI、DeepSeek 无隶属关系。采用 [MIT 许可证](LICENSE)。**

## 项目默认分工

仅针对一次任务时，在对话中明确要求使用 dsh-in-codex MCP 即可。
若希望当前项目的代码实现默认交给 DeepSeek，将下面规则合并到**任务项目根目录**
的 `AGENTS.md`，不是工具安装目录。保留已有内容；存在冲突时先与用户确认。
不要默认写入用户主目录的全局 `AGENTS.md`，避免影响所有无关项目。

```markdown
## Codex 与 DeepSeek Harness 分工

- 除非用户另有要求，本项目的代码实现、测试编写和首轮测试默认委派给
  dsh-in-codex MCP；Codex 负责需求澄清、代码阅读、任务拆分、审查和独立验收。
- 优先遵循 dsh-in-codex Skill。提交任务必须附带工作目录、
  目标、允许修改的文件范围、约束和可验证的验收标准。
- 委派前确认 MCP 可用且当前项目路径明确。用户级动态模式要求传入项目的绝对路径；
  项目级固定模式要求路径位于 `HARNESS_MCP_ROOT` 内。不得为了执行任务扩大
  项目级允许目录、降低审批或关闭沙箱。缺失工具、凭证或权限时报告阻塞，不静默改为自己实现。
- 独立子任务可以并行；保存任务 ID，不对同一文件进行未经协调的并行写入。
- 使用 wait_task 等待事件；completed 不代表测试通过。检查实际 diff，并独立复测。
- 需要修复时优先 continue_task 续接存活的原 session；原 worker 已退出时，
  先检查残留修改，再提交新的有界任务，不声称恢复了旧会话。
- 验收后 cancel_task 清理空闲 worker，检查 stopped_confirmed；取消不回滚代码。
- 遵守用户对 API 费用和任务范围的授权。不自动提交、推送、合并或回滚。
```

向导可安装项目级 Skill，但**不会自动修改 `AGENTS.md`**，因为这会改变项目默认工作方式。
规则写入后，在该项目开启新 Codex 会话确认生效；它是协作指令，不是 MCP 层的强制路由。
用户在具体任务中明确指定其他方式时，按该任务要求处理。

全局 setup 使用动态工作目录：每次提交必须传入当前 Codex 项目的绝对路径，
不使用 MCP 进程 CWD 推测项目。换项目无需重新配置；续接仍绑定原任务目录。
全局凭证、依赖与记录存放在 `CODEX_HOME/dsh-in-codex/<平台>`，
未设置 CODEX_HOME 时使用用户主目录下的 `.codex`。Skill 安装到用户级 skills。
项目级 setup 保留固定目录限制。不要把“跟随项目”理解为继承 Codex 的沙箱或审批权限。

从旧全局固定目录配置升级：关闭旧 MCP，运行新版 `npm run setup` 并选择用户配置，
由用户重新提供或通过环境变量配置密钥；不自动读取、迁移旧项目的 `.env`。
原项目配置可能覆盖全局同名服务，先检查该项目 `.codex/config.toml`，确认后再处理旧条目。
旧任务记录不自动迁移，仍保留在原目录。

## 当前状态

- npm 负责命令入口和 Harness Node 依赖，Python 负责 MCP 与任务生命周期。
- Windows 与 Ubuntu 24.04 WSL 已做本地验证；其他 Linux 发行版、macOS、ARM64 尚未验收。
- **尚未发布 npm 包**。当前请从本仓库安装，不要从公共 registry 下载未经确认的同名包。
- 需要 Node.js、Python 和有效的 DeepSeek API 凭证，并非“只装 Node 即可运行”。
- 支持多个 MCP 客户端进程共享同一项目的任务记录，默认最多同时执行 8 个任务。

验证范围与未完成事项见 [VERIFICATION.md](VERIFICATION.md)。

## 工作方式

```text
Codex：拆分任务、指定边界与验收标准
  |
  | MCP / STDIO
  v
dsh-in-codex：任务记录、排队、进程管理、事件等待
  |
  | 官方 Python SDK
  v
DeepSeek Harness：读取代码、修改文件、执行测试
  |
  v
Codex：检查实际 diff、独立复测、提出修复反馈
```

本项目不实现第二套规划器，也不负责自动提交、推送或合并代码。
它不是 Codex 原生 sub-agent；其他支持 STDIO 的 MCP 客户端也可以按同一协议接入。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| Node.js | 22.19 或以上，使用 npm |
| Python | 3.11 或以上，包含 `venv`、`ensurepip` / pip |
| Windows | 执行 Harness Shell 工具需要 PowerShell 7，`pwsh` 可从 PATH 找到 |
| Ubuntu | 安装 `python3-venv`、`bubblewrap`；系统须允许 Harness 使用沙箱后端 |
| 网络 | 安装时能访问 npm 与 Python 包源；执行时能访问模型服务 |
| 凭证 | 有效的 `DEEPSEEK_API_KEY`，模型调用可能产生费用 |

Ubuntu 可先安装系统依赖：

```bash
sudo apt-get update
sudo apt-get install -y python3-venv bubblewrap
```

容器或受限服务器中，仅安装 bubblewrap 不代表沙箱可用。请验证系统权限，
不要通过禁用安全机制来绕过 Harness 启动失败。

## 快速开始

### 1. 安装工具

以下命令在 Windows PowerShell、Linux Shell 中均可使用：

```sh
git clone https://github.com/RichardHu6666/dsh-in-codex.git
cd dsh-in-codex
npm ci
npm run setup
```

`setup` 是推荐的首次配置入口。它会依次引导：

1. 用户级配置选择用户数据目录，项目级配置才选择固定任务目录；同时检查 Python 和平台依赖。
2. 选择项目级或用户级 Codex 注册，确认安装独立 Python 环境。
3. 隐藏输入 API Key，或保留现有环境变量/本地密钥。
4. 选择是否安装配套 Skill，展示写入范围并再次确认。
5. 合并 `.env`、`.gitignore` 与 Codex TOML，备份原文件后写入。
6. 实际启动注册的 MCP 命令，验证五个工具可被发现；不调用模型。

密钥保存在任务项目的 `.env`，不会写入 Codex 配置。原生 Linux 使用 `0600`，
Windows 使用当前用户 ACL；WSL 的 Windows 挂载盘若不支持 POSIX 权限，
会尝试 Windows ACL，并说明它不提供 Linux 多用户隔离。无法设置私密权限时停止写入。
已有配置发生变化、`.env` 被 Git 跟踪或格式不合法时，也会停止而非覆盖。
备份在 `.runtime/setup-backups/`，包含原文件内容，应作为敏感文件保管。

选择用户级注册时，使用 `CODEX_HOME/config.toml`（未设置时为用户主目录的
`.codex/config.toml`）；项目级注册写入任务目录的 `.codex/config.toml`。
其他 MCP 与原有审批设置保持不变。完成后重载或重启 Codex，
项目级配置仍需要信任项目；向导不会绕过客户端信任或审批机制。

按 Ctrl+C 可取消。最终确认前不会修改凭证和 Codex 配置，但已经安装的依赖会保留。
下面的 `init`、`doctor` 和手工配置步骤用于非交互部署，运行向导成功后无须重复执行。

需要区分两个目录：

- **工具目录**：本仓库的克隆位置，存放启动器和 npm 依赖。
- **任务根目录**：你允许 Harness 修改代码的项目，由 `--root` 指定，必须已经存在且为绝对路径。

二者可以相同，也可以不同。不要将整个用户主目录或磁盘根目录设为任务根目录。

### 2. 固定项目模式的非交互初始化（可选）

仍在工具目录执行。请将示例路径替换为自己的项目：

Windows：

```powershell
npm exec --offline -- dsh-in-codex init --root "C:\projects\my-app"
```

Ubuntu：

```bash
npm exec --offline -- dsh-in-codex init --root /home/you/projects/my-app
```

这里的 `--offline` 限制 npm 查找命令，不会使首次 Python 依赖安装离线。
`init` 在任务根目录的 `.runtime/npm-python-<平台>-<架构>-<版本>` 中创建独立环境，
不安装到系统 Python，也不修改全局 Codex 配置。

如果 Python 不在 PATH 中，可追加：

```powershell
npm exec --offline -- dsh-in-codex init --root "C:\projects\my-app" --python "C:\Python313\python.exe"
```

首次安装需要下载 runtime，可能较慢。服务运行期间不要对同一项目执行 `init`。

### 3. 配置凭证

推荐由启动 MCP 客户端的环境提供 `DEEPSEEK_API_KEY`。也可以在**任务根目录**
创建 `.env`，参考本仓库的 [.env.example](.env.example)，仅在本地填写密钥。
请为你自己的任务仓库添加以下 Git 忽略规则：

```gitignore
.env
.runtime/
```

环境变量优先于 `.env`。程序只从 `.env` 加载 `DEEPSEEK_API_KEY` 与
`DEEPSEEK_BASE_URL`，不会导入个人 `~/.dsh` 配置。
不要把密钥填入源码、MCP 配置示例、聊天或 Issue；`.env` 仍是明文文件。

### 4. 检查安装

```powershell
npm exec --offline -- dsh-in-codex doctor --root "C:\projects\my-app"
```

Linux 替换为对应的绝对路径。正常输出包括依赖检查通过和
`API key configured: True`。若显示 `False`，需要先配置凭证。

`doctor` **不调用模型**，也不验证 API Key 的有效性、网络连通性或沙箱实际执行能力。
`serve` 只启动服务，不在 MCP 握手阶段安装依赖或弹出交互式配置。

## 接入 Codex

按 [Codex 官方 MCP 文档](https://developers.openai.com/codex/mcp) 将配置加入客户端。
项目级配置需要客户端信任该项目；修改后重新加载 MCP 或重启客户端。
请合并配置，不要覆盖已有的其他 MCP 配置。

推荐让客户端直接启动已安装的 Node 入口，避免每次握手时触发包下载。
下面是 Windows 示例，**两处目录都需要替换**：

```toml
[mcp_servers.deepseek_harness]
command = "node"
args = ["C:/tools/dsh-in-codex/bin/cli.cjs", "serve", "--root", "C:/projects/my-app"]
env_vars = ["DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"]
startup_timeout_sec = 60
tool_timeout_sec = 70
```

若桌面客户端找不到 `node`，将 `command` 改为 Node 可执行文件的绝对路径。
Linux 示例见 [examples/codex-linux.toml](examples/codex-linux.toml)，
Windows 示例见 [examples/codex-windows.toml](examples/codex-windows.toml)。
配置中的服务键暂时保留为 `deepseek_harness`，这是 Codex 的内部兼容标识；
用户侧项目名称、启动命令和使用方式统一称为 `dsh-in-codex`。

可将 [.agents/skills/delegate-deepseek-harness](.agents/skills/delegate-deepseek-harness)
复制到你的任务项目的 `.agents/skills/`，让 Codex 使用任务委派与独立验收规则。
Skill 不是服务启动的必要条件。

首次对话可以这样验证：

> 检查 dsh-in-codex MCP 的五个工具是否可用，先不要调用模型。
> 然后告诉我允许的任务目录与预期测试流程，等待我确认后再提交任务。

确认后，在当前项目内准备一个独立的测试子目录，再让 Codex：

> 将这个测试目录内的加法函数与 unittest 编写任务交给 Harness。
> 使用 submit_task，然后用 wait_task 等待；完成后独立检查文件并运行测试。
> 不修改其他目录，不提交 Git。最后确认取消并清理 worker。

只读工具有只读/幂等注解，但是否需要审批由客户端决定；
本项目不会自动调整全局审批权限，也不保证任意客户端免审批。

## 五个 MCP 工具

| 工具 | 主要参数 | 用途 |
| --- | --- | --- |
| `submit_task` | `workspace`、`instruction`、`acceptance` 列表 | 创建任务，立即返回任务 ID |
| `get_task` | `task_id`、`cursor`、`limit` | 查询状态、回复与分页事件 |
| `wait_task` | `task_id`、`cursor`、`limit`、`timeout_sec` | 等待新事件或终态，默认 30 秒、最多 60 秒 |
| `continue_task` | `task_id`、`feedback` | 向仍然存活的原 session 追加反馈 |
| `cancel_task` | `task_id` | 停止对应 worker，检查 `stopped_confirmed` |

典型流程：

```text
submit_task -> wait_task -> 检查事件、diff 与测试
                         -> continue_task -> wait_task -> 独立复测
                         -> cancel_task
```

- 用返回的 `next_cursor` 增量读取，`has_more` 为真时继续取完事件。
- `wait_reason=timeout` 表示本次等待到期，不代表任务失败；仍需再次等待。
- 没有异步推送到聊天的保证，由客户端继续调用 `wait_task` 获取进展。
- `completed` 只表示 Harness 一轮结束，不表示测试通过；必须独立验收。
- 原 worker 或所属 MCP 进程退出后，**不能仅凭持久化 session ID 恢复会话**。
  此时先检查部分修改，再提交新的任务。
- 取消不会回滚代码；已完成任务仍可能保留空闲 worker，验收后应清理。

## 并行与生命周期

每个任务有独立 worker、session ID 和 `DSH_HOME`。
同一用户数据目录下的多个 MCP 进程共享调度状态，默认执行并发上限为 8。
用户级动态模式下，多个项目共享这一并发上限；项目级固定模式的服务实例也按其数据目录共享。

多个客户端可查询或取消同一个任务。原 owner 存活时，跨窗口续接请求会由原 owner
派发给原 worker。关闭客户端连接时，该 MCP 所属任务被停止，不影响其他 MCP 的任务。
这不是常驻后台服务，不支持关闭所有客户端后仍继续执行任务。

允许多个任务使用相同目录，但会返回冲突警告。服务不会解决文件覆盖或测试干扰，
请优先使用不同目录或自行准备 Git worktree。
不要让 Windows 与 WSL 同时操作同一份活动 `.runtime`。

状态包括 `queued`、`running`、`completed`、`failed`、`timed_out`、
`cancelling`、`cancelled`、`interrupted`、`stop_failed`。
出现 `stop_failed` 时先处理遗留进程，不要继续提交写入任务。

## 配置项

| 环境变量 | 默认值 / 含义 |
| --- | --- |
| `HARNESS_MCP_ROOT` | 服务数据目录；固定模式下同时限制任务目录，启动器 `--root` 优先 |
| `HARNESS_MCP_WORKSPACE_MODE` | `fixed` 默认；用户级 setup 自动设置 `dynamic`，要求显式绝对任务路径 |
| `DSH_IN_CODEX_PYTHON` | 初始化时的 Python 路径，亦可用 `--python` 指定 |
| `DEEPSEEK_API_KEY` | 模型凭证 |
| `DEEPSEEK_BASE_URL` | 可选服务地址，须与 Harness provider 兼容 |
| `HARNESS_MCP_MODEL` | `deepseek-v4-flash`，可按账户可用模型调整 |
| `HARNESS_MCP_MAX_CONCURRENCY` | `8`，范围 `1..64`，同根目录各客户端应配置一致 |
| `HARNESS_MCP_TIMEOUT` | 单轮超时，默认 `1800` 秒，范围 `1..86400` |
| `HARNESS_MCP_RUNTIME` | Windows 默认 `node`，Linux 默认 `bundled` |
| `HARNESS_MCP_NODE_ROOT` | 底层 Node runtime 位置；npm 启动器自动设置，无须手工配置 |

除两个 provider 变量外，其他配置通过客户端进程环境或 MCP 的 `env` 表提供，
不要放入 `.env` 后期待自动生效。

## 升级与迁移

1. 停止相关 MCP 客户端，确认任务已结束并检查未提交修改。
2. 更新工具源码，执行 `npm ci`。
3. 对每个任务根目录运行 `npm run setup`，或非交互运行 `init` 后再运行 `doctor`。
4. 若安装路径改变，更新客户端配置，再启动 MCP。

迁移到另一台机器时重新安装依赖，不复制 `.venv`、`node_modules` 或
`.runtime/npm-python-*`。凭证单独配置。历史记录可作为敏感审计资料保留，
但不承诺跨机器恢复正在运行的任务或 Harness 会话；新部署推荐使用新的 `.runtime`。

旧的 `scripts/start_codex.py` / `.ps1` 专用启动链已移除，请迁移到向导注册后正常启动
Codex。旧脚本中针对个别 Windows 插件的 Git Bash PATH 调整不属于 MCP 功能，
向导不会修改 Codex 插件、Hook 或系统 PATH。

## 常见问题

| 问题 | 检查方向 |
| --- | --- |
| `Environment is not initialized` | `init` 与 `serve` 是否使用同一根目录、同一版本 |
| Python / ensurepip 不存在 | 安装 Python 3.11+；Ubuntu 安装 `python3-venv` |
| 初始化锁残留 | 先确认没有 `init` 进程，再处理错误信息指向的 `npm-init.lock`；不要删除活动任务状态锁 |
| MCP 握手失败 | 单独运行 `doctor`，检查 Node 路径和 stderr；不要把 `init` 配成服务启动命令 |
| Windows Shell 执行失败 | 检查 `pwsh` 与 Node 是否可用，使用项目锁定的 Node runtime |
| npm 提示 `allow-scripts` | 按本机 npm 的提示逐项审查上游安装脚本，不要全局放开所有脚本；握手成功不等于 Shell 已可执行 |
| Linux Shell 执行失败 | 检查 bubblewrap、内核权限和 Harness 的报错，不要关闭沙箱绕过 |
| 等待工具卡在审批 | 检查客户端工具审批策略；服务不能代替客户端批准工具 |
| 窗口关闭后无法续接 | 当前 SDK 会话只支持原 worker 存活期间续接，需检查修改后重新提交 |

代理通过进程环境传入。WSL NAT 模式下，WSL 的 `127.0.0.1` 不等于 Windows
的回环地址；需使用 WSL 可达的代理地址或适当网络配置，不要默认两侧共享 localhost。
本地曾通过直接 HTTPS 完成 WSL 验收。

## 安全与费用

工作目录检查**不是操作系统级安全隔离**。Harness 运行在当前用户权限下，
可以调用 Shell；不要用于不可信代码仓库，也不要将这个 STDIO 服务公开到网络。
只读工具注解不改变 Harness 写入工具的权限边界。

`.runtime` 可能含源码片段、提示词、Shell 输出及 SDK 历史。即使日志做了部分脱敏，
也不保证清除所有变形密钥。不要整体上传日志目录，提交 Issue 前先脱敏。
更多说明见 [SECURITY.md](SECURITY.md)。

真实任务会调用模型并可能计费；超时和修复轮数不等于金额上限。
`doctor`、离线单元测试和默认握手探针不调用模型。

## 开发与验证

见 [CONTRIBUTING.md](CONTRIBUTING.md)。目录结构：

```text
bin/                  npm 命令入口
src/harness_mcp/      MCP、任务存储、调度和 Harness 进程管理
tests/                离线测试与 fake worker
scripts/              SDK 探针、MCP 握手与显式付费验收脚本
examples/             客户端配置、测试夹具
.agents/skills/       Codex 委派规则
```

## 许可证与上游

本项目代码采用 [MIT](LICENSE)；依赖软件遵循各自的许可证，
本许可证不授予 DeepSeek API 服务使用权，也不改变其计费或服务条款。

- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
- [Codex MCP 文档](https://developers.openai.com/codex/mcp)
- [Codex Skills 文档](https://developers.openai.com/codex/skills)
- [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
