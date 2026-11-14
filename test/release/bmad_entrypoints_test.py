"""The simplified entry layer is kit-owned and does not replace native BMAD."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bmad_entry_builder', ROOT / 'scripts/build-workflow-kit.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BmadEntrypointsTests(unittest.TestCase):
    def test_packaged_entries_share_the_same_registry_and_keep_native_pins(self):
        registry_path = ROOT / 'resources/workflow-kit/common/references/bmad-entrypoints.json'
        registry = json.loads(registry_path.read_text(encoding='utf-8'))
        self.assertEqual('workflowkit-bmad-entrypoints/v1', registry['schema'])
        self.assertEqual(['goal', 'plan', 'build', 'verify', 'project'], [entry['id'] for entry in registry['entries']])
        self.assertEqual(3, len(registry['operations']))
        files = builder.kit_skill_files()
        self.assertTrue({'.agents/skills/wk-' + entry['id'] + '/SKILL.md' for entry in registry['entries']} <= files.keys())
        self.assertFalse(any(path.startswith('.agents/skills/bmad-') for path in files))
        self.assertEqual('6.12.4', next(source['version'] for source in builder.PINNED_SOURCES if source['id'] == 'bmad-method'))
        workspace_registry = ROOT.parent / 'GitlabWorkSpace/resources/bmad/entrypoints.json'
        if workspace_registry.is_file():
            self.assertEqual(registry, json.loads(workspace_registry.read_text(encoding='utf-8')))

    def test_external_profiles_keep_the_router_but_do_not_claim_verified_native_capabilities(self):
        version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
        with zipfile.ZipFile(ROOT / f'dist/gitlab-workspace-kit-{version}.zip') as archive:
            manifest = json.loads(archive.read('workflow-kit/manifest.json'))
        for profile in ('group', 'repository'):
            bundled = manifest['profiles'][profile]
            self.assertIn('bmad-entrypoints', bundled['capabilities'])
            external = bundled['variants']['external']
            self.assertNotIn('bmad-workflow', external['capabilities'])
            self.assertNotIn('bmad-entrypoints', external['capabilities'])
            self.assertTrue({'wk-goal', 'wk-plan', 'wk-build', 'wk-verify', 'wk-project'} <= set(external['skills']))
            self.assertFalse(any(name.startswith('bmad-') for name in external['skills']))


if __name__ == '__main__':
    unittest.main()
