'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { REQUIRED_WORKFLOWS, publishSourceNightly } = require('./source-nightly.cjs');
const sha = 'a'.repeat(40);
const repository = 'lumina-layer-studio/Lumina-Layers';

function fixture() {
  const state = {
    head: sha,
    reads: [],
    writes: [],
    release: null,
    tag: null,
    runs: Object.fromEntries(REQUIRED_WORKFLOWS.map((file) => [file, [{
      id: 10, head_sha: sha, head_branch: 'main', event: 'push',
      status: 'completed', conclusion: 'success', html_url: `https://github.com/check/${file}`,
    }]])),
  };
  const event = { workflow_run: {
    event: 'push', head_branch: 'main', head_sha: sha,
    head_repository: { full_name: repository }, status: 'completed', conclusion: 'success',
    path: '.github/workflows/native-svg-core.yml',
  } };
  const request = async (method, path, params) => {
    if (method !== 'GET') {
      state.writes.push({ method, path, params });
      assert.equal(method, 'POST');
      assert.equal(path, '/releases');
      return { html_url: 'https://github.com/release' };
    }
    state.reads.push(path);
    if (path === '/git/ref/heads/main') return { object: { sha: state.head } };
    if (path.startsWith('/actions/workflows/')) {
      assert.equal(params.head_sha, sha);
      assert.equal(params.branch, 'main');
      assert.equal(params.event, 'push');
      return { workflow_runs: state.runs[path.split('/')[3]] };
    }
    const value = path.startsWith('/releases/tags/') ? state.release : state.tag;
    if (!value) throw Object.assign(new Error('Not found'), { status: 404 });
    return value;
  };
  return { state, event, request, run: (options = {}) => publishSourceNightly({
    repository, request, event, now: new Date('2026-10-26T17:00:00Z'), ...options,
  }) };
}

test('publishes only a source prerelease at the exact approved commit', async () => {
  const f = fixture();
  assert.equal((await f.run()).published, true);
  assert.equal(f.state.writes.length, 1);
  const { params } = f.state.writes[0];
  assert.equal(params.target_commitish, sha);
  assert.equal(params.tag_name, 'nightly-aaaaaaaaaaaa');
  assert.equal(params.prerelease, true);
  assert.equal(params.draft, false);
  assert.equal(params.make_latest, 'false');
  assert.equal(params.generate_release_notes, true);
  assert.match(params.name, /2026-10-27/);
  assert.match(params.body, /No installer or portable application/);
  assert.ok(params.body.includes(sha));
});

for (const conclusion of ['failure', 'cancelled', 'skipped', 'timed_out', null]) {
  test(`does not publish when another check is ${conclusion}`, async () => {
    const f = fixture();
    f.state.runs['workshop-release-chain.yml'][0].conclusion = conclusion;
    assert.equal((await f.run()).published, false);
    assert.equal(f.state.writes.length, 0);
  });
}

test('missing or in-progress checks cannot be replaced by another commit or a PR run', async () => {
  for (const alteration of [
    (f) => { f.state.runs['layered-mesh-geometry.yml'] = []; },
    (f) => { f.state.runs['layered-mesh-geometry.yml'][0].status = 'in_progress'; },
    (f) => { f.state.runs['layered-mesh-geometry.yml'][0].head_sha = 'b'.repeat(40); },
    (f) => { f.state.runs['layered-mesh-geometry.yml'][0].event = 'pull_request'; },
  ]) {
    const f = fixture(); alteration(f);
    assert.equal((await f.run()).published, false);
    assert.equal(f.state.writes.length, 0);
  }
});

test('latest run takes precedence over an earlier success', async () => {
  const f = fixture();
  const runs = f.state.runs['layered-mesh-geometry.yml'];
  runs.push({ ...runs[0], id: 11, conclusion: 'failure' });
  assert.equal((await f.run()).published, false);
  runs[1].conclusion = 'success'; // successful rerun of the same newer run
  assert.equal((await f.run()).published, true);
});

test('PR, fork, manual, and unrelated workflow completions never enter the publishing gate', async () => {
  for (const change of [
    { event: 'pull_request' }, { event: 'workflow_dispatch' }, { head_branch: 'topic' },
    { head_repository: { full_name: 'someone/fork' } }, { conclusion: 'failure' },
    { path: '.github/workflows/unrelated.yml' },
  ]) {
    const f = fixture(); Object.assign(f.event.workflow_run, change);
    assert.equal((await f.run()).published, false);
    assert.equal(f.state.reads.length, 0);
    assert.equal(f.state.writes.length, 0);
  }
  const f = fixture();
  assert.equal((await f.run({ repository: 'someone/fork' })).published, false);
  assert.equal(f.state.reads.length, 0);
});

test('older completion cannot publish over newer main, including advancement during checks', async () => {
  const f = fixture(); f.state.head = 'b'.repeat(40);
  assert.equal((await f.run()).published, false);
  const g = fixture();
  let heads = 0;
  const request = async (...args) => {
    if (args[1] === '/git/ref/heads/main' && ++heads === 2) g.state.head = 'b'.repeat(40);
    return g.request(...args);
  };
  assert.equal((await g.run({ request })).published, false);
  assert.equal(g.state.writes.length, 0);
});

test('a late older completion cannot replace the pending publication of current main', async () => {
  const workflow = readFileSync(join(__dirname, '../workflows/source-nightly.yml'), 'utf8');
  const group = workflow.match(/^  group: (.+)$/m)?.[1];
  assert.ok(group, 'The publication workflow must declare its concurrency group');
  const current = fixture();
  const older = fixture();
  older.event.workflow_run.head_sha = 'b'.repeat(40);

  // GitHub retains only the last pending event within each concurrency group.
  // Read the real group expression so reverting to one global group loses current.
  const pending = new Map();
  for (const run of [current, older]) {
    const key = group.replace(/\$\{\{\s*github\.event\.workflow_run\.head_sha\s*\}\}/g,
      run.event.workflow_run.head_sha);
    pending.set(key, run);
  }
  for (const run of pending.values()) await run.run();
  assert.equal(current.state.writes.length, 1);
  assert.equal(current.state.writes[0].params.target_commitish, sha);
  assert.equal(older.state.writes.length, 0);
});

test('duplicate completion is idempotent and never edits existing releases or tags', async () => {
  const f = fixture();
  f.state.release = { draft: false, prerelease: true, assets: [] };
  f.state.tag = { object: { type: 'commit', sha } };
  assert.equal((await f.run()).published, false);
  assert.equal(f.state.writes.length, 0);
});

test('refuses tag collisions and a release containing binaries', async () => {
  const f = fixture();
  f.state.tag = { object: { type: 'commit', sha: 'b'.repeat(40) } };
  await assert.rejects(f.run(), /refusing to move/);
  assert.equal(f.state.writes.length, 0);
  const g = fixture();
  g.state.tag = { object: { type: 'commit', sha } };
  g.state.release = { draft: false, prerelease: true, assets: [{ name: 'installer.exe' }] };
  await assert.rejects(g.run(), /source-only prerelease/);
  assert.equal(g.state.writes.length, 0);
});

test('API errors fail closed, rather than being treated as missing releases', async () => {
  const f = fixture();
  await assert.rejects(f.run({ request: async () => { throw Object.assign(new Error('Forbidden'), { status: 403 }); } }), /Forbidden/);
  assert.equal(f.state.writes.length, 0);
});

test('dry run validates live metadata without publishing', async () => {
  const f = fixture();
  assert.equal((await f.run({ dryRun: true })).eligible, true);
  assert.equal(f.state.writes.length, 0);
});
