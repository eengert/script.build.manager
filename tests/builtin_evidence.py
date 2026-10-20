"""Explicit synthetic interface evidence for offline lifecycle tests only."""
from dataclasses import replace
from resources.lib.frozen import (
    AddonCaptureNode, CaptureStatus, DependencyEdge, InstalledMetadata,
    InstalledOrigin, ProvenanceStatus,
)
from resources.lib.frozen_install import FrozenInstalledAddon, InMemoryFrozenArtifactBackend


def core_node():
    return AddonCaptureNode("xbmc.core", "0.1.0", "system", True,
                            ProvenanceStatus.UNKNOWN, system=True, status=CaptureStatus.SYSTEM)


def close_python(manifest):
    """Model the actual Python/core relationship, previously omitted by fixtures."""
    if not any(n.addon_id == "xbmc.python" for n in manifest.addons):
        return manifest
    nodes = tuple(replace(n, dependency_edges=(DependencyEdge("xbmc.core", "0.1.0"),))
                  if n.addon_id == "xbmc.python" else n for n in manifest.addons)
    if not any(n.addon_id == "xbmc.core" for n in nodes):
        nodes += (core_node(),)
    return replace(manifest, addons=nodes)


class SyntheticBuiltinBackend(InMemoryFrozenArtifactBackend):
    """An explicit fake native proof, with observable state and ABI/closure bytes.

    There is no such default authority in the production in-memory backend.
    Tests can withdraw any proof or change any field between lifecycle checks.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.builtin_state = {
            "xbmc.python": FrozenInstalledAddon("xbmc.python", "3.0.1", True),
            "xbmc.core": FrozenInstalledAddon("xbmc.core", "0.1.0", True),
        }
        self.builtin_abis = {"xbmc.python": "3.0.0", "xbmc.core": "0.1.0"}
        self.builtin_checks = []

    def read_verified_builtin_metadata(self, edge):
        self.builtin_checks.append((edge.addon_id, edge.min_version))
        aid = edge.addon_id
        details = self.installed.get(aid, self.builtin_state.get(aid))
        if details is None or details.broken or details.enabled is not True:
            return None
        children = ('<requires><import addon="xbmc.core" version="0.1.0"/></requires>'
                    if aid in ("xbmc.python", "xbmc.gui", "kodi.resource") else "")
        xml = (f'<addon id="{aid}" version="{details.version}">'
               f'<backwards-compatibility abi="{self.builtin_abis[aid]}"/>{children}</addon>').encode()
        return InstalledMetadata(xml, InstalledOrigin.APPLICATION)

    def verify_builtin_requirement(self, edge):
        return self.read_verified_builtin_metadata(edge) is not None
