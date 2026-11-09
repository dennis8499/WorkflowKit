"""Routing state safety and frozen-source recovery, independent of model quality."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / 'resources/workflow-kit/skills/model-routing'
spec = importlib.util.spec_from_file_location('kit_model_routing', SKILL / 'scripts/routing.py')
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


class ModelRoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='routing-state-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.identifier = 'a' * 32

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def native(self, tool='merge-reviewer'):
        root = self.root / tool
        context = root / 'sessions' / self.identifier
        context.mkdir(parents=True)
        self.write(root / ('.' + tool + '-runtime.json'), {'schema': routing.TOOLS[tool][0], 'directory': str(root)})
        job = {'schema': routing.TOOLS[tool][1], 'request_id': self.identifier, 'runtime_root': str(root),
               'context_dir': str(context), 'draft_path': str(context / 'draft.json'), 'state': 'ready', 'input_digest': 'f' * 64}
        self.write(root / 'jobs' / (self.identifier + '.json'), job)
        manifest = {'repositories': [{'id': 'entry', 'sources': {'base': {'ref': 'b' * 40}, 'head': {'ref': 'c' * 40}}},
                                     {'id': 'peer', 'sources': {'head': {'ref': 'd' * 40}}}]}
        if tool == 'release-reviewer':
            manifest = {'base_sha': 'b' * 40, 'head_sha': 'c' * 40,
                        'repositories': [{'id': 'entry', 'snapshot': {'sources': {'b' * 40: {}, 'c' * 40: {}}}},
                                         {'id': 'peer', 'snapshot': {'sources': {'d' * 40: {}}}}]}
        self.write(context / 'manifest.json', manifest)
        self.write(context / 'draft.json', {'coverage': [{'status': 'not-reviewed'}]})
        return root, context, job

    def command(self, root, command, revision=0, decision=None, effort='auto', model=None, efforts=None):
        decision_path = self.root / 'decision.json'
        if decision is not None:
            self.write(decision_path, decision)
        return routing.operate(SimpleNamespace(command=command, tool=root.name, request_id=self.identifier,
            runtime_root=str(root), effort=effort, revision=revision, decision_file=str(decision_path), model=model, supported_efforts=efforts))

    def test_selected_model_and_sparse_efforts_are_frozen_and_round_trip(self):
        root, _, _ = self.native()
        options = dict(model='fixture-model', efforts=['low', 'high', 'xhigh'])
        state = self.command(root, 'bind', **options)
        self.assertEqual('ReviewModelRouting/v2', state['schema'])
        self.assertEqual(state, self.command(root, 'bind', **options))
        state = self.command(root, 'decide', decision=self.decision('medium'))
        self.assertEqual('high', state['effort'])
        self.assertEqual('medium', state['recommended_effort'])
        self.assertFalse(state['capped'])
        self.assertEqual(state, self.command(root, 'status'))
        with self.assertRaisesRegex(ValueError, 'different model capabilities'):
            self.command(root, 'bind', model='another-model', efforts=options['efforts'])
        with self.assertRaisesRegex(ValueError, 'different model capabilities'):
            self.command(root, 'bind', model='fixture-model', efforts=['low', 'max'])

    def test_auto_caps_and_does_not_add_same_effort_escalations(self):
        root, _, _ = self.native()
        self.command(root, 'bind', model='fixture-model', efforts=['low', 'xhigh'])
        first = self.command(root, 'decide', decision=self.decision('max'))
        self.assertTrue(first['capped'])
        self.assertEqual('xhigh', first['effort'])
        self.assertIn('highest supported', first['reason'])
        result = self.command(root, 'escalate', first['revision'], self.decision('max', 'Recheck affected judgments.'))
        self.assertEqual(1, len(result['history']))
        self.assertEqual('reviewing', result['phase'])
        self.assertEqual(result, self.command(root, 'status'))

    def test_unknown_effort_is_manual_only_and_legacy_bind_remains_v1(self):
        root, _, _ = self.native()
        with self.assertRaisesRegex(ValueError, 'Auto cannot order'):
            self.command(root, 'bind', model='fixture-model', efforts=['custom'])
        state = self.command(root, 'bind', model='fixture-model', efforts=['custom'], effort='custom')
        self.assertEqual('custom', state['effort'])
        self.assertEqual(state, self.command(root, 'status'))
        other, _, _ = self.native('release-reviewer')
        self.assertEqual('ReviewModelRouting/v1', self.command(other, 'bind')['schema'])

    def test_v2_rejects_unsupported_or_tampered_actual_effort(self):
        root, _, _ = self.native()
        with self.assertRaisesRegex(ValueError, 'not supported'):
            self.command(root, 'bind', model='fixture-model', efforts=['high'], effort='max')
        self.command(root, 'bind', model='fixture-model', efforts=['low', 'high'])
        state = self.command(root, 'decide', decision=self.decision('max'))
        state['effort'] = 'low'
        self.write(Path(state['state_path']), state)
        with self.assertRaisesRegex(ValueError, 'does not match model capabilities'):
            self.command(root, 'status')

    def decision(self, effort, checkpoint=''):
        return {'effort': effort, 'reason': 'Fixed evidence establishes this behavior.',
                'evidence': ['entry/head/' + 'c' * 40 + '/app.py:1'], 'checkpoint': checkpoint}

    def test_each_effort_and_both_native_source_formats_bind_without_reviewing(self):
        for tool in routing.TOOLS:
            root, context, _ = self.native(tool)
            before = (context / 'draft.json').read_bytes()
            state = self.command(root, 'bind')
            self.assertEqual('routing', state['phase'])
            self.assertIsNone(state['effort'])
            state = self.command(root, 'decide', decision=self.decision('low'))
            for effort in routing.EFFORTS[1:]:
                state = self.command(root, 'escalate', state['revision'], self.decision(effort, 'Recheck the changed caller.'))
            self.assertEqual(list(routing.EFFORTS), [item['effort'] for item in state['history']])
            self.assertEqual(before, (context / 'draft.json').read_bytes())
            self.assertEqual(state, self.command(root, 'status'))

    def test_manual_override_is_fixed_and_rebind_is_idempotent(self):
        root, _, _ = self.native()
        first = self.command(root, 'bind', effort='medium')
        self.assertEqual(first, self.command(root, 'bind', effort='medium'))
        with self.assertRaisesRegex(ValueError, 'different effort'):
            self.command(root, 'bind', effort='auto')
        with self.assertRaisesRegex(ValueError, 'Manual effort'):
            self.command(root, 'escalate', decision=self.decision('max', 'Recheck all data paths.'))

    def test_windows_utf8_bom_decision_files_preserve_unicode(self):
        root, _, _ = self.native()
        self.command(root, 'bind')
        decision = self.decision('high')
        decision['reason'] = '固定證據顯示一般程式變更。'
        decision_path = self.root / 'decision.json'
        decision_path.write_text(json.dumps(decision, ensure_ascii=False), encoding='utf-8-sig')
        result = self.command(root, 'decide')
        self.assertEqual(decision['reason'], result['reason'])

    def test_revision_and_exact_retry_prevent_repeated_escalation(self):
        root, _, _ = self.native()
        self.command(root, 'bind')
        decision = self.decision('high')
        first = self.command(root, 'decide', decision=decision)
        self.assertEqual(first, self.command(root, 'decide', decision=decision))
        with self.assertRaisesRegex(ValueError, 'revision conflict'):
            self.command(root, 'escalate', 0, self.decision('xhigh', 'Recheck the contract.'))
        for effort in ('low', 'high'):
            with self.assertRaisesRegex(ValueError, 'strictly higher'):
                self.command(root, 'escalate', 1, self.decision(effort, 'Recheck the contract.'))

    def test_mutable_ledgers_do_not_invalidate_but_peer_source_changes_do(self):
        for tool in routing.TOOLS:
            root, context, _ = self.native(tool)
            original = self.command(root, 'bind')
            manifest = json.loads((context / 'manifest.json').read_text(encoding='utf-8'))
            manifest['operations'] = {'read-1': {'status': 'saved'}}
            self.write(context / 'manifest.json', manifest)
            self.assertEqual(original['snapshot_hash'], self.command(root, 'status')['snapshot_hash'])
            peer = manifest['repositories'][1]
            if tool == 'merge-reviewer':
                peer['sources']['head']['ref'] = 'e' * 40
            else:
                peer['snapshot']['sources'] = {'e' * 40: {}}
            self.write(context / 'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'Frozen source identity changed'):
                self.command(root, 'status')

    def test_assessment_cannot_publish_and_cancelled_jobs_cannot_dispatch(self):
        root, _, job = self.native()
        self.command(root, 'bind')
        with self.assertRaisesRegex(ValueError, 'published native review'):
            self.command(root, 'complete')
        job['state'] = 'cancelled'
        self.write(root / 'jobs' / (self.identifier + '.json'), job)
        with self.assertRaisesRegex(ValueError, 'not resumable'):
            self.command(root, 'decide', decision=self.decision('high'))
        with self.assertRaisesRegex(ValueError, 'not resumable'):
            self.command(root, 'bind')

    def test_invalid_checkpoint_does_not_commit_an_unreadable_record(self):
        root, _, _ = self.native()
        original = self.command(root, 'bind')
        decision = self.decision('high')
        decision['checkpoint'] = {'unexpected': 'shape'}
        with self.assertRaisesRegex(ValueError, 'Decision needs'):
            self.command(root, 'decide', decision=decision)
        self.assertEqual(original, self.command(root, 'status'))

    def test_completion_preserves_native_incomplete_outcome_after_cleanup(self):
        root, context, job = self.native()
        self.command(root, 'bind', effort='high')
        job.update(state='published', report_path=str(self.root / 'report.md'),
                   review_outcome={'review_complete': False, 'gaps': ['Missing consumer evidence.']})
        self.write(root / 'jobs' / (self.identifier + '.json'), job)
        for path in context.iterdir():
            path.unlink()
        context.rmdir()
        result = self.command(root, 'complete')
        self.assertEqual('complete', result['phase'])
        self.assertFalse(result['review_outcome']['review_complete'])
        self.assertEqual(result, self.command(root, 'status'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
