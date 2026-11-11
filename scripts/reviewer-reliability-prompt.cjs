// Use the frozen product prompt builder and installed binding; no oracle input.
const fs = require('node:fs/promises');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
(async () => {
  const input = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
  const { readInstalledReviewerBinding } = require(path.join(input.engine, 'gws/src/workspace/installedReviewer.js'));
  const guide = require(path.join(input.engine, 'gws/src/webview/skillsGuideData.js'));
  const binding = await readInstalledReviewerBinding(input.workspace, 'merge-reviewer');
  const capabilities = JSON.parse(execFileSync(input.python, ['-X', 'utf8', '-B', binding.script_path, 'capabilities'], { encoding: 'utf8', windowsHide: true }));
  const context = { root: input.workspace, groupRoot: input.workspace, workspaceRoot: input.workspace,
    repositories: input.repositories, workflowKitVersion: input.version, workflowKitRunner: binding.workflow_kit_runner,
    reviewRuntimeRoot: input.runtime, reviewerBinding: binding, reviewerCapabilities: capabilities,
    reviewerRequestId: input.requestId, modelRouting: false };
  if (input.variant === 'candidate') {
    const { saveReviewLaunchRequest } = require(path.join(input.engine, 'gws/src/workspace/reviewLaunch.js'));
    context.reviewLaunch = await saveReviewLaunchRequest({ schema: 'ReviewLaunchRequest/v1', tool: 'merge-reviewer',
      request_id: input.requestId, workspace: input.workspace, project: input.project, base: input.base, head: input.head,
      runtime_root: input.runtime, binding, draft_format: 'compact', no_fetch: true });
  }
  const card = guide.getSkillGuideCard('merge-reviewer', 'merge-repo');
  const prompt = guide.buildSkillGuideContext(card, context) + '\n\n' + guide.buildSkillGuidePrompt(card,
    { 'merge-repo.repo': input.project, 'merge-repo.base': input.base, 'merge-repo.head': input.head, 'merge-repo.effort': 'auto' }, context);
  process.stdout.write(JSON.stringify({ prompt, binding, capabilities }));
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
