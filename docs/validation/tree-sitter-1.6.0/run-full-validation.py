"""Run all discovered release tests in three independent, exhaustive groups."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT / 'test/release'))


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def group(test):
    module = test.id().split('.')[0]
    if module in ('workflow_kit_installer_test', 'workflow_kit_profiles_test'):
        return 1
    if module == 'workflow_kit_transactions_test':
        return 2
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shard', type=int, choices=range(3), required=True)
    args = parser.parse_args()
    discovered = list(flatten(unittest.defaultTestLoader.discover(str(ROOT / 'test/release'), pattern='*_test.py')))
    ids = [test.id() for test in discovered]
    assert len(set(ids)) == len(ids), 'Discovery returned duplicate test IDs'
    selected = [test for test in discovered if group(test) == args.shard]
    path = ROOT / '.tmp' / f'syntax-final-validation-{args.shard}'
    source_rows = [[str(path.relative_to(ROOT)), hashlib.sha256(path.read_bytes()).hexdigest()]
                   for path in sorted((ROOT / 'test/release').glob('*_test.py'))]
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    record = {'all_test_count': len(discovered), 'shard': args.shard, 'selected_test_ids': [test.id() for test in selected],
              'package_sha256': hashlib.sha256((ROOT / f'dist/gitlab-workspace-kit-{version}.zip').read_bytes()).hexdigest(),
              'engine_sha256': hashlib.sha256((ROOT / 'resources/workflow-kit/common/scripts/syntax-context/bundle.json').read_bytes()).hexdigest(),
              'test_sources_sha256': hashlib.sha256(json.dumps(source_rows, separators=(',', ':')).encode()).hexdigest()}
    path.with_suffix('.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    start = time.monotonic()
    with path.with_suffix('.log').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.TestSuite(selected))
    record.update(seconds=round(time.monotonic() - start, 3), tests_run=result.testsRun, failures=len(result.failures),
                  errors=len(result.errors), skipped=len(result.skipped), success=result.wasSuccessful())
    path.with_suffix('.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in record.items() if key != 'selected_test_ids'}))
    raise SystemExit(not result.wasSuccessful())
