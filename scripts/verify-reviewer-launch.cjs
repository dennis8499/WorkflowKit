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
  const profile = arg('--profile') ?? 'group';
  if (!['group', 'repository'].includes(profile)) throw new Error('Unknown installation profile');
  const timeoutSeconds = Number(arg('--timeout-seconds') ?? '180');
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 30 || timeoutSeconds > 1800) throw new Error('Timeout must be 30..1800 seconds');
  const timeout = timeoutSeconds * 1000;
  const parent = path.resolve(arg('--fixture-root') ?? path.join(kit, '.tmp'));
  await fs.mkdir(parent, { recursive: true });
  const root = await fs.mkdtemp(path.join(parent, 'launch-'));
  const workspace = path.join(root, 'Project', '工作區 with space');
  const repo = path.join(workspace, 'service'), runtime = path.join(root, 'native');
  const installRoot = profile === 'repository' ? repo : workspace;
  const env = { ...process.env, GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: 'core.longpaths', GIT_CONFIG_VALUE_0: 'true',
    GITLAB_WORKSPACE_RUNTIME_DIR: path.join(root, 'network') };
  const result = { schema: 'ReviewerInstalledLaunchVerification/v1', modelEvaluation: false, profile, timeoutSeconds, checks: [], status: 'running' };
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
      installRoot, version, 'bundled', '--format', 'tar.xz', '--entry-root', 'workflow-kit', '--archive-sha256',
      sha(await fs.readFile(archive)), '--profile', profile], { env, windowsHide: true, encoding: 'utf8', timeout, maxBuffer: 4 * 1024 * 1024 });
    const binding = await readInstalledReviewerBinding(installRoot, 'merge-reviewer');
    if (binding.workflow_kit_runner?.review_launch_request !== 1) throw new Error('GWS did not discover the installed launch capability');
    const python = { executable: 'python', args: [], env };
    // The real workbench reader verifies the binding before its native probe.
    const capabilities = await readReviewerCapabilities(binding, python, installRoot);
    if (capabilities?.features?.completion_preview !== true) throw new Error('Native completion preview missing');
    if (capabilities?.features?.paging_state !== true || capabilities?.features?.operation_schema !== true) throw new Error('Installed paging/schema capabilities missing');
    result.checks.push('installed-gws-binding-and-native-capabilities');
    const requestId = crypto.randomUUID().replaceAll('-', '');
    const launch = await saveReviewLaunchRequest({ schema: 'ReviewLaunchRequest/v1', tool: 'merge-reviewer', request_id: requestId,
      workspace: installRoot, project: repo, base: 'main', head: 'feature/review', runtime_root: runtime,
      binding, draft_format: 'compact', no_fetch: true });
    if (launch.path.startsWith(runtime + path.sep)) throw new Error('Launch file polluted native ownership root');
    async function run(action, accepted = [0], request = launch, extra = []) {
      const child = spawnSync('python', ['-X', 'utf8', '-B', binding.workflow_kit_runner.script_path,
        '--review-request', request.path, '--expected-request-sha256', request.sha256, '--action', action,
        ...(extra.length ? ['--', ...extra] : [])],
        { env, windowsHide: true, encoding: 'utf8', timeout, maxBuffer: 8 * 1024 * 1024 });
      if (!accepted.includes(child.status)) throw new Error(`${action}: ${child.status}: ${child.stderr}\n${child.stdout}`);
      return JSON.parse(child.stdout);
    }
    const beforeSchema = await treeSnapshot(root);
    const schema = await run('schema', [0], launch, ['--operation', 'author']);
    if (!JSON.stringify(schema).includes('expected_checkpoint_revision')) throw new Error('Installed operation schema omitted checkpoint CAS');
    if ((await treeSnapshot(root)) !== beforeSchema) throw new Error('Schema inspection wrote files');
    result.checks.push('bound-schema-no-runtime-writes');
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
    if (job.inputs.workspace !== installRoot || job.inputs.project !== repo || job.draft_format !== 'compact') throw new Error('Bound launch inputs drifted');
    if (job.context_dir !== firstJob.context_dir || job.started_at !== firstJob.started_at ||
        job.input_digest !== firstJob.input_digest || (await treeSnapshot(job.context_dir)) !== firstContext) throw new Error('Retry changed the captured snapshot');
    result.checks.push('unicode-space-project-path', 'preflight-no-native-writes', 'single-capture-idempotency', 'compact-draft');
    const draftPath = job.draft_path ?? path.join(job.context_dir, 'draft.json');
    const operationsPath = path.join(root, 'installed-operations.json');
    async function step(operations) {
      await fs.writeFile(operationsPath, JSON.stringify(operations));
      const child = spawnSync('python', ['-X', 'utf8', '-B', binding.workflow_kit_runner.script_path,
        '--runtime-root', runtime + '-workflow-kit', '--',
        'python', '-X', 'utf8', '-B', binding.script_path, 'step', '--runtime-root', runtime,
        '--request-id', requestId, '--requests-file', operationsPath],
        { env, windowsHide: true, encoding: 'utf8', timeout, maxBuffer: 8 * 1024 * 1024 });
      if (child.status !== 0) throw new Error(`step: ${child.status}: ${child.stderr}\n${child.stdout}`);
      return JSON.parse(child.stdout);
    }
    const read = await step([{ id: 'installed-read', op: 'read', repo: firstJob.selected_repo, source: 'head', path: 'app.py' }]);
    const artifact = read.operations[0].artifact;
    const state = { schema: 'MergeReviewPaging/v1', runtime_root: runtime, request_id: requestId,
      pending: ['first', 'duplicate'].map(id => ({ id, command: 'review_session.py view', read_only: true,
        runtime_root: runtime, request_id: requestId, artifact, artifact_scope: 'context', pointer: '/lines', offset: 0, page_size: 70 })),
      acknowledged: [], blocked: [] };
    const statePath = path.join(root, 'installed-paging.json'), responsePath = path.join(root, 'installed-paging-response.json');
    await fs.writeFile(statePath, JSON.stringify(state));
    const beforePaging = [await treeSnapshot(runtime), await treeSnapshot(runtime + '-workflow-kit')];
    const page = await run('view', [0], launch, ['--requests-file', statePath]);
    if (page.schema !== 'MergeReviewPagingBatch/v1' || page.results.map(row => row.status).join(',') !== 'returned,duplicate' ||
        page.artifact_load_count !== 1 || page.git_commands !== 0) throw new Error('Installed paging did not deduplicate its fixed artifact');
    if (JSON.stringify([await treeSnapshot(runtime), await treeSnapshot(runtime + '-workflow-kit')]) !== JSON.stringify(beforePaging)) throw new Error('Paging inspection wrote native/scratch files');
    await fs.writeFile(responsePath, JSON.stringify(page));
    const applied = spawnSync('python', ['-X', 'utf8', '-B', '-c',
      "import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import review_paging;p=Path(sys.argv[2]);p.write_text(json.dumps(review_paging.apply_delta(json.loads(p.read_text(encoding='utf-8')),json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))['paging_delta'])),encoding='utf-8')",
      path.dirname(binding.script_path), statePath, responsePath], { env, windowsHide: true, encoding: 'utf8' });
    if (applied.status !== 0) throw new Error(`Installed paging acknowledgment failed: ${applied.stderr}`);
    const acknowledged = JSON.parse(await fs.readFile(statePath, 'utf8'));
    if (acknowledged.pending.length !== 0 || acknowledged.acknowledged.length !== 1) throw new Error('Installed paging acknowledgment lost the completed state');
    await step([{ id: 'installed-save', op: 'author', expected_draft_sha256: sha(await fs.readFile(draftPath)),
      expected_checkpoint_revision: 0, updates: { summary: '固定來源沒有差異。',
        tests_not_executed: ['This wiring fixture does not execute a business application.'], scope_notes: ['Declared local fixture only.'] },
      checkpoint: { next_action: 'check', paging: acknowledged } }]);
    const summary = await run('status');
    if (summary.checkpoint_revision !== 1 || summary.paging_counts?.acknowledged !== 1 || !summary.paging_ref) throw new Error('Installed summary lost the complete paging reference');
    const recovered = await run('view', [0], launch, ['--artifact', summary.paging_ref.artifact, '--artifact-scope', 'context']);
    if (recovered.value?.acknowledged?.length !== 1 || recovered.value?.pending?.length !== 0) throw new Error('Installed state artifact did not recover');
    result.checks.push('installed-native-paging-dedup', 'readonly-paging-no-git-or-writes', 'atomic-author-paging-checkpoint', 'summary-reference-recovery');
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
    result.reviewerPayloadSha256 = binding.payload_sha256;
    result.reportSha256 = sha(bytes); result.reviewComplete = published.review_outcome.review_complete;
    result.sourceCommit = git('rev-parse', 'HEAD');
    result.artifactRoot = root;
  } catch (error) { result.status = 'failed'; result.error = error.message; process.exitCode = 1; }
  await fs.mkdir(path.dirname(output), { recursive: true }); await fs.writeFile(output, JSON.stringify(result, null, 2) + '\n');
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
