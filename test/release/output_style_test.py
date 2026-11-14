"""Kit-owned Skill resources must be discoverable, complete and safe to package."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("output_style_kit_builder", ROOT / "scripts/build-workflow-kit.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class OutputStylePackageTests(unittest.TestCase):
    def test_both_generated_profiles_keep_workflow_style_loading_explicit(self):
        files = {}
        for source in builder.PINNED_SOURCES:
            if source["id"] not in ("codebase-wiki", "merge-reviewer", "release-reviewer"):
                continue
            selected, _ = builder.checked_zip(builder.SOURCES / source["filename"], source["sha256"])
            if source["id"] == "codebase-wiki":
                files.update({"payload/" + name: data for name, data in selected.items()
                              if name.startswith(".agents/skills/codebase-wiki/")})
            else:
                prefix = source["id"] + "/"
                files.update({"payload/.agents/skills/" + source["id"] + "/" + name[len(prefix):]: data
                              for name, data in selected.items() if name.startswith(prefix)})
        repository = dict(files)
        builder.apply_overlay(files, "codebase-wiki", builder.PROFILE / "overlays/codebase-wiki")
        policies = ("codebase-wiki/SKILL.md", "merge-reviewer/SKILL.md",
                    "merge-reviewer/references/report-style.md", "release-reviewer/references/report-style.md")
        for profile, payload in (("group", files), ("repository", repository)):
            for policy in policies:
                with self.subTest(profile=profile, policy=policy):
                    text = payload["payload/.agents/skills/" + policy].decode("utf-8")
                    self.assertNotIn("$output-style", text)
                    self.assertNotIn("output-style/SKILL.md", text)
                    self.assertRegex(text, r"explicitly requests or selects|只有使用者明確要求或選取")

    def test_packaged_style_requires_explicit_selection_and_preserves_manual_invocation(self):
        resources = builder.kit_skill_files()
        policy = resources[".agents/skills/output-style/agents/openai.yaml"].decode("utf-8")
        self.assertRegex(policy, r"(?m)^policy:\r?\n  allow_implicit_invocation: false\s*$")
        self.assertEqual(policy.count("allow_implicit_invocation:"), 1)
        self.assertRegex(policy, r'(?m)^  default_prompt: ".*\$output-style style=auto')

    def test_source_resources_keep_discoverable_paths_and_resolve_local_links(self):
        resources = builder.kit_skill_files()
        prefix = ".agents/skills/output-style/"
        self.assertTrue({prefix + name for name in ("SKILL.md", "agents/openai.yaml", "references/examples.md")}
                        <= resources.keys())
        for name, data in {key: data for key, data in resources.items() if key.startswith(prefix)}.items():
            self.assertEqual((builder.PROFILE / "skills/output-style" / name[len(prefix):]).read_bytes(), data)
            if name.endswith(".md"):
                for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", data.decode("utf-8")):
                    if "://" in target or target.startswith("#"):
                        continue
                    relative = Path(name).parent / target.split("#", 1)[0]
                    self.assertIn(relative.as_posix(), resources, (name, target))

    def test_missing_entrypoint_and_oversized_resource_fail_before_build(self):
        with tempfile.TemporaryDirectory(prefix="output-style-source-") as temporary:
            profile = Path(temporary)
            skill = profile / "skills/output-style"
            skill.mkdir(parents=True)
            with mock.patch.object(builder, "PROFILE", profile), mock.patch.object(builder, "KIT_SKILLS", ("output-style",)):
                with self.assertRaisesRegex(ValueError, "missing SKILL.md"):
                    builder.kit_skill_files()
                (skill / "SKILL.md").write_text("valid entrypoint", encoding="utf-8")
                with mock.patch.object(builder, "MAX_FILE_BYTES", 3):
                    with self.assertRaisesRegex(ValueError, "exceeds file limit"):
                        builder.kit_skill_files()

    def test_linked_resources_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="output-style-link-") as temporary:
            profile = Path(temporary)
            skill = profile / "skills/output-style"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("entrypoint", encoding="utf-8")
            outside = profile / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            try:
                os.symlink(outside, skill / "linked.md")
            except OSError as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")
            with mock.patch.object(builder, "PROFILE", profile), mock.patch.object(builder, "KIT_SKILLS", ("output-style",)):
                with self.assertRaisesRegex(ValueError, "cannot be links"):
                    builder.kit_skill_files()


if __name__ == "__main__":
    unittest.main(verbosity=2)
