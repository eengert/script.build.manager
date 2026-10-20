"""Bounded evidence for the unresolved legacy recovery/admission ordering conflict."""
import ast
from contextlib import ExitStack
from dataclasses import replace
import io
import json
import subprocess
import unittest
import zipfile
from unittest.mock import patch
from resources.lib import frozen_install as fi
from tests import test_frozen_resolution as legacy


class LegacyRecoveryOrderingTests(unittest.TestCase):
    def test_missing_exact_replacement_cannot_be_bound_before_legacy_mutations(self):
        baseline_source = subprocess.run(['git', 'show',
            '84f524a1a298bda520e241ff1e0ba99c244ac76f:resources/lib/frozen_install.py'],
            check=True, capture_output=True, text=True).stdout
        functions = {}
        for node in ast.parse(baseline_source).body:
            if isinstance(node, ast.FunctionDef) and node.name in (
                    '_validate_frozen_manifest_core', 'verify_platform_requirements'):
                namespace = dict(fi.__dict__)
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<rejected baseline>', 'exec'), namespace)
                functions[node.name] = namespace[node.name]
        old_class = next(n for n in ast.parse(baseline_source).body
                         if isinstance(n, ast.ClassDef) and n.name == 'FrozenInstallCoordinator')
        old_install = next(n for n in old_class.body if isinstance(n, ast.FunctionDef) and n.name == 'install')
        namespace = dict(fi.__dict__)
        exec(compile(ast.Module(body=[old_install], type_ignores=[]), '<rejected baseline install>', 'exec'), namespace)
        namespace.update(functions)
        rows = {}
        for label in ('baseline', 'candidate'):
            case = legacy.FrozenResolutionTest()
            case.setUp()
            try:
                m = case._manifest(repository_id=legacy.REPOSITORY)
                umbrella = next(n for n in m.addons if n.addon_id == legacy.UMBRELLA)
                # Faithful XML/edges, so this is independent of old fixture defects.
                imports = ''.join('<import addon="%s" version="%s" optional="%s"/>' %
                    (e.addon_id, e.min_version, str(e.optional).lower()) for e in umbrella.dependency_edges)
                data = io.BytesIO()
                with zipfile.ZipFile(data, 'w') as archive:
                    archive.writestr(umbrella.addon_id + '/addon.xml',
                        '<addon id="%s" version="%s"><requires>%s</requires></addon>' %
                        (umbrella.addon_id, umbrella.version, imports))
                metadata = case.artifacts.import_zip(data.getvalue(),
                    expected_addon_id=umbrella.addon_id, expected_version=umbrella.version)
                m = replace(m, addons=tuple(replace(n, artifact=metadata) if n.addon_id == umbrella.addon_id
                                           else n for n in m.addons))
                case.backend.repository_packages[(legacy.REPOSITORY, legacy.YOUTUBE)] = (
                    '8.2.1', legacy._zip(legacy.YOUTUBE, '8.2.1'))
                events = []
                resolver = case.backend.resolve_repository_current
                def resolve(*args):
                    events.append(dict(transaction_present=case.install_store.inspect() is not None,
                        updater=case.policy.policy.value,
                        installed=list(case.backend.install_calls)))
                    return resolver(*args)
                with ExitStack() as stack:
                    if label == 'baseline':
                        stack.enter_context(patch.object(fi.FrozenInstallCoordinator, 'install', namespace['install']))
                        for name, function in functions.items():
                            stack.enter_context(patch.object(fi, name, function))
                    stack.enter_context(patch.object(case.backend, 'resolve_repository_current', side_effect=resolve))
                    result = case._coordinator(decider=lambda _: legacy.ResolutionChoice.INSTALL_CURRENT).install(
                        m, manifest_path='/synthetic.json', device_profile_id='synthetic',
                        install_policies=(case._policy(legacy.REPOSITORY),))
                rows[label] = dict(outcome=result.outcome, code=result.code, acquisition_boundary=events,
                                   policy_calls=len(case.policy.calls), installs=list(case.backend.install_calls))
            finally:
                case.tearDown()
        print('LEGACY_ORDERING_EVIDENCE ' + json.dumps(rows), flush=True)
        self.assertEqual('complete', rows['baseline']['outcome'])
        self.assertTrue(rows['baseline']['acquisition_boundary'][0]['transaction_present'])
        self.assertTrue(rows['baseline']['acquisition_boundary'][0]['installed'])
        self.assertEqual('preparation_required', rows['candidate']['outcome'])
        self.assertEqual('PREPARATION_REQUIRED', rows['candidate']['code'])
        self.assertEqual([], rows['candidate']['installs'])
        self.assertEqual(0, rows['candidate']['policy_calls'])
