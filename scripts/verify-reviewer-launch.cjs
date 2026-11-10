// Cross-language installed contract: real GWS binding -> kit runner -> native report.
// Uses only a disposable local no-diff Git fixture; this is not a model-quality test.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync, spawnSync } = require('node:child_process');
const kit = path.resolve(__dirname, '..');
const workbench = process.env.WORKFLOWKIT_WORKBENCH_ROOT ?? path.resolve(kit, '../GitlabWorkSpace');
const { readInstalledReviewerBinding } = require(path.join(workbench, 'out/src/workspace/installedReviewer.js'));
const { saveReviewLaunchRequest } = require(path.join(workbench, 'out/src/workspace/reviewLaunch.js'));
const { readReviewerCapabilities } = require(path.join(workbench, 'out/src/workspace/reviewerCapabilities.js'));
const { reviewSessionActions } = require(path.join(workbench, 'out/src/workspace/reviewSessionProtocol.js'));
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const arg = name => { const index = process.argv.indexOf(name); return index < 0 ? undefined : process.argv[index + 1]; };
async function treeSnapshot(root) {
  const rows = [];
  async function visit(file) {
    const stat = await fs.lstat(file);
    if (stat.isSymbolicLink()) throw new Error('Unexpected link in owned fixture runtime');
    rows.push([path.relative(root, file), stat.mtimeMs, stat.isDirectory() ? 'directory' : sha(await fs.readFile(file))]);
    if (stat.isDirectory()) for (const name of (await fs.readdir(file)).sort()) await visit(path.join(file, name));
  }
  await visit(root); return JSON.stringify(rows);
}

(async () => {
  const output = path.resolve(arg('--output') ?? path.join(kit, '.tmp/reviewer-launch-installed.json'));
  const parent = path.join(kit, '.tmp'); await fs.mkdir(parent, { recursive: true });
  const root = await fs.mkdtemp(path.join(parent, 'launch-'));
  const workspace = path.join(root, 'Project', '工作區 with space');
  const repo = path.join(workspace, 'service'), runtime = path.join(root, 'native');
  const env = { ...process.env, GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: 'core.longpaths', GIT_CONFIG_VALUE_0: 'true',
    GITLAB_WORKSPACE_RUNTIME_DIR: path.join(root, 'network') };
  const result = { schema: 'ReviewerInstalledLaunchVerification/v1', modelEvaluation: false, checks: [], status: 'running' };
  try {
    await fs.mkdir(repo, { recursive: true });
    const git = (...args) => execFileSync('git', ['-C', repo, ...args], { env, windowsHide: true, encoding: 'utf8' }).trim();
    git('init', '-q', '-b', 'main'); git('config', 'user.name', 'Launch Contract Fixture');
    git('config', 'user.email', 'fixture@example.invalid'); git('config', 'commit.gpgsign', 'false');
    git('config', 'core.hooksPath', path.join(root, 'no-hooks'));
    await fs.writeFile(path.join(repo, 'app.py'), 'def total(a, b):\n    return a + b\n');
    git('add', '.'); git('commit', '-qm', 'fixed no-diff fixture'); git('branch', 'feature/review');
    const archive = path.join(kit, 'resources/offline-tools/workflow-kit.tar.xz');
    const version = (await fs.readFile(path.join(kit, 'VERSION'), 'utf8')).trim();
    execFileSync('python', ['-X', 'utf8', '-B', path.join(kit, 'resources/workflow-kit-installer.py'), 'install', archive,
      workspace, version, 'bundled', '--format', 'tar.xz', '--entry-root', 'workflow-kit', '--archive-sha256',
      sha(await fs.readFile(archive)), '--profile', 'group'], { env, windowsHide: true, encoding: 'utf8', timeout: 180000, maxBuffer: 4 * 1024 * 1024 });
    const binding = await readInstalledReviewerBinding(workspace, 'merge-reviewer');
    if (binding.workflow_kit_runner?.review_launch_request !== 1) throw new Error('GWS did not discover the installed launch capability');
    const python = { executable: 'python', args: [], env };
    // The real workbench reader verifies the binding before its native probe.
    const capabilities = await readReviewerCapabilities(binding, python, workspace);
    if (capabilities?.features?.completion_preview !== true) throw new Error('Native completion preview missing');
    result.checks.push('installed-gws-binding-and-native-capabilities');
    const requestId = crypto.randomUUID().replaceAll('-', '');
    const launch = await saveReviewLaunchRequest({ schema: 'ReviewLaunchRequest/v1', tool: 'merge-reviewer', request_id: requestId,
      workspace, project: repo, base: 'main', head: 'feature/review', runtime_root: runtime,
      binding, draft_format: 'compact', no_fetch: true });
    if (launch.path.startsWith(runtime + path.sep)) throw new Error('Launch file polluted native ownership root');
    async function run(action, accepted = [0], request = launch) {
      const child = spawnSync('python', ['-X', 'utf8', '-B', binding.workflow_kit_runner.script_path,
        '--review-request', request.path, '--expected-request-sha256', request.sha256, '--action', action],
        { env, windowsHide: true, encoding: 'utf8', timeout: 180000, maxBuffer: 8 * 1024 * 1024 });
      if (!accepted.includes(child.status)) throw new Error(`${action}: ${child.status}: ${child.stderr}\n${child.stdout}`);
      return JSON.parse(child.stdout);
    }
    const preflight = await run('preflight');
    if (!preflight.valid) throw new Error('Valid Unicode/space path failed preflight');
    try { await fs.access(runtime); throw new Error('Preflight wrote the native runtime'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    const started = await run('start');
    const jobPath = path.join(runtime, 'jobs', requestId + '.json');
    const firstJob = JSON.parse(await fs.readFile(jobPath, 'utf8'));
    const firstContext = await treeSnapshot(firstJob.context_dir);
    await run('start');
    const job = JSON.parse(await fs.readFile(jobPath, 'utf8'));
    if ((await fs.readdir(path.join(runtime, 'jobs'))).filter(name => name.endsWith('.json')).length !== 1) throw new Error('Retry recaptured a new job');
    if (job.inputs.workspace !== workspace || job.inputs.project !== repo || job.draft_format !== 'compact') throw new Error('Bound launch inputs drifted');
    if (job.context_dir !== firstJob.context_dir || job.started_at !== firstJob.started_at ||
        job.input_digest !== firstJob.input_digest || (await treeSnapshot(job.context_dir)) !== firstContext) throw new Error('Retry changed the captured snapshot');
    result.checks.push('unicode-space-project-path', 'preflight-no-native-writes', 'single-capture-idempotency', 'compact-draft');
    const draftPath = job.draft_path ?? path.join(job.context_dir, 'draft.json');
    const draft = JSON.parse(await fs.readFile(draftPath, 'utf8'));
    draft.summary = '固定來源沒有差異。';
    draft.tests_not_executed = ['This wiring fixture does not execute a business application.'];
    draft.scope_notes = ['Declared local fixture only.'];
    await fs.writeFile(draftPath, JSON.stringify(draft));
    const checked = await run('check');
    if (checked.expected_outcome?.review_complete !== true) throw new Error('Nonblocking notes changed completion');
    const published = await run('finish');
    if (published.review_outcome?.review_complete !== true) throw new Error('Native publication disagreed with check');
    const bytes = await fs.readFile(published.report_path);
    const jobBefore = await fs.readFile(jobPath); const modified = (await fs.stat(jobPath)).mtimeMs;
    const inspectionBefore = [await treeSnapshot(runtime), await treeSnapshot(runtime + '-workflow-kit')];
    await run('status');
    if (!(await fs.readFile(jobPath)).equals(jobBefore) || (await fs.stat(jobPath)).mtimeMs !== modified) throw new Error('Summary status wrote job metadata');
    if (JSON.stringify([await treeSnapshot(runtime), await treeSnapshot(runtime + '-workflow-kit')]) !== JSON.stringify(inspectionBefore)) throw new Error('Summary inspection changed the native or scratch tree');
    const again = await run('finish');
    if (again.report_path !== published.report_path || !(await fs.readFile(again.report_path)).equals(bytes)) throw new Error('Published retry changed the immutable report');
    if (reviewSessionActions({ state: 'published', cleanupPending: false }).resume || reviewSessionActions({ state: 'failed' }).resume) throw new Error('Terminal action gate regressed');
    result.checks.push('check-finish-outcome-agreement', 'nonblocking-scope-and-tests', 'readonly-published-status', 'immutable-publication-retry', 'gws-terminal-action-gates');
    result.status = 'passed'; result.kitVersion = version; result.reviewerVersion = binding.version;
    result.reportSha256 = sha(bytes); result.reviewComplete = published.review_outcome.review_complete;
    result.sourceCommit = git('rev-parse', 'HEAD');
    result.artifactRoot = root;
  } catch (error) { result.status = 'failed'; result.error = error.message; process.exitCode = 1; }
  await fs.mkdir(path.dirname(output), { recursive: true }); await fs.writeFile(output, JSON.stringify(result, null, 2) + '\n');
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
