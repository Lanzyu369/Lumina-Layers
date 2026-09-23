const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { redact, resourceName, isEntryResource, diagnose } = require('../../scripts/diagnose_packaged_startup.cjs');

test('diagnostics omit query signatures, external URLs and local usernames', () => {
  assert.equal(resourceName('https://private.example/package?signature=secret'), '<external-url>');
  assert.equal(resourceName('http://127.0.0.1:8123/assets/app.js?token=secret'), 'http://127.0.0.1:8123/assets/app.js');
  const clean = redact('Bearer secret-value file:///C:/Users/private/preload.cjs token=secret');
  assert.ok(!clean.includes('secret'));
  assert.ok(!clean.includes('Users/private'));
});

test('only local document and JS/CSS bodies are collected, never APIs or third-party data', () => {
  assert.equal(isEntryResource('http://127.0.0.1:8123/', 'document'), true);
  assert.equal(isEntryResource('http://127.0.0.1:8123/assets/app.js', 'script'), true);
  assert.equal(isEntryResource('http://127.0.0.1:8123/api/settings', 'fetch'), false);
  assert.equal(isEntryResource('https://example.com/a.js', 'script'), false);
  assert.equal(isEntryResource('file:///C:/app.js', 'script'), false);
});

test('invalid runtime budgets fail before filesystem mutation or application launch', async () => {
  await assert.rejects(diagnose({ executable: path.resolve('test.exe'), output: path.resolve('test-output'), seconds: 999 }), /Seconds/);
});
