const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { parse } = require('../bin/cli.cjs');

test('setup is an explicit command', () => {
  assert.equal(parse(['setup'], {}).command, 'setup');
});

test('noninteractive setup cannot prompt or change configuration', () => {
  const result = spawnSync(process.execPath, ['bin/cli.cjs', 'setup'], { encoding: 'utf8' });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /交互式终端/);
});
