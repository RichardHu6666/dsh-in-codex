# dsh-in-codex

Codex 负责规划与验收，DeepSeek Harness 负责代码修改和测试。

非官方社区 MCP 集成，支持 Windows 和 Ubuntu / WSL。采用 [MIT 许可证](LICENSE)。

前置条件：需要已经安装codex

## 快速开始

```bash
git clone https://github.com/RichardHu6666/dsh-in-codex.git
cd dsh-in-codex
npm ci
npm run setup
```

按终端向导选择任务目录、配置密钥和注册 MCP，完成后重载或重启 Codex。
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

先确认安装位置与允许 Harness 操作的任务目录；已有仓库则先检查，不重复克隆或覆盖。
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

## 说明

配置向导不调用模型；真实任务可能产生 API 费用。
只对可信项目使用：路径检查不是操作系统沙箱。不要上传 `.env` 或 `.runtime`。

- [部署细节与故障排查（给 Codex 阅读）](DEPLOYMENT.md)
- [安全说明](SECURITY.md) · [验证记录](VERIFICATION.md) · [贡献指南](CONTRIBUTING.md)
