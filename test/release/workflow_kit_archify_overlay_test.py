"""Verify the Wiki overlay's Windows hard-link denial fallback and no-clobber move."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

import workflow_kit_installer_test as harness


ROOT = harness.ROOT
WIKI_SOURCE = harness.CURRENT_SOURCES["codebase-wiki"]
ARCHIVE = ROOT / "resources/offline-tools/sources" / WIKI_SOURCE["filename"]
OVERLAY = (ROOT / "resources/workflow-kit/overlays/archify-no-hardlink/.agents/skills/"
           "codebase-wiki/vendor/archify/renderers/shared/atomic-output.mjs")
PREFIX = WIKI_SOURCE["entryRoot"] + "/.agents/skills/codebase-wiki/vendor/archify/renderers/shared/"


class ArchifyAtomicOverlayTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Release CI provides Node.js for Wiki visualization checks.")
    def test_windows_no_replace_move_replaces_outputs_after_hard_link_denial(self):
        with tempfile.TemporaryDirectory(prefix="kit-archify-overlay-") as temporary:
            base = Path(temporary)
            shared = base / "shared"
            shared.mkdir()
            with zipfile.ZipFile(ARCHIVE) as bundle:
                for name in bundle.namelist():
                    if name.startswith(PREFIX) and name.endswith(".mjs"):
                        relative = Path(*name[len(PREFIX):].split("/"))
                        target = shared / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(bundle.read(name))
            shutil.copyfile(OVERLAY, shared / "atomic-output.mjs")

            runner = base / "fallback-check.mjs"
            runner.write_text(r'''import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const api = await import(pathToFileURL(path.resolve(process.argv[2])));
const root = path.resolve(process.argv[3]);
fs.mkdirSync(root, { recursive: true });
const target = path.join(root, 'diagram.html');
const originalLink = fs.linkSync;
let attempts = 0;
let injectLateClaim = false;
fs.linkSync = (source, destination) => {
  attempts += 1;
  if (injectLateClaim && path.resolve(destination) === target && !fs.existsSync(destination)) {
    fs.writeFileSync(destination, 'late claimant\n');
  }
  const error = new Error('simulated sandbox hard-link denial');
  error.code = 'EPERM';
  throw error;
};

function publish(candidate, output, contents) {
  fs.writeFileSync(candidate, contents);
  const captured = api.captureAtomicOutput(output);
  if (captured.status !== 'captured') throw new Error(JSON.stringify(captured));
  const binding = api.captureRegularFileBinding(candidate, { subject: 'test-candidate' });
  if (binding.status !== 'captured') throw new Error(JSON.stringify(binding));
  try {
    return api.publishRegularFileBinding(binding.binding, candidate, captured.snapshot, {
      subject: 'test-output',
    });
  } finally {
    const released = api.releaseRegularFileBinding(binding.binding);
    if (released.status !== 'released') throw new Error(JSON.stringify(released));
  }
}

try {
  const first = publish(path.join(root, 'candidate-first'), target, 'first\n');
  if (first.status !== 'committed' || fs.readFileSync(target, 'utf8') !== 'first\n') {
    throw new Error(JSON.stringify(first));
  }
  const replacement = publish(path.join(root, 'candidate-replacement'), target, 'replacement\n');
  if (replacement.status !== 'committed' || fs.readFileSync(target, 'utf8') !== 'replacement\n') {
    throw new Error(JSON.stringify(replacement));
  }

  injectLateClaim = true;
  const raced = publish(path.join(root, 'candidate-raced'), target, 'must not overwrite\n');
  const recovery = raced.recoveryFile;
  if (raced.status === 'committed'
      || fs.readFileSync(target, 'utf8') !== 'late claimant\n'
      || fs.readFileSync(path.join(root, 'candidate-raced'), 'utf8') !== 'must not overwrite\n'
      || !recovery || fs.readFileSync(recovery, 'utf8') !== 'replacement\n') {
    throw new Error(JSON.stringify(raced));
  }
  console.log(JSON.stringify({
    first: first.status,
    replacement: replacement.status,
    lateClaimPreserved: fs.readFileSync(target, 'utf8').trim(),
    candidatePreserved: fs.existsSync(path.join(root, 'candidate-raced')),
    recoveryPreserved: fs.existsSync(recovery),
    hardLinkAttempts: attempts,
  }));
} finally {
  fs.linkSync = originalLink;
}
''', encoding="utf-8")
            output_root = base / "output with spaces"
            result = subprocess.run(
                [shutil.which("node"), str(runner), str(shared / "atomic-output.mjs"), str(output_root)],
                cwd=ROOT,
                env={**os.environ, "TEMP": str(base), "TMP": str(base), "TMPDIR": str(base)},
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=60,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
            self.assertIn('"first":"committed"', result.stdout)
            self.assertIn('"replacement":"committed"', result.stdout)
            self.assertIn('"lateClaimPreserved":"late claimant"', result.stdout)
            self.assertIn('"candidatePreserved":true', result.stdout)
            self.assertIn('"recoveryPreserved":true', result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
