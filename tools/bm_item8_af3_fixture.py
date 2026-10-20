"""Construct the approved AF3 authored fixture offline, without publishing state.

AUTHORED QUALIFICATION FIXTURE — NOT CAPTURED STATE.
Only retained, checksum-pinned evidence is read. No Kodi API, ArtifactStore
writer, library registration, transaction or installation is used.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from resources.lib.addon_zip import validated_root
from resources.lib.artifacts import ArtifactMetadata, validate_addon_zip
from resources.lib.frozen import (
    AddonCaptureNode, CaptureStatus, DependencyEdge, FrozenBuildManifest,
    ProvenanceStatus, _declared_extension_points, _parse_dependency_edges,
)
from resources.lib.frozen_install import validate_frozen_manifest, validate_frozen_install_plan

LABEL = "AUTHORED QUALIFICATION FIXTURE — NOT CAPTURED STATE"
PINS = {
    "item8-af3-correction-20261018/trusted-closure.json":
        "7abd85187af6ee91df2c2e08ad8bdbdbe5153922b267ff78de2ed7469799ec2a",
    "item8-help-af3-20261018/platform-requirements.json":
        "9a37612174cd4dfcef766a23290b09874cbc0d6e6ff6bcb2e056c23f0bde161e",
    "item8-help-af3-20261018/platform-source.json":
        "112e8527a1c08bb9f76e13279604ee436ab27ee6cf95039e3864422937ea8d79",
}
SYSTEM_IDS = frozenset(("xbmc.gui", "xbmc.python", "kodi.resource", "xbmc.core"))


class FixtureInputError(ValueError):
    """Approved input is missing, altered or inconsistent."""


def _read(root, relative, digest=None):
    # Do not let a caller-selected evidence tree redirect reads outside itself.
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in (".", "..") for p in parts):
        raise FixtureInputError("unsafe evidence path")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise FixtureInputError("symlink in evidence path")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FixtureInputError("approved evidence is unavailable: " + relative) from exc
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise FixtureInputError("approved evidence checksum mismatch: " + relative)
    return data


class ReadOnlyArtifacts:
    """Validation-only facade; re-read pinned original bytes on every access."""
    def __init__(self, root, rows):
        self.root = root
        self.rows = {row[0].sha256: row for row in rows}

    def get_metadata(self, digest):
        return self.rows[digest][0]

    def read_bytes(self, digest):
        metadata, relative = self.rows[digest]
        data = _read(self.root, relative, digest)
        if len(data) != metadata.size:
            raise FixtureInputError("approved archive size mismatch")
        return data


def prepare(evidence_root=None):
    """Return (typed manifest, read-only artifacts); write no files.

    The historical version fields of system/PIL rows describe source
    observations. Incoming edges are requirements, not exact target versions.
    Core's structured observation is retained; raw core XML was not retained.
    """
    root = Path(evidence_root or Path(__file__).resolve().parents[1] / ".qualification-evidence")
    if root.is_symlink():
        raise FixtureInputError("symlink evidence root")
    evidence = {name: json.loads(_read(root, name, digest)) for name, digest in PINS.items()}
    closure = evidence[next(iter(PINS))]
    observations = {r["id"]: r for r in evidence["item8-help-af3-20261018/platform-requirements.json"]}
    sources = evidence["item8-help-af3-20261018/platform-source.json"]
    if len(closure["nodes"]) != 22 or len(closure["edges"]) != 45:
        raise FixtureInputError("approved graph cardinality mismatch")
    rows, nodes = [], []
    for row in closure["nodes"]:
        aid = row["id"]
        retained = tuple(sorted(
            (e["to"], e["minimum"], e["optional"])
            for e in closure["edges"] if e["from"] == aid))
        edges = tuple(DependencyEdge(child, minimum, optional, (aid,))
                      for child, minimum, optional in retained)
        artifact = None
        detail = {"fixture": LABEL}
        if row["kind"] == "managed":
            data = _read(root, row["path"], row["sha256"])
            if len(data) != row["bytes"]:
                raise FixtureInputError("approved archive size mismatch: " + aid)
            validate_addon_zip(data, expected_addon_id=aid, expected_version=row["version"])
            package = validated_root(data, aid, row["version"])
            actual = tuple(sorted((e.addon_id, e.min_version, e.optional)
                                  for e in _parse_dependency_edges(package.xml_bytes, aid)))
            if actual != retained or package.root != row["actual_root"]:
                raise FixtureInputError("archive dependency/root evidence mismatch: " + aid)
            declared = set(_declared_extension_points(package.xml_bytes, aid)) - {"xbmc.addon.metadata"}
            if not declared:
                raise FixtureInputError("missing managed extension type: " + aid)
            # A package can declare several real capabilities. This authored
            # classification chooses one deterministically; none is invented.
            kind = sorted(declared)[0]
            artifact = ArtifactMetadata(row["sha256"], row["bytes"], aid, row["version"],
                                        Path(row["path"]).name, "approved-retained-archive")
            rows.append((artifact, row["path"]))
            status = CaptureStatus.COMPLETE
        else:
            observation = observations[aid]
            if (observation["actual_version"] != row["version"] or
                    observation["addon_xml_sha256"] != row["source_metadata_sha256"]):
                raise FixtureInputError("source observation identity mismatch: " + aid)
            observed_edges = tuple(sorted((e["addon"], e.get("version", ""),
                                          e.get("optional", "false") == "true")
                                         for e in observation["dependencies"]))
            if observed_edges != retained:
                raise FixtureInputError("source dependency observation mismatch: " + aid)
            detail.update(source_metadata_sha256=row["source_metadata_sha256"],
                          runtime_evidence="NONE; retained source observation only")
            if aid == "xbmc.core":
                detail["limitation"] = "Raw core XML not retained; structured source observation only"
            else:
                source = sources["addons/" + aid + "/addon.xml"]
                xml = source["text"].encode()
                if (hashlib.sha256(xml).hexdigest() != row["source_metadata_sha256"] or
                        source["sha256"] != row["source_metadata_sha256"]):
                    raise FixtureInputError("source XML checksum mismatch: " + aid)
                from resources.lib.frozen import _check_addon_xml_identity
                _check_addon_xml_identity(xml, aid, row["version"])
                if tuple(sorted((e.addon_id, e.min_version, e.optional)
                                for e in _parse_dependency_edges(xml, aid))) != retained:
                    raise FixtureInputError("source XML dependency mismatch: " + aid)
            if aid in SYSTEM_IDS:
                kind, status = "system", CaptureStatus.SYSTEM
            elif aid == "script.module.pil":
                if "xbmc.python.module" not in _declared_extension_points(xml, aid):
                    raise FixtureInputError("PIL source type mismatch")
                kind, status = "xbmc.python.module", CaptureStatus.PLATFORM_PROVIDED
            else:
                raise FixtureInputError("unapproved platform classification")
        nodes.append(AddonCaptureNode(
            aid, row["version"], kind, True, ProvenanceStatus.UNKNOWN,
            provenance_detail=detail, artifact=artifact, dependency_edges=edges,
            system=aid in SYSTEM_IDS, platform_provided=aid == "script.module.pil", status=status))
    if len(rows) != 17 or len({n.addon_id for n in nodes}) != 22:
        raise FixtureInputError("approved graph identity mismatch")
    manifest = FrozenBuildManifest(
        schema_version=2, build_id="item8-authored-af3-3.3.12", name=LABEL,
        created_at="2026-10-20T00:00:00Z", kodi_version="UNOBSERVED", platform="macos",
        capture_status=CaptureStatus.COMPLETE, addons=tuple(nodes),
        source_metadata={"fixture": LABEL, "runtime_observations": "NONE",
                         "source_requirements": "Retained October 18 source observations; not target versions",
                         "input_pins": json.dumps(PINS, sort_keys=True),
                         "core_limitation": "Raw XML not retained; structured source observation only"})
    store = ReadOnlyArtifacts(root, rows)
    manifest = FrozenBuildManifest.from_json(manifest.to_json())
    validate_frozen_manifest(manifest, store)
    validate_frozen_install_plan(manifest, store)
    return manifest, store
