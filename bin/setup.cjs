'use strict';

const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');

function backend(executable, action, payload) {
  const result = spawnSync(executable, ['-m', 'harness_mcp.onboarding', action], {
    input: JSON.stringify(payload), encoding: 'utf8',
    env: { ...process.env, PYTHONUTF8: '1' }, maxBuffer: 1024 * 1024,
  });
  // Never forward raw child output: it could contain user-provided credentials.
  if (result.error) throw new Error('无法启动配置助手，请检查 Python 环境。');
  let response;
  try { response = JSON.parse(result.stdout); }
  catch { throw new Error('配置助手未返回有效结果，请重新运行 init。'); }
  if (result.status !== 0) throw new Error(response.error || '配置失败；请检查文件权限。');
  return response;
}

async function setup(options, api) {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw new Error('setup 需要交互式终端；自动化部署请使用 init/serve。');
  }
  const { input, password, confirm, select } = await import('@inquirer/prompts');
  try {
    console.log('dsh-in-codex 配置向导\n不会自动调用模型，也不会更改 Codex 审批权限。');
    const scope = await select({
      message: '将 MCP 注册到哪里？',
      choices: [
        { name: '用户配置（推荐；每次任务使用当前 Codex 项目的绝对路径）', value: 'user' },
        { name: '项目配置（仅允许指定项目目录内的任务）', value: 'project' },
      ],
    });
    let root;
    if (scope === 'user') {
      root = path.join(path.resolve(process.env.CODEX_HOME || path.join(os.homedir(), '.codex')),
        'dsh-in-codex', process.platform);
      console.log(`用户数据目录：${root}\n仅存放凭证、依赖和任务记录，不限制任务到这个目录。`);
      if (!await confirm({ message: '确认创建或复用此用户数据目录？', default: true })) return;
      fs.mkdirSync(root, { recursive: true });
      root = api.layout(root).root;
    } else root = api.layout(await input({
      message: '允许 Harness 操作的项目根目录（绝对路径）',
      default: options.root || process.cwd(),
      validate: value => {
        try {
          const dirs = api.layout(value);
          return dirs.root !== path.parse(dirs.root).root || '不能使用磁盘根目录';
        } catch { return '请输入已存在的绝对目录'; }
      },
    })).root;
    const [python] = api.findPython(options.python);
    api.run(process.platform === 'win32' ? 'pwsh' : 'bwrap',
      [process.platform === 'win32' ? '--version' : '--version']);
    if (!await confirm({
      message: `为 ${root} 安装或更新独立 Python 环境？需要联网，已运行的 MCP 必须先关闭。`,
      default: true,
    })) return console.log('已取消，未修改凭证或 Codex 配置。');
    await api.main(['init', '--root', root, ...(options.python ? ['--python', options.python] : [])]);
    const executable = api.layout(root).executable;
    const request = { root, scope, node: process.execPath, launcher: path.join(api.packageRoot, 'bin/cli.cjs') };
    const info = backend(executable, 'inspect', request);
    console.log(`Python：${python}\n配置文件：${info.config_path}`);
    if (info.env_tracked) throw new Error('.env 已被 Git 跟踪。请先自行处理跟踪及密钥泄露风险，再重新配置。');
    let key;
    if (info.environment_key) {
      const save = await confirm({ message: `检测到环境变量密钥，是否同时保存到 ${root}/.env？（明文、受限权限）`, default: false });
      if (save) key = process.env.DEEPSEEK_API_KEY;
    } else if (!info.local_key || await confirm({ message: '已存在本地密钥，是否更换？', default: false })) {
      key = await password({
        message: `DeepSeek API Key（隐藏输入，将保存到 ${root}/.env）`,
        mask: '*',
        validate: value => value.trim().length > 0 && !/[\r\n\0]/.test(value) || '密钥不能为空或包含换行',
      });
    }
    const skill = await confirm({ message: `安装${scope === 'user' ? '用户级' : '项目级'} Codex Skill？已有不同内容时会备份替换。`, default: true });
    console.log(`将合并 ${root}/.gitignore，${key ? '更新' : '保留'} .env，${info.existing_mcp ? '更新已有' : '新增'} deepseek_harness 配置。`);
    console.log('其他 MCP 配置不变。修改前备份保存在任务目录 .runtime/setup-backups。');
    if (!await confirm({ message: '确认写入以上配置？', default: false })) {
      key = undefined;
      return console.log('已取消；仅保留安装好的 Python 环境，未修改凭证或 Codex 配置。');
    }
    const result = backend(executable, 'apply', { ...request, revision: info.revision, key, skill });
    key = undefined;
    if (process.platform !== 'win32' && result.credential_protection === 'windows-acl') {
      console.log('挂载盘使用 Windows ACL 保护凭证，不提供 Linux 多用户权限隔离。');
    }
    console.log(`配置已写入；变更文件：${result.changed}。正在验证注册的启动命令……`);
    const verified = backend(executable, 'verify', request);
    console.log(`MCP 握手成功，发现 ${verified.tools.length} 个工具。未验证密钥有效性，未调用模型。`);
    console.log('在 Codex 中重新加载 MCP 或重启客户端；项目级配置需信任任务项目。');
    console.log(scope === 'user'
      ? '全局配置完成。进入任意项目使用 Codex；每次委派须传入该项目的绝对路径。'
      : `任务目录：${root}\n若 Codex CLI 已安装，可进入该目录执行 codex。`);
  } catch (error) {
    if (error.name === 'ExitPromptError' || error.name === 'AbortPromptError') {
      console.log('\n已取消；已完成的依赖安装不会回滚。');
      return;
    }
    throw error;
  }
}

module.exports = { setup, backend };
