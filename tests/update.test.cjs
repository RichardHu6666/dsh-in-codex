const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { options, update } = require('../bin/update.cjs');

test('update defaults to user data, explicit root selects project', () => {
  const home = path.resolve('test-home');
  assert.equal(options([], { CODEX_HOME: home }).root,
    path.join(home, 'dsh-in-codex', process.platform));
  assert.equal(options(['--root', home]).scope, 'project');
  assert.throws(() => options(['--root', 'relative']));
});

test('dirty clone stops before pull, install or configuration writes', () => {
  const calls = [];
  assert.throws(() => update([], (exe, args) => {
    calls.push(args);
    return { stdout: args[0] === 'rev-parse' ? path.resolve(__dirname, '..') : ' M README.md' };
  }), /local changes/);
  assert.equal(calls.length, 2);
});
