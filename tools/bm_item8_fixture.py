"""Offline, explicitly authored Item 8 inputs. Never capture or runtime authority.

This module is deliberately not imported by product code. Only the pinned public
archive is admitted. Output is a NEW directory directly under /private/tmp;
incomplete output is retained and never reused or automatically removed.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resources.lib.artifacts import ArtifactStore, validate_addon_zip
from resources.lib.build_library import BuildLibrary, _directory, _read_at
from resources.lib.create_capture import PreparedPublicBundle
from resources.lib.frozen import (AddonCaptureNode, CaptureStatus, DependencyEdge,
                                 FrozenBuildManifest, ProvenanceStatus)
from resources.lib.frozen_install import validate_frozen_install_plan
from resources.lib.private_overlay import PrivateOverlay, PrivateOverlayStore, validate_private_overlay
from resources.lib.private_resource import StructuredPrivateResourceOverlay, StructuredPrivateValue
from resources.lib.redlight_resource import redlight_declaration
from resources.lib.resolver import resolve_manifest
from resources.lib.manifest import validate_manifest
from resources.lib.dependencies import _strict_version_satisfies, _version_satisfies

ARCHIVE = Path('/Users/eengert/Documents/Kodi/archives/build-manager-frozen-artifacts-2026-10-04')
PIL_XML = Path('/Applications/Kodi Build Manager Test.app/Contents/Resources/Kodi/addons/script.module.pil/addon.xml')
PACKAGES = {
    'plugin.video.redlight': ('2.6.8', '64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927'),
    'script.module.requests': ('2.31.0', 'fa5eb6969159964dc1917f47da48fab2dd582fa3e608ecfa83d3b488c21147fa'),
    'script.module.urllib3': ('2.2.3', '740b2d63bb50eee9fb35f01c567ec8d3588c5bbd548e2b8d280932be30d82f53'),
    'script.module.idna': ('3.10.0', 'c4ff34dbfab2736e9214a374d331bd6f558d8b3fea8eb7902e210749509242b3'),
    'script.module.chardet': ('5.1.0', 'ac9a7465574586854cdd5b1bf5e90dbca97ce3a30fbfd09c03de24f7b120f16d'),
    'script.module.certifi': ('2023.5.7', '8b47f58ae31496179574268a8220f3782a56a0bac9b5022654f4b692a91c81ce'),
}
LABEL = 'AUTHORED QUALIFICATION FIXTURE — NOT CAPTURED STATE'
BUILD = 'bm-item8-authored'
PROFILE = 'item8-disposable-macos'
OVERLAY = 'item8-authored-unauthenticated'


class AdmissionError(ValueError):
    """Bounded refusal: never include payloads or untrusted paths."""


def _require(condition):
    if not condition:
        raise AdmissionError('ITEM8_FIXTURE_ADMISSION_REFUSED')


def _read(path, limit):
    with _directory(str(path.parent)) as fd:
        data = _read_at(fd, path.name, limit)
    _require(data is not None)
    return data


def _edges(xml):
    return tuple(DependencyEdge(n.attrib['addon'], n.get('version', ''),
                                n.get('optional', 'false') == 'true')
                 for n in xml.findall('./requires/import'))


def validate_dependency_requirements(frozen):
    """Graph completeness and each package-declared minimum, without guessing."""
    nodes = {n.addon_id: n for n in frozen.addons}
    _require(len(nodes) == len(frozen.addons))
    for node in frozen.addons:
        for edge in node.dependency_edges:
            if edge.optional and edge.addon_id not in nodes:
                continue
            _require(edge.addon_id in nodes)
            if edge.min_version:
                dependency = nodes[edge.addon_id]
                compare = _strict_version_satisfies if dependency.platform_provided else _version_satisfies
                _require(compare(dependency.version, edge.min_version))


def validate_inputs(archive, pil_xml):
    """No imports, extraction, package execution, capture, or writes."""
    _require(Path(archive) == ARCHIVE and Path(pil_xml) == PIL_XML)
    sums = _read(ARCHIVE / 'SHA256SUMS', 2 * 1024 * 1024).decode('utf-8')
    _read(ARCHIVE / 'README.md', 64 * 1024)
    records = {}
    for line in sums.splitlines():
        pieces = line.split(maxsplit=1)
        if len(pieces) == 2:
            records[pieces[1].lstrip('*')] = pieces[0]
    blobs, nodes = {}, []
    for aid, (version, digest) in sorted(PACKAGES.items()):
        relative = 'bm017f/artifact-store/artifacts/' + digest + '.zip'
        _require(records.get(relative) == digest or records.get('./' + relative) == digest)
        data = _read(ARCHIVE / relative, 32 * 1024 * 1024)
        metadata = validate_addon_zip(data, expected_addon_id=aid, expected_version=version)
        _require(metadata.sha256 == digest)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            _require(z.testzip() is None)
            xml = ET.fromstring(z.read(aid + '/addon.xml'))
        point = next(n.get('point') for n in xml.findall('extension')
                     if n.get('point') != 'xbmc.addon.metadata')
        nodes.append(AddonCaptureNode(aid, version, point, True,
            ProvenanceStatus.MANUAL_OR_UNKNOWN, artifact=metadata, dependency_edges=_edges(xml)))
        blobs[aid] = data
    pil = ET.fromstring(_read(PIL_XML, 1024 * 1024))
    _require(pil.get('id') == 'script.module.pil' and pil.get('version') == '5.1.0')
    _require(any(n.get('point') == 'xbmc.python.module' for n in pil.findall('extension')))
    _require([(e.addon_id, e.min_version, e.optional) for e in _edges(pil)] == [('xbmc.python', '3.0.0', False)])
    nodes.append(AddonCaptureNode('script.module.pil', '5.1.0', 'xbmc.python.module', True,
        ProvenanceStatus.MANUAL_OR_UNKNOWN, dependency_edges=_edges(pil),
        status=CaptureStatus.PLATFORM_PROVIDED, platform_provided=True))
    nodes.append(AddonCaptureNode('xbmc.python', '3.0.0', 'system', True,
        ProvenanceStatus.MANUAL_OR_UNKNOWN, system=True, status=CaptureStatus.SYSTEM))
    frozen = FrozenBuildManifest(2, BUILD, 'Item 8 authored qualification',
        '2026-10-15T00:00:00Z', '21.3', 'macos', CaptureStatus.COMPLETE, tuple(nodes))
    validate_dependency_requirements(frozen)
    return frozen, blobs


def material(frozen):
    declaration = redlight_declaration()
    # The audited package's revoked/default sentinel, never a fabricated account
    # or token. The remaining auth defaults are untouched and unauthenticated.
    resource = StructuredPrivateResourceOverlay('redlight.settings', 'plugin.video.redlight',
        '2.6.8', 'redlight-settings-v1',
        (StructuredPrivateValue('pm.account_id', 'string', 'empty_setting'),))
    overlay = PrivateOverlay(OVERLAY, 'sha256:' + frozen.fingerprint(), (), resources=(resource,))
    document = {'schema_version': 1, 'build': {'id': BUILD, 'version': '1.0.0',
        'name': 'Item 8 authored qualification'},
        'addons': [{'addon_id': 'plugin.video.redlight', 'state': 'enabled'}],
        'config': {'structured_private_resources': [declaration.safe_dict()]},
        'platform_profiles': {'macos': {}},
        'device_profiles': {PROFILE: {'extends': 'macos'}},
        'private_overlay': {'type': 'local_file', 'overlay_id': OVERLAY, 'required': True}}
    desired = resolve_manifest(validate_manifest(document), PROFILE)
    validate_private_overlay(overlay, (), expected_source_software_fingerprint=frozen.fingerprint(),
        expected_overlay_id=OVERLAY, resource_declarations=desired.config.structured_private_resources)
    bundle = PreparedPublicBundle(json.dumps({'schema_version': 1, 'manifest': document,
        'frozen': frozen.to_dict(), 'packages': {}}))
    return bundle, overlay


def validate_authored_overlay(frozen, overlay):
    """Qualification admission is narrower than the generic overlay schema.

    Generic production validation permits legitimate credentials. This preparer
    permits exactly one unauthenticated sentinel and has no credential input.
    """
    _, expected = material(frozen)
    _require(overlay.to_dict() == expected.to_dict())
    return overlay


def prepare(*, archive, pil_xml, output):
    """Write only into a newly reserved offline root; never update an existing one."""
    output = Path(output)
    _require(output.is_absolute() and output.parent == Path('/private/tmp')
             and output.name.startswith('bm-item8-') and output.name not in ('.', '..'))
    frozen, blobs = validate_inputs(archive, pil_xml)
    bundle, overlay = material(frozen)
    validate_authored_overlay(frozen, overlay)
    # Preserve evidence on interruption. A repeat refuses instead of overwriting,
    # deleting, repairing, adopting, or registering into any existing library.
    with _directory('/private/tmp') as parent:
        os.mkdir(output.name, 0o700, dir_fd=parent)
    with ExitStack() as stack:
        fd = stack.enter_context(_directory(str(output)))
        # Product APIs require canonical path roots, not /dev/fd aliases.
        # The new 0700 root admits no pre-existing state or foreign writers.
        info = os.stat(output, follow_symlinks=False)
        _require((info.st_dev, info.st_ino) == (os.fstat(fd).st_dev, os.fstat(fd).st_ino))
        store = ArtifactStore(output / 'artifacts-store')
        for aid, data in blobs.items():
            store.import_zip(data, expected_addon_id=aid, expected_version=PACKAGES[aid][0],
                             source='authored Item 8: pinned public archive')
        validate_frozen_install_plan(frozen, store)
        info = os.stat(output, follow_symlinks=False)
        _require((info.st_dev, info.st_ino) == (os.fstat(fd).st_dev, os.fstat(fd).st_ino))
        library = BuildLibrary(str(output / 'library'))
        with bundle.registration_inputs() as inputs:
            entry = library.register(*inputs)
        PrivateOverlayStore(output / 'profile').save(overlay)
        library.select(entry.entry_id, PROFILE)
        record = {'label': LABEL, 'entry_id': entry.entry_id, 'profile': PROFILE,
                  'software_fingerprint': frozen.fingerprint(),
                  'packages': {aid: {'version': v, 'sha256': h} for aid, (v, h) in PACKAGES.items()},
                  'overlay_values': 'Only package unauthenticated sentinel; no account or token',
                  'capture_performed': False, 'runtime_performed': False}
        with open(output / 'provenance.json', 'x', encoding='utf-8') as stream:
            json.dump(record, stream, indent=2); stream.write('\n')
        return record


def main():
    parser = argparse.ArgumentParser(description=LABEL)
    for name in ('archive', 'pil-xml', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare(archive=args.archive, pil_xml=args.pil_xml, output=args.output)
    except Exception:
        parser.exit(1, 'ITEM8_FIXTURE_REFUSED; retain any incomplete output\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
