"""A formal release can differ from an earlier reviewed same-version candidate."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'test/fixtures/formal-workflow-kit-1.9.0'
spec = importlib.util.spec_from_file_location('formal_predecessor_installer', ROOT / 'resources/workflow-kit-installer.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class FormalPredecessorIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provenance = json.loads((FIXTURE / 'provenance.json').read_text(encoding='utf-8'))
        for name, expected in cls.provenance['fixtureFiles'].items():
            if hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() != expected:
                raise AssertionError('Formal predecessor fixture changed: ' + name)
        cls.manifest = json.loads((FIXTURE / 'manifest.json').read_text(encoding='utf-8'))

    def installed_record(self, profile, mode):
        fields = self.manifest['profiles'][profile]
        if mode == 'external':
            fields = fields['variants']['external']
        record = {'version': '1.9.0', 'profile': profile, 'bmadMode': mode,
                  'payloadSha256': fields['payloadSha256'], 'overlays': fields['overlays'],
                  'upstream': {k: v for k, v in self.manifest['upstream'].items()
                               if mode != 'external' or k != 'bmad-method'},
                  'files': dict(fields['files']), 'installedRoot': str(ROOT / 'formal-upgrade-fixture')}
        if mode == 'bundled':
            payload = {'_bmad/config.toml': (FIXTURE / 'bmad-config.toml').read_bytes(),
                       '_bmad/_config/files-manifest.csv': (FIXTURE / 'bmad-files-manifest.csv').read_bytes()}
            installer.configure_bmad_payload(payload, Path(record['installedRoot']).name)
            record['files'].update({name: hashlib.sha256(data).hexdigest() for name, data in payload.items()})
        return record

    def test_all_four_formal_release_variants_are_authenticated_for_upgrade(self):
        self.assertEqual('943d249d86a5f10ca38e7da07ade691decdc1b2d', self.provenance['sourceSha'])
        for profile in ('group', 'repository'):
            for mode in ('bundled', 'external'):
                with self.subTest(profile=profile, mode=mode):
                    record = self.installed_record(profile, mode)
                    reviewed = installer.trusted_package(record)
                    self.assertEqual(record['payloadSha256'], reviewed['payloadSha256'])
                    self.assertEqual(mode, reviewed['bmadMode'])
                    self.assertEqual(record['upstream'], reviewed['upstream'])

    def test_formal_predecessor_identity_does_not_accept_modified_skill_hashes(self):
        record = copy.deepcopy(self.installed_record('repository', 'external'))
        skill = next(name for name in record['files'] if name.startswith('.agents/skills/merge-reviewer/'))
        record['files'][skill] = '0' * 64
        with self.assertRaises(installer.KitError):
            installer.trusted_package(record)

    def test_reviewed_same_version_candidate_identities_are_preserved(self):
        expected = {'d15329d0cf9b51edfdd890cd91a0723e2a29d4322b2770fd3431cc38f602ba27',
                    'bc00a29bb705122e79f6fb21968b07ff41d5c04550713b8375fffdfe385aaf5a',
                    '40fd9381e765f67eea5ddd4f2ee2398475a9404efe416b7b227678373cf861af',
                    'd6605ad6f8bcf39473aee7a2c4fd0ff64415e476708305097911a6e0b84c4d63'}
        observed = {row['payloadSha256'] for row in installer.TRUSTED_PREDECESSORS['packages'] if row['version'] == '1.9.0'}
        self.assertLessEqual(expected, observed)


if __name__ == '__main__':
    unittest.main()
