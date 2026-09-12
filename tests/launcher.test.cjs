const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { parse, layout } = require('../bin/cli.cjs');

test('arguments and environment defaults', () => {
  assert.equal(parse(['serve'], { HARNESS_MCP_ROOT: '/project' }).root, '/project');
  assert.equal(parse(['init', '--root', '/explicit'], {}).root, '/explicit');
  assert.throws(() => parse(['unknown'], {}));
  assert.throws(() => parse(['serve', '--root'], {}));
  assert.throws(() => layout('relative'));
});

test('help and errors never start an MCP server', () => {
  const help = spawnSync(process.execPath, ['bin/cli.cjs', '--help'], { encoding: 'utf8' });
  assert.equal(help.status, 0);
  assert.match(help.stdout, /Python >=3.11/);
  const error = spawnSync(process.execPath, ['bin/cli.cjs', 'serve', '--root', 'relative'], { encoding: 'utf8' });
  assert.equal(error.status, 1);
  assert.equal(error.stdout, '');
  assert.match(error.stderr, /absolute project directory/);
});
