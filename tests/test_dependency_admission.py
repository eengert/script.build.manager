"""Managed minimum admission never treats parse failure as satisfaction."""
from types import SimpleNamespace
import unittest
from resources.lib.dependencies import (_dependency_version_satisfies as admits,
    _strict_version_satisfies, _version_satisfies, _admission_max_requirement,
    DependencyResolver, DependencyStatus)
from resources.lib.addons import RepositoryPackage
from resources.lib.frozen_install import _repository_package_required_dependencies, FrozenInstallValidationError
from tests.test_dependencies import FakeDependencyBackend, _xml, _imp, _info
from tests.test_addon_zip_contract import archive


class DependencyAdmission(unittest.TestCase):
    def test_acquired_suffix_edges(self):
        for actual, minimum in [('0.0.6+matrix.1','0.0.6+matrix.1'),
                                ('6.1.0+matrix.3','6.1.0+matrix.3'),
                                ('2.2.3','1.26.16+matrix.1'),
                                ('1.16.0+matrix.1','1.14.0+matrix.1')]:
            with self.subTest(actual=actual,minimum=minimum):
                self.assertTrue(admits(actual, minimum))

    def test_lower_malformed_and_incomparable_versions_are_denied(self):
        for actual, minimum in [('0.0.1','0.0.6+matrix.1'),('1.26.15','1.26.16+matrix.1'),
                                ('6.0.9','6.1.0+matrix.3'),('1.13.9','1.14.0+matrix.1'),
                                ('0.0.6','0.0.6+matrix.1'),('1.0+matrix.2','1.0+matrix.1'),
                                ('1.0+matrix.1','1.0+matrix.2'),('wat','1.0'),('1.0','wat'),
                                ('1.0+omega.1','1.0'),(' 1.0','1.0'),('01.0','1.0'),
                                ('1.0+matrix.x','1.0'),('', ''),(None,'1.0'),('1.0', None)]:
            with self.subTest(actual=actual, minimum=minimum):
                self.assertFalse(admits(actual, minimum))

    def test_plain_numeric_workflows_and_platform_rule_preserved(self):
        self.assertTrue(admits('2.0.0', '1.9'))
        self.assertTrue(admits('1.0', '1.0.0'))
        self.assertTrue(admits('1.0+matrix.1', '1.0'))
        self.assertFalse(admits('1.0', '1.0.1'))
        self.assertTrue(_version_satisfies('unparsed', '1.0'))  # Legacy utility unchanged.
        self.assertFalse(_strict_version_satisfies('1.0+matrix.1','1.0'))
        self.assertFalse(_strict_version_satisfies('1.0','1.0+matrix.1'))

    def test_conjunction_does_not_drop_suffix_or_malformed_requirement(self):
        for a,b in [('0.0.1','0.0.6+matrix.1'),('1.0','malformed'),('1.0+matrix.1','1.0+matrix.2')]:
            left = _admission_max_requirement(a,b); right = _admission_max_requirement(b,a)
            self.assertEqual(left, right)
            self.assertFalse(admits('0.0.1', left))

    def test_real_resolver_denies_bad_versions_before_install_or_enable(self):
        for actual, minimum in [('0.0.1','0.0.6+matrix.1'),('1.26.15','1.26.16+matrix.1'),('wat','1.0')]:
            backend = FakeDependencyBackend(installed={'dep':_info('dep', version=actual)},
                addon_xmls={'root':_xml('root', requires=_imp('dep',minimum)), 'dep':_xml('dep')})
            closure = DependencyResolver(backend).resolve_closure(['root'])
            self.assertEqual(closure.nodes[0].status, DependencyStatus.VERSION_INSUFFICIENT)
            self.assertEqual(backend.set_enabled_calls, [])

    def test_duplicate_and_multipath_requirements_cannot_drop_unsupported_minimum(self):
        for requirements in [(_imp('dep','1.0')+_imp('dep','wat')),(_imp('dep','wat')+_imp('dep','1.0'))]:
            backend = FakeDependencyBackend(installed={'dep':_info('dep',version='2.0')},
                addon_xmls={'root':_xml('root',requires=requirements)})
            self.assertEqual(DependencyResolver(backend).resolve_closure(['root']).nodes[0].status,
                             DependencyStatus.VERSION_INSUFFICIENT)
        backend = FakeDependencyBackend(installed={'dep':_info('dep',version='2.0')},
            addon_xmls={'a':_xml('a',requires=_imp('dep','1.0')), 'b':_xml('b',requires=_imp('dep','wat')), 'dep':_xml('dep')})
        self.assertEqual(DependencyResolver(backend).resolve_closure(['a','b']).nodes[0].status,
                         DependencyStatus.VERSION_INSUFFICIENT)

    def test_frozen_repository_preexecution_uses_strict_managed_admission(self):
        xml = _xml('repository.fixture', requires=_imp('dep', '1.26.16+matrix.1'))
        data = archive([('alternate/addon.xml',xml)])
        package=RepositoryPackage('repository.fixture','repository.source','1.0.0',data)
        for actual in ('1.26.15','wat','2.2.3'):
            node=SimpleNamespace(version=actual,is_absent_optional_dependency=False,platform_provided=False)
            if actual == '2.2.3':
                self.assertEqual(_repository_package_required_dependencies(package,SimpleNamespace(nodes={'dep':node}),{},frozenset()),('dep',))
            else:
                with self.assertRaises(FrozenInstallValidationError):
                    _repository_package_required_dependencies(package,SimpleNamespace(nodes={'dep':node}),{},frozenset())
