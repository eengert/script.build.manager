"""Guarded macOS offline unittest runner; kernel policy covers every child.

Run from the repository root: python3 -B tools/offline_test_suite.py [modules...]
No product IO is mocked. A disposable canary proves stat/open/enumeration denial
in this interpreter, a subprocess and a multiprocessing-spawn child first.
"""
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
POLICY = '''(version 1)
(allow default)
(deny file-read* file-write*
 (literal "/Applications")
 (subpath "/Applications/Kodi.app")
 (subpath "/Applications/Kodi Build Manager Test.app")
 (subpath "/Users/eengert/Library/Application Support/Kodi")
 (subpath (param "PROBE")))
'''

# Supervisor-authorized local commit validation exception, 2026-10-20.
# These methods remain UNVERIFIED; this is never a full-suite PASS.
PS_ENVIRONMENT_EXCLUSIONS = (
    'tests.test_bm_test_app.TestRealPsAndLsof.test_real_ps_output_for_this_process_parses',
    'tests.test_bm_test_app.TestRealProcessIdentity.test_real_process_with_p_is_identified',
    'tests.test_bm_test_app.TestRealProcessIdentity.test_real_embedded_portable_text_and_option_value_are_refused',
    'tests.test_bm_test_app.TestRealProcessIdentity.test_real_spoofed_argv0_cannot_supply_executable_identity',
    'tests.test_bm_test_app.TestRealProcessIdentity.test_real_process_without_p_is_refused',
    'tests.test_bm_test_app.TestRealProcessIdentity.test_two_real_processes_are_refused',
)


def test_cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_cases(test)
        else:
            yield test


def select_scoped_tests(suite):
    """Fail closed before execution unless all six exact identities occur once."""
    cases = list(test_cases(suite))
    identities = [test.id() for test in cases]
    counts = Counter(identities)
    if len(set(PS_ENVIRONMENT_EXCLUSIONS)) != 6:
        raise ValueError('environmental exception must name six distinct methods')
    invalid = {name: counts[name] for name in PS_ENVIRONMENT_EXCLUSIONS if counts[name] != 1}
    if invalid:
        raise ValueError('absent or duplicated discovery identity: ' + repr(invalid))
    excluded = set(PS_ENVIRONMENT_EXCLUSIONS)
    selected = unittest.TestSuite(test for test in cases if test.id() not in excluded)
    return selected, identities


def probe(path):
    for operation in (os.stat, os.lstat, os.listdir, os.scandir,
                      lambda p: open(p + '/canary', 'rb')):
        try:
            operation(path)
        except PermissionError:
            continue
        raise RuntimeError('offline sandbox canary was accessible')


def guarded_main(canary, names):
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    probe(canary)
    subprocess.run([sys.executable, '-B', __file__, '--probe', canary], check=True)
    child = multiprocessing.get_context('spawn').Process(target=probe, args=(canary,))
    child.start()
    child.join(20)
    if child.is_alive():
        child.terminate()
        child.join()
        raise RuntimeError('sandbox spawn self-check timed out')
    if child.exitcode != 0:
        raise RuntimeError('sandbox spawn self-check failed')
    print('OFFLINE GUARD PASS: parent, subprocess, spawn; stat/lstat/open/enumeration denied', flush=True)
    if names == ['--self-check']:
        return 0
    verbose = bool(names and names[0] == '--verbose')
    if verbose:
        names = names[1:]
    scoped = bool(names and names[0] == '--exclude-ps-environment')
    if scoped:
        names = names[1:]
        if names:
            raise ValueError('environmental exception requires ordinary complete discovery')
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromNames(names) if names else loader.discover('tests', top_level_dir='.')
    discovered = suite.countTestCases()
    if scoped:
        suite, identities = select_scoped_tests(suite)
        print('OFFLINE_DISCOVERY ' + json.dumps(identities), flush=True)
        print('OFFLINE_EXCLUDED_UNVERIFIED ' + json.dumps(PS_ENVIRONMENT_EXCLUSIONS), flush=True)
    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    summary = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   skipped=len(result.skipped))
    if scoped:
        summary.update(discovered=discovered, executed=result.testsRun, excluded=6,
                       failed=len(result.failures), errored=len(result.errors))
    if result.skipped:
        print('OFFLINE_SKIPS ' + json.dumps([
            {"test": test.id(), "reason": reason} for test, reason in result.skipped]), flush=True)
    print('OFFLINE_RESULT ' + json.dumps(summary), flush=True)
    if scoped and result.wasSuccessful() and not result.skipped and result.testsRun == discovered - 6:
        print(f'Guarded broad regression: PASS for {result.testsRun} executed tests, '
              'six explicitly excluded environmental tests UNVERIFIED.', flush=True)
    if scoped and result.testsRun != discovered - 6:
        return 1
    return 0 if result.wasSuccessful() and not result.skipped else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--probe':
        probe(sys.argv[2])
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == '--guarded':
        return guarded_main(sys.argv[2], sys.argv[3:])
    with tempfile.TemporaryDirectory(prefix='bm-offline-guard-', dir='/private/tmp') as tmp:
        canary = Path(tmp) / 'denied'
        canary.mkdir()
        (canary / 'canary').write_text('synthetic guard control')
        policy = Path(tmp) / 'offline.sb'
        policy.write_text(POLICY)
        return subprocess.run(['/usr/bin/sandbox-exec', '-D', 'PROBE=' + str(canary),
            '-f', str(policy), sys.executable, '-B', __file__, '--guarded', str(canary),
            *sys.argv[1:]], cwd=ROOT).returncode


if __name__ == '__main__':
    sys.exit(main())
