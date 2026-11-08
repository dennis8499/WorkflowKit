"""Real installed-kit / compiled-extension / Wiki-inventory integration smoke."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path.cwd().resolve()
KIT = ROOT / 'dist/gitlab-workspace-kit-1.6.0.zip'
EXTENSION = ROOT.parent / 'GitlabWorkSpace/out/src/workspace/workflowKitRunner.js'
NODE = r'''
const [root, modulePath, python, action, original] = process.argv.slice(1);
(async () => {
  const api = require(modulePath);
  if (action === 'tamper') {
    let rejected = false;
    try { await api.workflowKitPythonCommand({executable:python,args:[],env:{}}, JSON.parse(original), []); }
    catch { rejected = true; }
    if (!rejected) throw Error('Tampered bundle was accepted');
    console.log(JSON.stringify({tamper_rejected:true}));
    return;
  }
  const runner = await api.readWorkflowKitRunnerBinding(root);
  if (!runner?.syntax_analysis) throw Error('Missing real syntax binding');
  const syntax = runner.syntax_analysis;
  const command = await api.workflowKitPythonCommand({executable:python,args:[],env:{}}, runner,
    [syntax.script_path,'capabilities','--expected-engine-sha256',syntax.engine_sha256]);
  console.log(JSON.stringify({runner,command}));
})().catch(error => {console.error(error);process.exitCode=1;});
'''


def call(arguments, env=None):
    process = subprocess.run(arguments, capture_output=True, text=True, encoding='utf-8', env=env, timeout=180)
    if process.returncode:
        raise AssertionError(process.stdout + process.stderr)
    return json.loads(process.stdout)


with tempfile.TemporaryDirectory(prefix='syntax-binding-final-') as temporary:
    root = Path(temporary)
    group = root / 'group'
    group.mkdir()
    installed = call([sys.executable, '-X', 'utf8', '-B', str(ROOT/'dist/workflowkit-installer-1.6.0.py'),
                      'install', str(KIT), str(group), '1.6.0', 'bundled', '--format', 'zip',
                      '--entry-root', 'workflow-kit', '--archive-sha256', hashlib.sha256(KIT.read_bytes()).hexdigest(), '--profile', 'group'])
    assert installed['status'] == 'installed'
    verifier = ROOT.parent/'GitlabWorkSpace/resources/workflow-kit-status.py'
    state = call([sys.executable, '-X', 'utf8', '-B', str(verifier), 'status', str(group), '--expected-version', '0.44.0'])
    assert state['status'] in ('installed', 'update-available') and state['integrity'] == 'verified'
    assert state['version'] == '1.6.0' and 'syntax-context' in state['capabilities']
    bound = call(['node', '-e', NODE, str(group), str(EXTENSION), sys.executable, 'bind'])
    binding = bound['runner']['syntax_analysis']
    capabilities = call([bound['command']['executable'], *bound['command']['args']])
    assert capabilities['engine_sha256'] == binding['engine_sha256']
    assert binding['schema'] == 'SyntaxAnalysisBinding/v1' and capabilities['available']
    assert binding['default_mode'] == capabilities['default_mode'] == 'off'

    project = root / 'wiki-source'
    project.mkdir()
    source = project / 'Program.cs'
    source.write_text('class Program {\n static void Main() {\n  System.Console.WriteLine(1);\n }\n}\n', encoding='utf-8')
    scanner = group / '.agents/skills/codebase-wiki/scripts/project_scanner.py'
    inventory = call([sys.executable, '-X', 'utf8', '-B', str(scanner), '--root', str(project)])
    row = next(item for item in inventory['included'] if item['path'] == 'Program.cs')
    before = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    syntax = call([sys.executable, '-X', 'utf8', '-B', bound['runner']['script_path'], '--',
                   sys.executable, '-X', 'utf8', '-B', binding['script_path'], 'analyze', '--root', str(project),
                   '--path', row['path'], '--expected-source-sha256', row['sha256'],
                   '--snapshot-id', inventory['snapshot_id'], '--expected-engine-sha256', binding['engine_sha256']],
                  {**os.environ, 'WORKFLOW_KIT_SYNTAX_CONTEXT': 'auto'})
    assert syntax['status'] == 'ok' and syntax['semantic_reviewed'] is False
    assert syntax['source']['snapshot_id'] == inventory['snapshot_id']
    assert syntax['source']['content_sha256'] == row['sha256']
    assert syntax['unread_ranges'] == [[1, 5]]
    assert before == {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    after_inventory = call([sys.executable, '-X', 'utf8', '-B', str(scanner), '--root', str(project)])
    assert after_inventory['snapshot_id'] == inventory['snapshot_id']
    query = Path(binding['script_path']).parent/'queries/csharp.scm'
    query.write_bytes(query.read_bytes() + b'\n; tampered fixture\n')
    tamper = call(['node', '-e', NODE, str(group), str(EXTENSION), sys.executable, 'tamper', json.dumps(bound['runner'])])
    report = {'schema':'SyntaxInstalledBindingValidation/v1', 'engine_sha256':binding['engine_sha256'],
              'installed_package_sha256':hashlib.sha256(KIT.read_bytes()).hexdigest(),
              'compiled_extension_binding':True, 'bundled_status_verifier':True, 'wiki_inventory_snapshot_retained':True,
              'wiki_cli_read_only':True, 'wiki_semantic_reviewed':False, 'default_mode':'off', **tamper}
    (ROOT/'.tmp/syntax-final-binding.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
