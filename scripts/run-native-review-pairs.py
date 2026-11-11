"""Alternate frozen native-review variants; stop expansion on a real failed run."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_pair_runner', ROOT / 'scripts/run-reviewer-reliability.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('manifest', 'baseline', 'candidate', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--model', default='gpt-6-luna')
    parser.add_argument('--effort', default='xhigh')
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--case', action='append')
    parser.add_argument('--parallel', type=int, choices=(1, 2), default=1)
    parser.add_argument('--codex')
    args = parser.parse_args()
    metadata = {key: runner.load_engine(getattr(args, key).resolve()) for key in ('baseline', 'candidate')}
    executable = runner.resolve_codex(args.codex)
    sources = json.loads(args.manifest.read_text(encoding='utf-8'))['cases']
    chosen = [row for row in sources if not args.case or row['case'] in args.case]
    if not chosen or args.case and set(args.case) != {row['case'] for row in chosen}:
        raise ValueError('Unknown performance case.')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)

    def paired_case(source):
        rows = []
        for trial in (1, 2, 3):
            order = ('baseline', 'candidate') if trial % 2 else ('candidate', 'baseline')
            for variant in order:
                options = SimpleNamespace(**{**vars(args), 'engine': getattr(args, variant).resolve()})
                row = runner.run_trial(options, source, trial, executable, metadata[variant])
                rows.append(row)
                runner.save(args.output / (source['case'] + '-runs.json'), rows)
                print(json.dumps({key: row.get(key) for key in ('case', 'variant', 'trial', 'status', 'elapsed_seconds', 'tool_calls', 'native_state')}, ensure_ascii=False), flush=True)
                if row['status'] != 'completed':
                    return rows
        return rows

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        groups = list(pool.map(paired_case, chosen))
    rows = [row for group in groups for row in group]
    runner.save(args.output / 'observed-runs.json', rows)
    # A completed model run still needs independent oracle adjudication.
    complete = len(rows) == len(chosen) * 6 and all(row['status'] == 'completed' for row in rows)
    return 0 if complete else 3


if __name__ == '__main__':
    raise SystemExit(main())
