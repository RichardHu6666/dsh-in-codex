#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { createRequire } = require('node:module');
const packageRoot = path.resolve(__dirname, '..');
const version = require('../package.json').version;

function parse(argv, env = process.env) {
  const command = argv[0] || 'help';
  if (!['init', 'serve', 'doctor', 'help', '--help', '--version'].includes(command)) {
    throw new Error(`Unknown command: ${command}`);
  }
  let root = env.HARNESS_MCP_ROOT;
  let python = env.DSH_IN_CODEX_PYTHON;
  for (let i = 1; i < argv.length; i += 2) {
    if (!['--root', '--python'].includes(argv[i]) || !argv[i + 1]) {
      throw new Error('Expected --root DIRECTORY or --python EXECUTABLE');
    }
    if (argv[i] === '--root') root = argv[i + 1];
    else python = argv[i + 1];
  }
  return { command, root, python };
}

function layout(raw) {
  if (!raw || !path.isAbsolute(raw)) throw new Error('Set --root to an existing absolute project directory');
  const root = fs.realpathSync(raw);
  if (!fs.statSync(root).isDirectory()) throw new Error('Project root must be a directory');
  const runtime = path.join(root, '.runtime');
  const envDir = path.join(runtime, `npm-python-${process.platform}-${process.arch}-${version}`);
  // Reject redirected internal paths before writing or executing anything there.
  for (const target of [runtime, envDir]) {
    if (fs.existsSync(target) && fs.realpathSync(target) !== target) {
      throw new Error(`Redirected runtime directory is not supported: ${target}`);
    }
  }
  return {
    root, runtime, envDir,
    executable: path.join(envDir, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'),
    ready: path.join(envDir, '.dsh-in-codex-ready'),
  };
}

function run(exe, args, options = {}) {
  const result = spawnSync(exe, args, { stdio: ['ignore', 2, 2], ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${path.basename(exe)} failed (exit ${result.status})`);
  return result;
}

function findPython(explicit) {
  const candidates = explicit ? [[explicit]] : process.platform === 'win32'
    ? [['py', '-3'], ['python'], ['python3']] : [['python3'], ['python']];
  for (const [exe, ...prefix] of candidates) {
    const result = spawnSync(exe, [...prefix, '-c',
      'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'], { stdio: 'ignore' });
    if (!result.error && result.status === 0) return [exe, prefix];
  }
  throw new Error('Python 3.11+ is required. Install it or pass --python /path/to/python');
}

function runtimeRoot() {
  // Resolve from this package, including npm's hoisted dependency layout.
  const req = createRequire(path.join(packageRoot, 'package.json'));
  for (const parent of req.resolve.paths('@deepseek-ai/dsh') || []) {
    if (fs.existsSync(path.join(parent, '@deepseek-ai/dsh/lib/bin.js'))) return path.dirname(parent);
  }
  throw new Error('Official Harness npm runtime is missing; reinstall dsh-in-codex');
}

async function main(argv = process.argv.slice(2)) {
  const options = parse(argv);
  if (options.command === '--version') return console.log(version);
  if (['help', '--help'].includes(options.command)) {
    return console.log('dsh-in-codex <init|doctor|serve> --root ABSOLUTE_DIRECTORY [--python EXECUTABLE]\nRequires Node >=22.19 and Python >=3.11. Set DEEPSEEK_API_KEY in the client environment or project .env.\ninit installs dependencies; doctor does not call the model; serve uses STDIO.');
  }
  const dirs = layout(options.root);
  if (options.command === 'init') {
    const [python, prefix] = findPython(options.python);
    const venvCheck = spawnSync(python, [...prefix, '-c', 'import venv, ensurepip'], { stdio: 'ignore' });
    if (venvCheck.error || venvCheck.status !== 0) {
      throw new Error('Python venv/ensurepip is missing. On Ubuntu install python3-venv, then retry init.');
    }
    fs.mkdirSync(dirs.runtime, { recursive: true });
    const lock = path.join(dirs.runtime, 'npm-init.lock');
    let fd;
    try {
      fd = fs.openSync(lock, 'wx');
    } catch (error) {
      if (error.code === 'EEXIST') throw new Error(`Another init may be running. If it crashed, remove ${lock} after checking.`);
      throw error;
    }
    try {
      fs.rmSync(dirs.ready, { force: true });
      run(python, [...prefix, '-m', 'venv', dirs.envDir]);
      run(dirs.executable, ['-m', 'pip', 'install', '--disable-pip-version-check', packageRoot]);
      fs.writeFileSync(dirs.ready, version, { mode: 0o600 });
    } finally {
      fs.closeSync(fd);
      fs.unlinkSync(lock);
    }
    console.error(`Initialized ${dirs.envDir}\nSet DEEPSEEK_API_KEY, then run doctor. No global client configuration was changed.`);
    return;
  }
  if (!fs.existsSync(dirs.ready) || !fs.existsSync(dirs.executable)) {
    throw new Error('Environment is not initialized. Run dsh-in-codex init with the same --root first.');
  }
  const env = { ...process.env, HARNESS_MCP_ROOT: dirs.root,
    HARNESS_MCP_NODE_ROOT: runtimeRoot(), PYTHONUTF8: '1', PYTHONUNBUFFERED: '1' };
  if (options.command === 'doctor') {
    run(dirs.executable, ['-m', 'pip', 'check'], { env });
    run(dirs.executable, ['-c',
      'from harness_mcp.config import Settings; from harness_mcp.runtime import sdk_runtime_options; import os; Settings.from_env(); sdk_runtime_options(); print("API key configured:", bool(os.environ.get("DEEPSEEK_API_KEY"))); print("Python/MCP configuration: OK")'], { env });
    if (process.platform === 'linux') run('bwrap', ['--version']);
    console.error('Local dependency checks passed. Network, sandbox execution and model calls were not tested.');
    return;
  }
  const child = spawn(dirs.executable, ['-m', 'harness_mcp.server'], {
    cwd: dirs.root, env, stdio: 'inherit',
  });
  const handlers = ['SIGINT', 'SIGTERM'].map(signal => {
    const handler = () => child.kill(signal);
    process.on(signal, handler);
    return [signal, handler];
  });
  await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code, signal) => {
      process.exitCode = code ?? (signal ? 1 : 0);
      resolve();
    });
  }).finally(() => handlers.forEach(([signal, handler]) => process.off(signal, handler)));
}

module.exports = { parse, layout, findPython };
if (require.main === module) main().catch(error => {
  console.error(`dsh-in-codex: ${error.message}`);
  process.exitCode = 1;
});
