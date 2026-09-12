# dsh-in-codex
Codex 负责规划与验收，DeepSeek Harness 负责代码修改和测试。

非官方社区 MCP 集成，支持 Windows 和 Ubuntu / WSL。采用 [MIT 许可证](LICENSE)。

前置条件：需要已经安装codex。更新：关闭 MCP 后在本仓库执行 `npm run update`（详见 DEPLOYMENT.md）。

## 快速开始

```bash
git clone https://github.com/RichardHu6666/dsh-in-codex.git
cd dsh-in-codex
npm ci
npm run setup
```

默认使用 `workspace-write` Bubblewrap/Landlock 沙箱并 fail closed。受信任的
Jupyter/GPU 容器若被宿主 seccomp 拦截 `unshare(CLONE_NEWUSER)`，可在
`[mcp_servers.dsh-in-codex.env]` 显式设置
`HARNESS_MCP_EXECUTION_BACKEND = "direct"`；该 unsafe 模式不调用 Bubblewrap
或 Landlock，服务不会在沙箱失败时自动降级。

按终端向导选择用户级或项目级配置、配置密钥和注册 MCP，完成后重载或重启 Codex。
无需单独安装 dsh。需要 Node.js 22.19+、Python 3.11+；系统依赖可让 Codex 协助检查。

## 让你的 Codex 帮你部署

直接复制下面整段发给自己的 Codex：

```text
请帮我部署 dsh-in-codex，仓库：
https://github.com/RichardHu6666/dsh-in-codex

目标流程：
git clone https://github.com/RichardHu6666/dsh-in-codex.git
cd dsh-in-codex
npm ci
npm run setup

先确认安装位置与当前 Codex 项目；已有仓库则先检查，不重复克隆或覆盖。
克隆后先阅读 DEPLOYMENT.md 和 SECURITY.md，按当前平台检查环境并处理依赖问题。
系统级安装、全局配置修改前先征求我的确认，不要关闭沙箱或降低审批权限。

setup 是交互式命令，请让我在本机终端完成目录选择、隐藏密钥输入和写入确认。
不要在聊天里索要密钥，不读取或输出已有密钥，也不要把密钥写入命令参数。
如果你无法提供可交互的终端，请给出我需要亲自运行的命令，不要用管道模拟确认。

配置完成后检查 MCP 握手与五个工具：
submit_task、wait_task、get_task、continue_task、cancel_task。
如果当前 Codex 会话还没加载工具，请明确让我重载或重启，不要假装已经调用成功。
握手通过不等于 API Key 有效或 Shell 已可执行；先说明剩余验证项。

得到我对模型费用的确认后，再在独立测试目录做一次最小任务和独立复测。
不要提交、推送、合并或回滚我的项目代码。
```

## 在项目中使用

临时委派，直接对 Codex 说：

> 这个任务由你规划，通过 dsh-in-codex MCP 交给 DeepSeek 修改代码和运行测试。
> 你负责检查实际 diff、独立复测和反馈修复；每次委派都必须把当前项目的绝对路径作为
> `workspace` 传给 MCP。不要从 MCP 安装目录或服务数据目录推断工作目录。

希望整个项目默认这样协作，就让 Codex：

> 按 DEPLOYMENT.md 的“项目默认分工”示例，将规则合并到当前项目的 AGENTS.md，
> 保留原有规则，并检查配套 dsh-in-codex Skill 和 MCP 是否可用。

`AGENTS.md` 约定默认分工，Skill 描述执行流程，MCP 提供实际工具。
用户级 setup 配置一次即可换项目：Codex 每次委派显式传入当前项目的绝对路径。
项目级 setup 才会限定任务目录；两种模式都不会自动继承 Codex 的沙箱权限。
这不是强制路由：工具不可用时应报告问题，不能假装已经委派。

## 说明
配置向导不调用模型；真实任务可能产生 API 费用。
只对可信项目使用：路径检查不是操作系统沙箱。不要上传 `.env` 或 `.runtime`。

- [部署细节与故障排查（给 Codex 阅读）](DEPLOYMENT.md)
- [安全说明](SECURITY.md) · [验证记录](VERIFICATION.md) · [贡献指南](CONTRIBUTING.md)
