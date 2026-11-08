"""Run final loader/integrity and all directly affected installed workflows."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path.cwd().resolve()
OUT = ROOT / '.tmp'
sys.path.insert(0, str(ROOT / 'test/release'))
os.environ['WORKFLOW_KIT_TEST_PREDECESSOR_VERSION'] = '1.5.0'
names = [
    'syntax_context_test',
    'release_reviewer_integration_test.ReleaseReviewerIntegrationTests.test_installed_reviewer_payloads_match_pinned_archives',
    'workflow_kit_transactions_test.TransactionTests.test_windows_checkout_and_git_archive_have_identical_bundle_digests',
    'workflow_kit_transactions_test.TransactionTests.test_real_predecessors_upgrade_repeat_and_rollback_from_versioned_fixtures',
    'workflow_kit_installer_test.WorkflowKitInstallerTests.test_bundled_and_external_profiles_install_with_current_native_versions',
    'reviewer_sessions_integration_test.InstalledReviewerSessionTests.test_both_installed_facades_check_resume_publish_retry_and_cancel_independently',
]
suite = unittest.defaultTestLoader.loadTestsFromNames(names)
record = {'schema':'SyntaxFinalImpactedValidation/v1','test_names':names,'expected_tests':suite.countTestCases(),
          'package_sha256':hashlib.sha256((ROOT/'dist/gitlab-workspace-kit-1.6.0.zip').read_bytes()).hexdigest(),
          'engine_sha256':hashlib.sha256((ROOT/'resources/workflow-kit/common/scripts/syntax-context/bundle.json').read_bytes()).hexdigest(),
          'predecessor_filter':'1.5.0','status':'running'}
path=OUT/'syntax-delivery-validation.json'
path.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
started=time.monotonic()
with (OUT/'syntax-delivery-validation.log').open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
record.update(status='passed' if result.wasSuccessful() else 'failed',success=result.wasSuccessful(),tests_run=result.testsRun,
              skipped=len(result.skipped),failures=len(result.failures),errors=len(result.errors),seconds=round(time.monotonic()-started,3))
path.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record))
raise SystemExit(not result.wasSuccessful())
