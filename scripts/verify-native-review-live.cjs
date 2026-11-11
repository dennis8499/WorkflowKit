const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
// Opt-in live verification: uses the current Codex account and a fresh fixture.
const workbench = process.env.WORKFLOWKIT_WORKBENCH_ROOT ?? path.resolve(__dirname, '../../GitlabWorkSpace');
const outputDirectory = path.resolve(__dirname, '../.tmp');
const { CodexBridge } = require(path.join(workbench, 'out/src/codex/bridge.js'));
const argument = (name, fallback) => { const index = process.argv.indexOf(name); return index < 0 ? fallback : process.argv[index + 1]; };
const selectedModel = argument('--model', 'gpt-6-luna'), requestedEffort = argument('--effort', 'xhigh');
if (!/^[a-zA-Z0-9._-]{1,200}$/.test(selectedModel) || !/^[a-z][a-z0-9_-]{0,39}$/.test(requestedEffort)) throw new Error('Invalid smoke model/effort');
const runId = argument('--run-id', new Date().toISOString().replace(/[:.]/g, '-') + '-' + crypto.randomUUID().slice(0, 8));
if (!/^[a-zA-Z0-9._-]{1,100}$/.test(runId)) throw new Error('Invalid smoke run ID');
const resultPrefix = `native-review-app-server-${selectedModel}-${requestedEffort}-${runId}`;
(async () => {
  await fs.mkdir(outputDirectory, { recursive: true });
  await fs.writeFile(path.join(outputDirectory, resultPrefix + '-trace.jsonl'), '', { flag: 'wx' });
  const temporaryRoot = path.resolve(__dirname, '../../.tmp'); await fs.mkdir(temporaryRoot, { recursive: true });
  const root = await fs.mkdtemp(path.join(temporaryRoot, 'native-'));
  const group = path.join(root, 'workspace'), repo = path.join(group, 'service'), runtime = path.join(root, 'runtime');
  const requestId = crypto.randomUUID().replaceAll('-', '');
  process.env.GITLAB_WORKSPACE_RUNTIME_DIR = path.join(root, 'network');
  const result = { status: 'running', requestId, root, model: selectedModel, requestedEffort };
  let bridge;
  const events = [];
  try {
    await fs.mkdir(repo, { recursive: true });
    const git = (...args) => execFileSync('git', ['-C', repo, ...args], { windowsHide: true, encoding: 'utf8' }).trim();
    git('init', '-q', '-b', 'main'); git('config', 'user.name', 'Routing smoke'); git('config', 'user.email', 'fixture@example.invalid');
    git('config', 'core.longpaths', 'true'); git('config', 'core.autocrlf', 'false'); git('config', 'commit.gpgsign', 'false'); git('config', 'core.hooksPath', path.join(root, 'no-hooks'));
    await fs.writeFile(path.join(repo, 'app.py'), 'def average(total, count):\n    if count == 0:\n        return 0\n    return total / count\n');
    await fs.writeFile(path.join(repo, '.gitignore'), '/review-reports/\n'); git('add', '.'); git('commit', '-qm', 'base');
    git('switch', '-qc', 'feature');
    await fs.writeFile(path.join(repo, 'app.py'), 'def average(total, count):\n    return total / count\n'); git('add', '.'); git('commit', '-qm', 'remove empty case');
    const archive = path.resolve(__dirname, '../resources/offline-tools/workflow-kit.tar.xz');
    const sha = crypto.createHash('sha256').update(await fs.readFile(archive)).digest('hex');
    const version = (await fs.readFile(path.resolve(__dirname, '../VERSION'), 'utf8')).trim();
    execFileSync('python', ['-X', 'utf8', '-B', path.resolve(__dirname, '../resources/workflow-kit-installer.py'), 'install', archive,
      group, version, 'bundled', '--format', 'tar.xz', '--entry-root', 'workflow-kit', '--archive-sha256', sha, '--profile', 'group'],
      { windowsHide: true, encoding: 'utf8', timeout: 180000, maxBuffer: 1024 * 1024 });
    const tool = 'merge-reviewer';
    const { readInstalledReviewerBinding } = require(path.join(workbench, 'out/src/workspace/installedReviewer.js'));
    const { saveReviewLaunchRequest } = require(path.join(workbench, 'out/src/workspace/reviewLaunch.js'));
    const guide = require(path.join(workbench, 'out/src/webview/skillsGuideData.js'));
    const binding = await readInstalledReviewerBinding(group, tool);
    const capabilities = JSON.parse(execFileSync('python', ['-X', 'utf8', '-B', binding.script_path, 'capabilities'], { encoding: 'utf8', windowsHide: true }));
    const launch = await saveReviewLaunchRequest({ schema: 'ReviewLaunchRequest/v1', tool, request_id: requestId,
      workspace: group, project: repo, base: 'main', head: 'feature', runtime_root: runtime, binding, draft_format: 'compact', no_fetch: true });
    const card = guide.getSkillGuideCard(tool);
    const context = { root: group, workspaceRoot: group, repositories: [{ name: 'service', path: repo }],
      workflowKitVersion: version, workflowKitRunner: binding.workflow_kit_runner, reviewerBinding: binding,
      reviewerCapabilities: capabilities, reviewerRequestId: requestId, reviewRuntimeRoot: runtime, reviewLaunch: launch };
    const spec = { source: { kind: 'skill', featureId: 'merge-repo', inputs: {}, revision: 'smoke' }, title: 'Native fixed review smoke', root: group,
      workspaceKey: group, prompt: `$merge-reviewer Repo=${JSON.stringify(repo)} base=main head=feature\n` +
        `Declared workspace=${JSON.stringify(group)}; runtime_root=${JSON.stringify(runtime)}; request_id=${requestId}.\n` +
        'The current agent is the native reviewer; keep the selected model and effort. Use the installed native helper and kit runner. All branches are local; keep capture offline. This fixture is a pure calculation helper; review the removed zero-count behavior. Finish the native report with all required coverage and retain any real gaps.',
      skill: { name: tool, path: path.join(group, '.agents/skills', tool, 'SKILL.md') }, writableRoots: [group, runtime, runtime + '-workflow-kit', path.join(root, 'network')],
      environmentKey: 'smoke', review: { tool, requestId, revision: 'smoke', runtimeRoot: runtime, workspaceRoot: group, repositoryPath: repo } };
    spec.prompt = guide.buildSkillGuideContext(card, context) + '\n\n' + guide.buildSkillGuidePrompt(card,
      { 'merge-repo.repo': repo, 'merge-repo.base': 'main', 'merge-repo.head': 'feature' }, context) +
      '\nUse the bound local launch command above. All branches are local. Complete native review, check and finish. Preserve all inspected source files. Local helper tools provide the required evidence.';
    result.startedAt = new Date().toISOString(); const started = Date.now();
    bridge = new CodexBridge({ storage: path.join(root, 'storage'), version: 'native-smoke', executable: () => '', trusted: () => true,
      prepare: async () => spec, openUrl: async () => {},
      event: event => {
        events.push(event);
        require('node:fs').appendFileSync(path.join(outputDirectory, resultPrefix + '-trace.jsonl'), JSON.stringify({ at: new Date().toISOString(), event }) + '\n');
        if (event.kind === 'tasks') {
          const task = event.tasks[0]; if (task) process.stdout.write(JSON.stringify({ status: task.status, effort: task.selection?.effort, phase: task.progress?.phase, error: task.error }) + '\n');
        }
        if (event.kind === 'interactions') for (const item of event.interactions) {
          // The authorized fixture roots are already in the turn sandbox.
          // This unattended check never approves additional access.
          void bridge.answer(item.taskId, item.id, { decision: 'decline' }).catch(() => {});
        }
      } });
    const models = await bridge.models(group), selected = models.find(item => item.model === selectedModel);
    if (!selected) throw new Error(`Selected live model unavailable: ${selectedModel}`);
    const supportedEfforts = selected.supportedReasoningEfforts.map(item => item.reasoningEffort);
    Object.assign(spec.source, { model: selectedModel, effort: requestedEffort, modelEfforts: supportedEfforts });
    Object.assign(spec, { model: selectedModel, effort: requestedEffort });
    await bridge.enqueue(spec, 'native-smoke');
    const deadline = Date.now() + 600000;
    while (Date.now() < deadline) {
      const task = bridge.list()[0];
      if (task && ['completed', 'paused', 'failed', 'uncertain', 'interrupted'].includes(task.status)) {
        result.task = task; break;
      }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    if (!result.task) { await bridge.cancel('native-smoke'); throw new Error('Native smoke timed out'); }
    if (result.task.status !== 'completed') throw new Error(result.task.error ?? result.task.status);
    const job = JSON.parse(await fs.readFile(path.join(runtime, 'jobs', requestId + '.json'), 'utf8'));
    const reports = await fs.readdir(path.join(repo, 'review-reports'));
    result.status = job.state === 'published' && reports.length === 1 ? 'passed' : 'failed';
    result.diagnostics = bridge.diagnosticSnapshot(result.task.id); result.nativeState = job.state; result.networkActivity = job.network_activity;
    result.reviewOutcome = job.review_outcome; result.report = await fs.readFile(job.report_path, 'utf8');
    result.workingTreeStatus = git('status', '--porcelain');
    result.captureCount = (job.metrics?.git_command_phases ?? []).filter(item => item.phase === 'start').length;
    result.reportCount = reports.length;
    result.nativeJobCount = (await fs.readdir(path.join(runtime, 'jobs'))).filter(name => name.endsWith('.json')).length;
    if (result.captureCount !== 1 || result.nativeJobCount !== 1 || result.workingTreeStatus ||
        !result.reviewOutcome?.review_complete || !/ZeroDivisionError|除.{0,3}零/u.test(result.report)) {
      throw new Error('Native evidence, capture count, coverage or defect recall did not match the fixture');
    }
    result.contextRetained = await fs.stat(job.context_dir).then(() => true).catch(() => false);
    if (result.task.selection?.model !== selectedModel || result.task.selection?.effort !== requestedEffort || result.task.modelRouting) throw new Error('Fixed model/effort were not preserved');
    result.elapsedSeconds = (Date.now() - started) / 1000;
    await fs.writeFile(path.join(outputDirectory, resultPrefix + '-events.json'), JSON.stringify(events, null, 2));
  } catch (error) { result.status = 'failed'; result.error = error.message; process.exitCode = 1; }
  finally {
    const trace = JSON.stringify(events, null, 2);
    await fs.writeFile(path.join(outputDirectory, resultPrefix + '-events.json'), trace);
    result.traceSha256 = crypto.createHash('sha256').update(trace).digest('hex');
    await bridge?.shutdown();
    if (bridge) {
      result.finalTaskStatus = bridge.list()[0]?.status;
      if (result.status === 'passed' && result.finalTaskStatus !== 'completed') { result.status = 'failed'; process.exitCode = 1; }
    }
    await fs.writeFile(path.join(outputDirectory, resultPrefix + '-result.json'), JSON.stringify(result, null, 2));
    process.stdout.write(JSON.stringify({ status: result.status, error: result.error, nativeState: result.nativeState }) + '\n');
    // Keep the isolated fixture as an inspectable proof until task delivery.
  }
})().catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
