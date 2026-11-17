"""Controlled package of an installed add-on's own files (D-033 exception).

This is the last-resort acquisition step, used only when the exact original ZIP is
demonstrably absent from the official repository. It never reads Kodi, the network or
the filesystem: ``build_local_capture_zip`` receives the file bytes that the trusted-root
scan already proved fresh and returns deterministic ZIP bytes, or raises
``LocalCaptureRefusal``. Anything ambiguous, private, native or unsafe is refused, never
silently packaged or silently dropped.

The result is local, weaker provenance. It is recorded under ``LOCAL_CAPTURE_SOURCE`` and
is never an original or repository-verified archive.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, Mapping, Tuple

LOCAL_CAPTURE_SOURCE = "installed_local_capture"
LOCAL_CAPTURE_MAX_BYTES = 64 * 1024 * 1024

Parts = Tuple[str, ...]


class LocalCaptureRefusal(Exception):
    """Fail-closed refusal with a fixed reason. No path, value or file name is carried."""


# Generated, reproducible or OS noise that is dropped and counted, never refused.
_DROPPED_NAMES = frozenset({".ds_store", "thumbs.db"})
_DROPPED_SUFFIXES = (".log",)
_CACHE_DIRECTORY = "__pycache__"
_CACHE_FILE = re.compile(r"(?P<module>[^.]+)\.[A-Za-z0-9_-]+(?:\.opt-[12])?\.pyc")

# Kodi keeps user state in userdata/addon_data. Finding any of it inside the install
# directory is anomalous, so it is refused rather than guessed about.
_PRIVATE_DIRECTORIES = frozenset({"addon_data", "userdata", ".git", ".svn", ".hg"})
_PRIVATE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".key", ".p12", ".pfx", ".jks", ".keystore", ".cookies")
_PRIVATE_NAMES = frozenset({".env", ".netrc", ".htpasswd", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"})
_PRIVATE_TOKENS = ("password", "passwd", "secret", "credential", "apikey", "api_key", "cookie", "auth_token", "access_token")
_DATA_SUFFIXES = frozenset({"", ".json", ".xml", ".ini", ".cfg", ".conf", ".txt", ".dat", ".bin", ".yml", ".yaml", ".toml", ".properties"})

_NATIVE_SUFFIXES = frozenset({".so", ".dylib", ".dll", ".pyd", ".exe", ".a", ".o", ".jnilib", ".node", ".apk", ".class", ".jar"})
_NATIVE_MAGIC = (b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                 b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe")


def _suffix(name: str) -> str:
    index = name.rfind(".")
    return name[index:] if index > 0 else ""


def _is_native(name: str, data: bytes) -> bool:
    if _suffix(name.casefold()) in _NATIVE_SUFFIXES or data.startswith(_NATIVE_MAGIC):
        return True
    if data[:2] == b"MZ" and len(data) > 64:
        offset = int.from_bytes(data[60:64], "little")
        return data[offset:offset + 4] == b"PE\x00\x00"
    return False


def _looks_private(parts: Parts) -> bool:
    name = parts[-1].casefold()
    if parts == ("settings.xml",):
        # Only the add-on root settings.xml is saved user state. resources/settings.xml is
        # the shipped definition and is ordinary distributable content.
        return True
    if name in _PRIVATE_NAMES or name.endswith(_PRIVATE_SUFFIXES):
        return True
    return _suffix(name) in _DATA_SUFFIXES and any(token in name for token in _PRIVATE_TOKENS)


def _check_platform(xml_bytes: bytes) -> None:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise LocalCaptureRefusal("add-on metadata is malformed") from exc
    for extension in root.iter():
        if extension.tag.rsplit("}", 1)[-1] != "extension":
            continue
        if any(key.startswith("library_") for key in extension.attrib):
            raise LocalCaptureRefusal("add-on declares platform-specific libraries")
        for child in extension:
            if child.tag.rsplit("}", 1)[-1] == "platform" and (child.text or "").strip().casefold() not in ("", "all"):
                raise LocalCaptureRefusal("add-on is not declared for all platforms")


def classify_installed_files(
    files: Mapping[Parts, bytes],
) -> Tuple[Dict[Parts, bytes], int]:
    """Return (files to package, dropped generated count) or raise LocalCaptureRefusal."""
    if ("addon.xml",) not in files:
        raise LocalCaptureRefusal("installed add-on has no addon.xml")
    kept: Dict[Parts, bytes] = {}
    dropped = 0
    for parts, data in files.items():
        name = parts[-1]
        folded = name.casefold()
        if any(part.casefold() in _PRIVATE_DIRECTORIES for part in parts[:-1]):
            raise LocalCaptureRefusal("installed add-on contains private or local-state content")
        if folded in _DROPPED_NAMES or folded.endswith(_DROPPED_SUFFIXES):
            dropped += 1
            continue
        in_cache = len(parts) >= 2 and parts[-2] == _CACHE_DIRECTORY
        if folded.endswith((".pyc", ".pyo")) or in_cache:
            match = _CACHE_FILE.fullmatch(name) if in_cache else None
            source = parts[:-2] + (match.group("module") + ".py",) if match else None
            if source is not None and source in files:
                dropped += 1  # regenerable cache whose source is shipped
                continue
            raise LocalCaptureRefusal("installed add-on contains bytecode without shipped source")
        if _looks_private(parts):
            raise LocalCaptureRefusal("installed add-on contains private or local-state content")
        if _is_native(name, data):
            raise LocalCaptureRefusal("installed add-on contains platform-specific binary content")
        kept[parts] = data
    _check_platform(kept[("addon.xml",)])
    return kept, dropped


def build_local_capture_zip(addon_id: str, files: Mapping[Parts, bytes]) -> Tuple[bytes, int]:
    """Deterministic ZIP (sorted, fixed timestamp, no extra metadata) plus dropped-file count."""
    kept, dropped = classify_installed_files(files)
    if sum(len(data) for data in kept.values()) > LOCAL_CAPTURE_MAX_BYTES:
        raise LocalCaptureRefusal("installed add-on exceeds the local capture size limit")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for parts in sorted(kept):
            info = zipfile.ZipInfo("/".join((addon_id,) + parts), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, kept[parts])
    data = buffer.getvalue()
    if len(data) > LOCAL_CAPTURE_MAX_BYTES:
        raise LocalCaptureRefusal("installed add-on exceeds the local capture size limit")
    return data, dropped
