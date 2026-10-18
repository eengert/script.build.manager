"""Cross-consumer single-root identity and no-overwrite regressions."""
import io
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

from resources.lib.addon_zip import validated_root, extract_package, publish_package, AddonZipError
from resources.lib.addons import _validate_addon_zip, _staged_install, RepositoryPackage
from resources.lib.artifacts import validate_addon_zip
from resources.lib.repository import validate_repository_zip, _extract_zip_to_directory
from resources.lib.frozen_install import _repository_required_addon_ids, _repository_package_required_dependencies
from resources.lib.dependencies import KodiRuntimeDependencyBackend

ID = 'repository.fixture'
XML = f'<addon id="{ID}" version="1.0.0"><extension point="xbmc.addon.repository"/></addon>'.encode()


def archive(entries=None):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(stream, 'w') as z:
            for name, value in entries or [('alternate/addon.xml', XML), ('alternate/sub/file', b'original')]:
                z.writestr(name, value)
    return stream.getvalue()


class PackageContract(unittest.TestCase):
    def readers(self, data):
        return [
            lambda: validated_root(data, ID, '1.0.0'),
            lambda: _validate_addon_zip(data, ID, '1.0.0'),
            lambda: validate_addon_zip(data, expected_addon_id=ID, expected_version='1.0.0'),
            lambda: validate_repository_zip(data, ID),
            lambda: _repository_required_addon_ids(None, packages=(RepositoryPackage(ID, 'repository.source', '1.0.0', data),)),
            lambda: _repository_package_required_dependencies(RepositoryPackage(ID, 'repository.source', '1.0.0', data), SimpleNamespace(nodes={}), {}, frozenset()),
        ]

    def test_id_and_alternate_roots_agree_across_readers(self):
        for root in (ID, 'alternate'):
            data = archive([(root+'/addon.xml', XML)])
            for reader in self.readers(data):
                reader()
            self.assertEqual(validated_root(data, ID).root, root)

    def test_runtime_dependency_metadata_uses_verified_root(self):
        data = archive()
        with patch('resources.lib.addons.KodiRuntimeAddonBackend') as owner, patch('resources.lib.addons._fetch_bytes', return_value=data):
            owner.return_value._resolve_package_url.return_value = ('https://example.test/pinned.zip', '1.0.0')
            self.assertEqual(KodiRuntimeDependencyBackend().read_available_addon_xml(ID), XML)

    def test_malicious_packages_fail_across_all_readers_and_writers(self):
        symlink = zipfile.ZipInfo('alternate/link'); symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        fifo = zipfile.ZipInfo('alternate/pipe'); fifo.external_attr = (stat.S_IFIFO | 0o600) << 16
        cases = [
            [('addon.xml', XML)],
            [('alternate/addon.xml', XML), ('other/x', b'x')],
            [('alternate/addon.xml', XML), ('alternate/addon.xml', XML)],
            [('alternate/addon.xml', XML), ('alternate/../escape', b'x')],
            [('alternate/addon.xml', XML), ('/absolute/x', b'x')],
            [('alternate/addon.xml', XML), ('alternate\\evil', b'x')],
            [('alternate/addon.xml', XML), ('alternate/C:/x', b'x')],
            [('alternate/addon.xml', XML), ('alternate/a', b'x'), ('alternate/a/b', b'y')],
            [('alternate/addon.xml', XML), ('alternate/X/a', b'x'), ('alternate/x/b', b'y')],
            [('alternate/addon.xml', XML), ('alternate/e\u0301', b'x'), ('alternate/é', b'y')],
            [('alternate/addon.xml', XML), (symlink, b'outside')],
            [('alternate/addon.xml', XML), (fifo, b'')],
            [('alternate/addon.xml', XML.replace(ID.encode(), b'repository.other'))],
            [('alternate/addon.xml', XML.replace(b'1.0.0', b''))],
            [('alternate/addon.xml', b'<broken')],
            [('alternate/addon.xml', b'<!DOCTYPE addon [<!ENTITY x "bad">]>'+XML)],
        ]
        for index, entries in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as temp:
                data = archive(entries); root = Path(temp).resolve()
                for reader in self.readers(data):
                    with self.assertRaises(Exception):
                        reader()
                for writer in (lambda: extract_package(data, ID, root/'extract'),
                               lambda: publish_package(data, ID, root/ID),
                               lambda: _extract_zip_to_directory(data, ID, root/'legacy'),
                               lambda: _staged_install(data, ID, root)):
                    with self.assertRaises(Exception):
                        writer()
                self.assertEqual(list(root.iterdir()), [])

    def test_version_mismatch_and_byte_entry_limits(self):
        with self.assertRaises(AddonZipError):
            validated_root(archive(), ID, '2.0.0')
        with self.assertRaises(AddonZipError):
            validated_root(b'x'*(100*1024**2+1), ID)
        data = archive([('alternate/addon.xml', XML)] + [(f'alternate/{i}', b'') for i in range(20000)])
        with self.assertRaises(AddonZipError):
            validated_root(data, ID)

    def test_alternate_root_publishes_complete_original_files_under_verified_id(self):
        data = archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            _staged_install(data, ID, root)
            self.assertEqual((root/ID/'addon.xml').read_bytes(), XML)
            self.assertEqual((root/ID/'sub/file').read_bytes(), b'original')
            self.assertEqual([p.name for p in root.iterdir()], [ID])

    def test_existing_empty_directory_file_and_symlink_are_never_replaced(self):
        for kind in ('directory', 'file', 'symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve(); target = root/ID
                if kind == 'directory': target.mkdir()
                elif kind == 'file': target.write_bytes(b'owner')
                else: target.symlink_to(root/'absent')
                before = target.lstat()
                with self.assertRaises(OSError): publish_package(archive(), ID, target)
                self.assertEqual(target.lstat().st_ino, before.st_ino)
                self.assertEqual([p.name for p in root.iterdir()], [ID])

    def test_destination_race_preserves_new_owner_and_cleans_only_our_stage(self):
        from resources.lib.addon_zip import _rename_exclusive
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            def race(parent, source, target):
                (root/ID).mkdir(); (root/ID/'owner').write_bytes(b'keep')
                return _rename_exclusive(parent, source, target)
            with patch('resources.lib.addon_zip._rename_exclusive', side_effect=race), self.assertRaises(OSError):
                publish_package(archive(), ID, root/ID)
            self.assertEqual((root/ID/'owner').read_bytes(), b'keep')
            self.assertEqual([p.name for p in root.iterdir()], [ID])

    def test_symlink_ancestor_and_nonempty_extraction_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); outside=root/'outside'; outside.mkdir()
            link=root/'link';link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError): publish_package(archive(), ID, link/ID)
            with self.assertRaises(OSError): extract_package(archive(), ID, link/'extract')
            self.assertEqual(list(outside.iterdir()), [])
            (outside/'owner').write_bytes(b'keep')
            with self.assertRaises(AddonZipError): extract_package(archive(), ID, outside)
            self.assertEqual((outside/'owner').read_bytes(), b'keep')

    def test_midwrite_failure_has_no_final_target_and_cleans_owned_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with patch('resources.lib.addon_zip._write', side_effect=OSError('synthetic I/O')), self.assertRaises(OSError):
                publish_package(archive(), ID, root/ID)
            self.assertEqual(list(root.iterdir()), [])
