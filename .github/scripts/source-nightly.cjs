'use strict';

// Keep this list and source-nightly.yml's completion triggers in sync when
// adding or renaming a main-branch CI workflow.
const REQUIRED_WORKFLOWS = [
  'layered-mesh-geometry.yml',
  'native-svg-core.yml',
  'workshop-release-chain.yml',
];

// Only GitHub metadata is read here. Never download or execute upstream artifacts.
async function publishSourceNightly({ request, event, repository, now = new Date(), dryRun = false }) {
  const run = event.workflow_run;
  const skip = (reason) => ({ published: false, reason });
  if (repository !== 'lumina-layer-studio/Lumina-Layers'
      || run?.event !== 'push' || run.head_branch !== 'main'
      || run.head_repository?.full_name !== repository
      || run.status !== 'completed' || run.conclusion !== 'success'
      || !REQUIRED_WORKFLOWS.some((file) => run.path === `.github/workflows/${file}`)) {
    return skip('Not a successful main push check from the public repository.');
  }
  const sha = run.head_sha;
  if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error('Invalid source commit SHA.');
  const currentHead = async () => (await request('GET', '/git/ref/heads/main')).object.sha;
  if (await currentHead() !== sha) return skip('A newer main commit is waiting for its own checks.');

  const checks = [];
  for (const file of REQUIRED_WORKFLOWS) {
    const data = await request('GET', `/actions/workflows/${file}/runs`, {
      branch: 'main', event: 'push', head_sha: sha, per_page: 100,
    });
    // A re-run keeps its run ID; GitHub returns its current attempt and status.
    const latest = data.workflow_runs
      .filter((item) => item.head_sha === sha && item.head_branch === 'main' && item.event === 'push')
      .sort((a, b) => b.id - a.id)[0];
    if (!latest || latest.status !== 'completed' || latest.conclusion !== 'success') {
      return skip(`${file}: the latest push run for this commit has not passed.`);
    }
    checks.push({ file, url: latest.html_url });
  }

  const tag = `nightly-${sha.slice(0, 12)}`;
  const optionalGet = async (path) => {
    try { return await request('GET', path); }
    catch (error) { if (error.status === 404) return null; throw error; }
  };
  const existing = await optionalGet(`/releases/tags/${tag}`);
  const ref = await optionalGet(`/git/ref/tags/${tag}`);
  if (ref && (ref.object.type !== 'commit' || ref.object.sha !== sha)) {
    throw new Error(`Tag ${tag} already points to another object; refusing to move it.`);
  }
  if (existing) {
    if (!ref || existing.draft || !existing.prerelease || existing.assets.length) {
      throw new Error(`Existing release ${tag} is not the expected source-only prerelease.`);
    }
    return skip(`Source nightly ${tag} already exists.`);
  }
  if (await currentHead() !== sha) return skip('Main advanced while checking CI; leave publication to the newer commit.');
  if (dryRun) return { published: false, eligible: true, sha, tag, checks };

  const date = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Singapore', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(now);
  const body = [
    '源码预览版，可能仍有未发现的问题。只提供源码，不提供安装包或便携版。',
    '',
    '下载下方 Source code (zip / tar.gz)，解压后按此版本 README 安装依赖并运行。已有本地修改时，先保存到自己的分支或备份，再切换版本。',
    '',
    'This is a source-only preview. Download the source archive below and follow its README to install dependencies and run Lumina. No installer or portable application is provided.',
    '',
    `Commit: ${sha}`,
    `Published date (UTC+8): ${date}`,
    '',
    `[中文安装说明](https://github.com/${repository}/blob/${sha}/README_CN.md#安装) · [Installation](https://github.com/${repository}/blob/${sha}/README.md#installation)`,
    '',
    '反馈问题时请附上以上提交编号 / Include this commit SHA in bug reports.',
    '',
    ...checks.map(({ file, url }) => `- [${file}](${url})`),
  ].join('\n');
  const release = await request('POST', '/releases', {
    tag_name: tag,
    target_commitish: sha,
    name: `Source Nightly · ${date} · ${sha.slice(0, 12)}`,
    body,
    draft: false,
    prerelease: true,
    make_latest: 'false',
    generate_release_notes: true,
  });
  return { published: true, sha, tag, url: release.html_url };
}

module.exports = { REQUIRED_WORKFLOWS, publishSourceNightly };
