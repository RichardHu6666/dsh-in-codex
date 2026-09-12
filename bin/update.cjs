'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function run(exe, args, options = {}) {
  const result = spawnSync(exe, args, { stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${path.basename(exe)} failed (${result.status}); update stopped.`);
  return result;
}

function options(argv, env = process.env) {
  const root = path.join(path.resolve(env.CODEX_HOME || path.join(os.homedir(), '.codex')),
    'dsh-in-codex', process.platform);
  if (!argv.length) return { root, scope: 'user' };
  if (argv.length !== 2 || argv[0] !== '--root' || !path.isAbsolute(argv[1])) {
    throw new Error('Usage: npm run update [-- --root ABSOLUTE_PROJECT_DIRECTORY]');
  }
  return { root: argv[1], scope: 'project' };
}

function update(argv = process.argv.slice(2), execute = run) {
  const request = options(argv);
  const repo = path.resolve(__dirname, '..');
  const capture = { cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] };
  const top = execute('git', ['rev-parse', '--show-toplevel'], capture).stdout.trim();
  if (fs.realpathSync(top) !== fs.realpathSync(repo)) throw new Error('Update requires a standalone Git clone.');
  if (execute('git', ['status', '--porcelain'], capture).stdout.trim()) {
    throw new Error('Repository has local changes; commit or resolve them yourself before update.');
  }
  const cli = require('./cli.cjs');
  const dirs = cli.layout(request.root);
  if (!fs.existsSync(dirs.ready)) throw new Error('No installed environment; run npm run setup first.');
  const payload = JSON.stringify({ ...request, launcher: path.join(repo, 'bin/cli.cjs') });
  execute(dirs.executable, ['-c',
    'import sys; sys.path.insert(0,sys.argv[1]); from harness_mcp.update_check import main; sys.exit(main())',
    path.join(repo, 'src')], {
    cwd: repo, input: payload, encoding: 'utf8', stdio: ['pipe', 'inherit', 'inherit'],
  });
  execute('git', ['pull', '--ff-only'], { cwd: repo });
  // npm runs this script with the portable JS entrypoint in npm_execpath.
  const npm = process.env.npm_execpath;
  if (!npm || !fs.existsSync(npm)) throw new Error('Use npm run update to locate the npm executable.');
  execute(process.execPath, [npm, 'ci'], { cwd: repo });
  execute(process.execPath, [path.join(repo, 'bin/cli.cjs'), 'init', '--root', request.root], { cwd: repo });
  // Reload layout after pulling: the package version may now be different.
  execute(process.execPath, ['-e',
    'const c=require("./bin/cli.cjs");const s=require("./bin/setup.cjs");' +
    'const r=JSON.parse(process.argv[1]);s.backend(c.layout(r.root).executable,"verify",r);',
    payload], { cwd: repo });
  console.log('Update verified: five MCP tools. Restart Codex. Credentials, configuration, skills and task records were not rewritten.');
}

module.exports = { options, update };
if (require.main === module) {
  try { update(); } catch (error) {
    console.error(`dsh-in-codex update: ${error.message}`);
    process.exitCode = 1;
  }
}
