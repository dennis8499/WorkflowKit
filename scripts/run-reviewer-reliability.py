"""Run blinded, isolated native Reviewer trials with real Codex tools and traces.

Freeze once, then run each variant against the same source-only manifest. The
parent's independent adjudication is deliberately absent from these outputs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def source_rows(root):
    rows = [[p.relative_to(root).as_posix(), sha(p.read_bytes())] for p in root.rglob('*')
            if p.is_file() and not any(x in ('__pycache__', '.git', '.pytest_cache') for x in p.parts) and p.suffix != '.pyc']
    return sorted(rows, key=lambda row: row[0].encode('utf-8'))


def archive(repository, revision, paths, destination):
    raw = subprocess.run(['git', '-C', str(repository), 'archive', revision, *paths], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
        bundle.extractall(destination, filter='data')


def freeze(args):
    target = args.output.resolve()
    if target.exists():
        raise ValueError('Use a fresh engine directory; frozen engines are never overwritten.')
    target.mkdir(parents=True)
    if args.variant == 'baseline':
        archive(PARENT / 'MergeReviewer', args.merge_ref, ['skills/merge-reviewer'], target / 'native')
        archive(ROOT, 'HEAD', ['resources/workflow-kit'], target / 'kit-source')
        archive(PARENT / 'GitlabWorkSpace', 'HEAD', ['src'], target / 'gws')
    else:
        shutil.copytree(PARENT / 'MergeReviewer/skills/merge-reviewer', target / 'native/skills/merge-reviewer',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(ROOT / 'resources/workflow-kit', target / 'kit-source/resources/workflow-kit',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(PARENT / 'GitlabWorkSpace/src', target / 'gws/src')
    # Transpile the frozen TS sources with the existing pinned local compiler.
    compiler = PARENT / 'GitlabWorkSpace/node_modules/typescript'
    script = """const fs=require('fs'),path=require('path'),ts=require(process.argv[1]);
function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true})){const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(p.endsWith('.ts')&&!p.endsWith('.d.ts')){const out=ts.transpileModule(fs.readFileSync(p,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;fs.writeFileSync(p.slice(0,-3)+'.js',out)}}}walk(process.argv[2]);"""
    subprocess.run(['node', '-e', script, str(compiler), str(target / 'gws/src')], check=True)
    skill = target / 'native/skills/merge-reviewer'
    rows = source_rows(skill)
    result = {'schema': 'ReviewerReliabilityEngine/v1', 'variant': args.variant,
              'merge_ref': args.merge_ref if args.variant == 'baseline' else 'working-tree-snapshot',
              'merge_version': (skill / 'VERSION').read_text(encoding='utf-8').strip(),
              'skill_sha256': sha(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()),
              'skill_files': rows, 'engine_files': source_rows(target),
              'kit_version': '1.7.0' if args.variant == 'baseline' else (ROOT / 'VERSION').read_text().strip()}
    save(target / 'engine.json', result)
    return {'engine': str(target), 'variant': args.variant, 'skill_sha256': result['skill_sha256']}


def install_fixture(engine, workspace, metadata):
    """Install only the active frozen components; no network or user installation."""
    kit = engine / 'kit-source/resources/workflow-kit'
    common = workspace / '.agents/gitlab-workspace-kit'
    shutil.copytree(kit / 'common', common)
    for name in ('profile.md', 'group-instructions.md', 'legacy-cleanup.md'):
        shutil.copyfile(kit / name, common / name)
    shutil.copytree(engine / 'native/skills/merge-reviewer', workspace / '.agents/skills/merge-reviewer')
    for name in ('model-routing', 'output-style'):
        shutil.copytree(kit / 'skills' / name, workspace / '.agents/skills' / name)
    (workspace / 'AGENTS.md').write_bytes((kit / 'group-instructions.md').read_bytes())
    # This is a synthetic fixture ownership marker, not a distribution installer.
    files = {'.agents/' + name: digest for name, digest in source_rows(workspace / '.agents')}
    save(workspace / '.gitlab-workspace/tool-manifests/workflow-kit.json',
         {'version': metadata['kit_version'], 'files': files, 'capabilities': ['model-routing', 'syntax-context']})


def resolve_codex(explicit):
    if explicit:
        path = Path(explicit).resolve()
    else:
        script = "const p=require(process.argv[1]);p.resolveCodexExecutable().then(v=>process.stdout.write(v.file)).catch(e=>{console.error(e);process.exitCode=1})"
        output = subprocess.run(['node', '-e', script, str(PARENT / 'GitlabWorkSpace/out/src/codex/process.js')],
                                capture_output=True, text=True, encoding='utf-8', check=True).stdout
        path = Path(output)
    if not path.is_file():
        raise ValueError('Codex native executable is unavailable.')
    return path


def native_draft_started(runtime):
    for draft in runtime.glob('sessions/*/draft.json'):
        try:
            value = json.loads(draft.read_text(encoding='utf-8-sig'))
            if value.get('summary') or value.get('findings') or any(row.get('status') == 'reviewed' for row in value.get('coverage', []) if isinstance(row, dict)):
                return True
        except (OSError, ValueError, TypeError):
            pass
    return False


def run_trial(args, fixture, trial, executable, metadata):
    engine = args.engine.resolve()
    variant = metadata['variant']
    directory = args.output.resolve() / fixture['case'] / variant / f'trial-{trial}'
    if directory.exists():
        raise ValueError(f'Trial already exists; preserve it and choose a new trial number: {directory}')
    directory.mkdir(parents=True)
    # Keep the vendor paths below Windows' legacy 260-character process limit.
    # This is a fresh, recorded fixture only; no existing directory is moved.
    workroot = Path(tempfile.mkdtemp(prefix='rr-')).resolve()
    save(directory / 'isolation.json', {'workroot': str(workroot), 'retained': True, 'fixture_only': True})
    workspace = workroot / 'Project/review workspace'
    shutil.copytree(fixture['workspace'], workspace)
    install_fixture(engine, workspace, metadata)
    runtime = workroot / 'native-runtime'
    request_id = uuid.uuid4().hex
    run_id = uuid.uuid4().hex
    project = workspace / 'service'
    setup = {'engine': str(engine), 'variant': variant, 'workspace': str(workspace), 'project': str(project),
             'base': fixture['base'], 'head': fixture['head'], 'runtime': str(runtime), 'requestId': request_id,
             'python': sys.executable, 'version': metadata['kit_version'], 'effort': args.effort,
             'repositories': [{'name': item.name, 'path': str(item)} for item in sorted(workspace.iterdir()) if (item / '.git').is_dir()]}
    setup_file = directory / 'prompt-input.json'
    save(setup_file, setup)
    built = json.loads(subprocess.run(['node', str(ROOT / 'scripts/reviewer-reliability-prompt.cjs'), str(setup_file)],
                                     capture_output=True, text=True, encoding='utf-8', check=True).stdout)
    guard = (f'\n\nExecution context: routing_adapter=workbench routing_phase=review. The host has selected {args.model} / {args.effort}, manual and fixed. '
             'You are the executing reviewer: complete native capture, semantic review, draft, check, finish and routing completion in this turn. '
             'Use real installed Skill helper tools; do not spawn another reviewer. All branches are local; remain offline. '
             f'Only this isolated fixture root is authorized for output: {workroot}. Preserve all inspected source files and commits. '
             'Read only this fixture and its installed Skills/runtime; do not inspect parent directories or unrelated repositories. '
             'There is no human input during this run. Preserve genuine evidence gaps and actual failures; do not invent coverage or change the rules to force completion. '
             'PowerShell must use UTF-8 and no profile when possible. Do not pipe multilingual Python source through PowerShell. '
             'Do not read evaluation metadata or attempt to discover expected findings. Return the actual report link and native completion state.')
    prompt = built['prompt'] + guard
    (directory / 'prompt.txt').write_text(prompt, encoding='utf-8')
    save(directory / 'binding.json', built['binding'])
    row = {'schema': 'ReviewerReliabilityRun/v1', 'case': fixture['case'], 'variant': variant, 'trial': trial,
           'execution_id': run_id, 'model': args.model, 'effort': args.effort, 'source_identity': fixture['source_identity'],
           'skill_sha256': metadata['skill_sha256'], 'prompt_chars': len(prompt), 'tool_calls': 0, 'tokens': None,
           'first_draft_seconds': None, 'duplicate_document_bytes': 0, 'authoring_retries': 0,
           'status': 'running', 'request_id': request_id, 'workspace': str(workspace), 'runtime': str(runtime),
           'metrics_method': {'prompt_chars': 'Exact product-generated initial prompt plus identical isolation instructions.',
                              'tool_calls': 'Observed item.started tool events.',
                              'duplicate_document_bytes': 'Bytes of identical repeated completed Markdown-read command outputs.',
                              'authoring_retries': 'Observed native check/finish command failures with exit code 3.',
                              'first_draft_seconds': 'First observed nonempty summary/findings or reviewed coverage; null if never observed.'}}
    save(directory / 'run.json', row)
    command = [str(executable), 'exec', '--ignore-user-config', '--ephemeral', '--json',
               '--skip-git-repo-check', '--sandbox', 'workspace-write', '--model', args.model,
               '-c', f'model_reasoning_effort="{args.effort}"', '-c', 'approval_policy="never"',
               '-c', 'windows.sandbox="elevated"', '-c', 'features.prefer_mxc=true',
               '--cd', str(workroot), '--output-last-message', str(directory / 'final.txt'), '-']
    save(directory / 'command.json', {'argv': command, 'sandbox': 'workspace-write', 'approval_policy': 'never'})
    started = time.monotonic()
    raw_path, timeline_path = directory / 'trace.jsonl', directory / 'timeline.jsonl'
    errors = []
    documents = set()
    with raw_path.open('wb') as raw, timeline_path.open('w', encoding='utf-8') as timeline, (directory / 'stderr.log').open('wb') as stderr:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                 cwd=workroot, env={**os.environ, 'WORKFLOW_KIT_SYNTAX_CONTEXT': 'off'}, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        child.stdin.write(prompt.encode('utf-8'))
        child.stdin.close()

        def consume():
            for line in child.stdout:
                raw.write(line); raw.flush()
                elapsed = time.monotonic() - started
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                timeline.write(json.dumps({'seconds': elapsed, 'event': event}, ensure_ascii=False) + '\n'); timeline.flush()
                item = event.get('item', {})
                kind = item.get('type')
                if event.get('type') == 'thread.started':
                    row['thread_id'] = event.get('thread_id')
                if event.get('type') == 'item.started' and kind in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change'):
                    row['tool_calls'] += 1
                if event.get('type') == 'turn.completed' and isinstance(event.get('usage'), dict):
                    row['usage'] = event['usage']
                    row['tokens'] = sum(event['usage'].get(key, 0) for key in ('input_tokens', 'output_tokens'))
                if event.get('type') == 'item.completed' and kind == 'command_execution':
                    command_text, output = item.get('command', ''), item.get('aggregated_output', '')
                    if re.search(r'(Get-Content|read_text|cat |type ).*\.md', command_text, re.I):
                        fingerprint = sha(output.encode('utf-8'))
                        if fingerprint in documents:
                            row['duplicate_document_bytes'] += len(output.encode('utf-8'))
                        documents.add(fingerprint)
                    if item.get('exit_code') == 3 and re.search(r'(review_session\.py.*\b(check|finish)\b|--action\s+(check|finish))', command_text):
                        row['authoring_retries'] += 1
                if event.get('type') in ('error', 'turn.failed'):
                    errors.append(event)

        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        timed_out = False
        while child.poll() is None:
            elapsed = time.monotonic() - started
            if row['first_draft_seconds'] is None and native_draft_started(runtime):
                row['first_draft_seconds'] = elapsed
            if elapsed > args.timeout:
                timed_out = True
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, check=False)
                else:
                    child.terminate()
                break
            time.sleep(.25)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=15)
        reader.join(timeout=15)
    row.update(elapsed_seconds=time.monotonic() - started, exit_code=child.returncode,
               status='timed-out' if timed_out else 'completed' if child.returncode == 0 else 'failed',
               trace_path=str(raw_path), trace_sha256=sha(raw_path.read_bytes()), errors=errors)
    job_path = runtime / 'jobs' / (request_id + '.json')
    if job_path.is_file():
        job = json.loads(job_path.read_text(encoding='utf-8'))
        save(directory / 'native-job.json', job)
        row['native_state'] = job.get('state')
        row['native_outcome'] = job.get('review_outcome') or job.get('report_receipt', {}).get('review_outcome')
        report = Path(job.get('report_path', ''))
        if report.is_file():
            shutil.copyfile(report, directory / 'report.md')
            row['report_path'] = str(directory / 'report.md')
    if row['status'] == 'completed' and row.get('native_state') != 'published':
        row['status'] = 'native-incomplete'
    # Audit all fixed source commits after execution; reports may be untracked.
    drift = []
    for repo in setup['repositories']:
        check = subprocess.run(['git', '-C', repo['path'], 'diff', '--exit-code', 'HEAD'], capture_output=True)
        if check.returncode:
            drift.append(repo['name'])
    row['source_drift'] = drift
    if drift:
        row['status'] = 'source-drift'
    row['adjudication'] = {'verified': False, 'reviewer': None}
    save(directory / 'run.json', row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    frozen = sub.add_parser('freeze')
    frozen.add_argument('--variant', choices=('baseline', 'candidate'), required=True)
    frozen.add_argument('--output', type=Path, required=True)
    frozen.add_argument('--merge-ref', default='baaa033da81e6814bdbf9bf13b16fe801a4d4f6b')
    run = sub.add_parser('run')
    run.add_argument('--manifest', type=Path, required=True)
    run.add_argument('--engine', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--case', action='append')
    run.add_argument('--trial', action='append', type=int)
    run.add_argument('--parallel', type=int, default=2, choices=(1, 2, 3))
    run.add_argument('--model', default='gpt-6-luna')
    run.add_argument('--effort', default='xhigh')
    run.add_argument('--timeout', type=int, default=900)
    run.add_argument('--codex')
    args = parser.parse_args()
    if args.command == 'freeze':
        print(json.dumps(freeze(args), ensure_ascii=False))
        return 0
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    metadata = json.loads((args.engine / 'engine.json').read_text(encoding='utf-8'))
    actual = source_rows(args.engine / 'native/skills/merge-reviewer')
    if actual != metadata['skill_files']:
        raise ValueError('Frozen Reviewer engine changed.')
    selected = [row for row in manifest['cases'] if not args.case or row['case'] in args.case]
    if not selected or args.case and set(args.case) != {row['case'] for row in selected}:
        raise ValueError('Unknown fixture case.')
    executable = resolve_codex(args.codex)
    results = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(run_trial, args, fixture, trial, executable, metadata)
                   for fixture in selected for trial in (args.trial or [1, 2, 3])]
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            print(json.dumps({key: row.get(key) for key in ('case', 'variant', 'trial', 'status', 'elapsed_seconds', 'tool_calls', 'native_state')}, ensure_ascii=False), flush=True)
    save(args.output / (metadata['variant'] + '-runs.json'), results)
    return 0 if all(row['status'] == 'completed' for row in results) else 3


if __name__ == '__main__':
    raise SystemExit(main())
