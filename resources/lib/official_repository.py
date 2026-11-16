"""Exact-archive acquisition from the application-bundled official Kodi repository.

This provider is the optional third step of the frozen acquisition order
(PROJECT.md; D-003, D-004, D-028). It runs only after the verified artifact
store and the exact Kodi package cache have been tried, and never for
platform-provided add-ons. It returns one archive or raises
RepositoryArtifactRefusal, which callers must treat as fail-closed.

Trust anchor
    The single ``<dir>`` of the application-bundled ``repository.xbmc.org``
    add-on, read through Build Manager's trusted application root. Its ``info``,
    ``checksum`` and ``datadir zip="true"`` define every location contacted.
    Callers supply only an add-on ID and an exact version. No caller-supplied
    URL is used, and no other repository is consulted.

Acquisition
    1. Read the index within bounds. Its digest must match the configured
       checksum: the raw bytes, or the decompressed bytes for a ``.gz`` index.
    2. Require exactly one index entry with the exact ID and version. Its
       declared ``<path>`` and ``<size>`` must name that archive when present.
       There is no fallback to any other version.
    3. Fetch ``<datadir><id>/<id>-<version>.zip.md5`` and the archive over HTTPS,
       within size and time bounds. The archive must match the sidecar.

MD5 is supplemental. The sidecar is served by the same mirror as the archive,
so it proves transfer integrity, not authenticity. Authority over the bytes
rests on the bundled trust anchor, the exact identity checks in
validate_addon_zip, and the installed-content equality gate in frozen.py, which
runs before anything is imported.

Redirect policy: every hop must be HTTPS on port 443, with no credentials,
query or fragment, a DNS host rather than an address literal, and the archive's
own trailing path segments. Mirror hosts are not allow-listed, because the
official mirror itself redirects to third-party mirrors.

Nothing here logs, stores or returns URLs, headers or local paths. Refusal
messages are fixed reason strings.
"""

from __future__ import annotations

import gzip
import hashlib
import http.client
import io
import ipaddress
import re
import socket
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

OFFICIAL_REPOSITORY_ID = "repository.xbmc.org"
INDEX_MAX_BYTES = 32 * 1024 * 1024
INDEX_MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
ARCHIVE_MAX_BYTES = 64 * 1024 * 1024
SIDECAR_MAX_BYTES = 256
CONFIG_MAX_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30.0
TRANSFER_BUDGET_SECONDS = 180.0
MAX_REDIRECTS = 5

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ADDON_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_ADDON_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+~-]{0,63}")
_DNS_NAME = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]")
_DIGEST_LINE = re.compile(r"([0-9a-fA-F]{32})(?:[ \t]+(\S+))?")
_READ_CHUNK = 65536


class RepositoryArtifactRefusal(Exception):
    """Fail-closed refusal. The message is a fixed reason with no URL, path or secret."""


@dataclass(frozen=True)
class OfficialRepositoryConfig:
    """The validated single official directory of the bundled repository add-on."""

    index_url: str
    index_name: str
    checksum_url: str
    checksum_name: str
    datadir_url: str


def _check_https_authority(parts: urllib.parse.SplitResult) -> None:
    if parts.scheme != "https":
        raise RepositoryArtifactRefusal("official repository URL is not HTTPS")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise RepositoryArtifactRefusal("official repository URL carries credentials")
    if parts.query or parts.fragment:
        raise RepositoryArtifactRefusal("official repository URL carries a query or fragment")
    try:
        port = parts.port
    except ValueError as exc:
        raise RepositoryArtifactRefusal("official repository URL port is invalid") from exc
    if port not in (None, 443):
        raise RepositoryArtifactRefusal("official repository URL uses a non-default port")
    host = parts.hostname or ""
    if not _DNS_NAME.fullmatch(host):
        raise RepositoryArtifactRefusal("official repository URL host is not a DNS name")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return
    raise RepositoryArtifactRefusal("official repository URL host is an address literal")


def _check_path(path: str, *, directory: bool) -> Tuple[str, ...]:
    """Return decoded path segments, refusing anything that could escape the directory."""
    if not path.startswith("/") or path.endswith("/") != directory:
        raise RepositoryArtifactRefusal("official repository URL path is invalid")
    segments = path[1:].split("/")
    if directory:
        segments = segments[:-1]
    decoded = tuple(urllib.parse.unquote(segment) for segment in segments)
    for segment in decoded:
        if segment in ("", ".", "..") or "\\" in segment or "\x00" in segment:
            raise RepositoryArtifactRefusal("official repository URL path is unsafe")
    return decoded


def _https_url(value: object, label: str, *, directory: bool = False) -> urllib.parse.SplitResult:
    if not isinstance(value, str):
        raise RepositoryArtifactRefusal(f"bundled repository {label} is invalid")
    text = value.strip()
    if not text or len(text) > 2048:
        raise RepositoryArtifactRefusal(f"bundled repository {label} is invalid")
    parts = urllib.parse.urlsplit(text)
    _check_https_authority(parts)
    _check_path(parts.path, directory=directory)
    return parts


def _leaf(parts: urllib.parse.SplitResult) -> str:
    return urllib.parse.unquote(parts.path.rsplit("/", 1)[1])


def _parent(parts: urllib.parse.SplitResult) -> str:
    return parts.path.rsplit("/", 1)[0]


def parse_official_repository_config(addon_xml: bytes) -> OfficialRepositoryConfig:
    """Validate the bundled repository add-on and return its one official directory."""
    if not isinstance(addon_xml, bytes) or not 0 < len(addon_xml) <= CONFIG_MAX_BYTES:
        raise RepositoryArtifactRefusal("bundled repository configuration is unavailable")
    if b"<!DOCTYPE" in addon_xml or b"<!ENTITY" in addon_xml:
        raise RepositoryArtifactRefusal("bundled repository configuration is invalid")
    try:
        root = ET.fromstring(addon_xml)
    except ET.ParseError as exc:
        raise RepositoryArtifactRefusal("bundled repository configuration is invalid") from exc
    if root.tag != "addon" or root.get("id") != OFFICIAL_REPOSITORY_ID:
        raise RepositoryArtifactRefusal("bundled repository configuration names another add-on")
    extensions = [item for item in root.findall("extension") if item.get("point") == "xbmc.addon.repository"]
    directories = [item for extension in extensions for item in extension.findall("dir")]
    if len(extensions) != 1 or len(directories) != 1:
        raise RepositoryArtifactRefusal("bundled repository must declare exactly one directory")
    directory = directories[0]
    infos = directory.findall("info")
    checksums = directory.findall("checksum")
    datadirs = directory.findall("datadir")
    if len(infos) != 1 or len(checksums) != 1 or len(datadirs) != 1:
        raise RepositoryArtifactRefusal("bundled repository directory is incomplete or ambiguous")
    info, checksum, datadir = infos[0], checksums[0], datadirs[0]
    compressed = info.get("compressed")
    if compressed not in ("true", "false"):
        raise RepositoryArtifactRefusal("bundled repository index declares an unknown compression")
    index_name = "addons.xml.gz" if compressed == "true" else "addons.xml"
    index = _https_url(info.text, "index")
    if _leaf(index) != index_name:
        raise RepositoryArtifactRefusal("bundled repository index name is unexpected")
    checksum_url = _https_url(checksum.text, "checksum")
    checksum_name = _leaf(checksum_url)
    if checksum_name not in (f"{index_name}.md5", "addons.xml.md5"):
        raise RepositoryArtifactRefusal("bundled repository checksum name is unexpected")
    if _parent(checksum_url) != _parent(index) or checksum_url.hostname != index.hostname:
        raise RepositoryArtifactRefusal("bundled repository checksum is outside the index directory")
    if datadir.get("zip") != "true":
        raise RepositoryArtifactRefusal("bundled repository datadir is not a zip directory")
    datadir_url = _https_url(datadir.text, "datadir", directory=True)
    if datadir_url.hostname != index.hostname:
        raise RepositoryArtifactRefusal("bundled repository datadir uses another host")
    return OfficialRepositoryConfig(
        index_url=index.geturl(),
        index_name=index_name,
        checksum_url=checksum_url.geturl(),
        checksum_name=checksum_name,
        datadir_url=datadir_url.geturl(),
    )


def _redirect_target(current: str, location: object, tail: Tuple[str, ...]) -> str:
    if not isinstance(location, str) or not location or len(location) > 4096 or location != location.strip():
        raise RepositoryArtifactRefusal("official repository redirect is invalid")
    named = urllib.parse.urlsplit(location)
    # A named scheme must be HTTPS with a host. Otherwise urljoin would silently rebase the hop onto the current host.
    if named.scheme and (named.scheme != "https" or not named.netloc):
        raise RepositoryArtifactRefusal("official repository redirect is invalid")
    target = urllib.parse.urljoin(current, location)
    parts = urllib.parse.urlsplit(target)
    _check_https_authority(parts)
    decoded = _check_path(parts.path, directory=False)
    if decoded[-len(tail):] != tail:
        raise RepositoryArtifactRefusal("official repository redirect changed the archive name")
    return target


def _default_connect(host: str, port: int, timeout: float):
    try:
        # Imported here, not at module load, so the capture core imports on hosts without a TLS library.
        import ssl
    except ImportError as exc:
        # Fail closed: without a TLS library there is no HTTPS, and plain HTTP is never an alternative.
        raise RepositoryArtifactRefusal("official repository TLS is unavailable") from exc
    return http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())


class BoundedHttpsGetter:
    """HTTPS GET with fixed size, time and redirect bounds. Sends no credentials."""

    def __init__(
        self,
        *,
        connect: Optional[Callable[[str, int, float], object]] = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._connect = connect or _default_connect
        self._timeout = timeout
        self._clock = clock

    def get(self, url: str, *, max_bytes: int, tail: Tuple[str, ...]) -> bytes:
        deadline = self._clock() + TRANSFER_BUDGET_SECONDS
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            parts = urllib.parse.urlsplit(current)
            status, location, body = self._request_once(parts, max_bytes=max_bytes, deadline=deadline)
            if status == 200:
                return body
            if status not in _REDIRECT_STATUSES:
                raise RepositoryArtifactRefusal("official repository returned an unexpected status")
            if hop == MAX_REDIRECTS:
                break
            current = _redirect_target(current, location, tail)
        raise RepositoryArtifactRefusal("official repository redirected too many times")

    def _request_once(self, parts: urllib.parse.SplitResult, *, max_bytes: int, deadline: float):
        _check_https_authority(parts)
        connection = None
        try:
            connection = self._connect(parts.hostname, parts.port or 443, self._timeout)
            connection.request(
                "GET",
                parts.path,
                headers={"Accept-Encoding": "identity", "Connection": "close", "User-Agent": "artifact-fetch/1"},
            )
            response = connection.getresponse()
            status = response.status
            if status in _REDIRECT_STATUSES:
                return status, response.getheader("Location"), b""
            if status != 200:
                return status, None, b""
            encoding = response.getheader("Content-Encoding")
            if encoding not in (None, "", "identity"):
                raise RepositoryArtifactRefusal("official repository response encoding is unsupported")
            declared = response.getheader("Content-Length")
            expected_length = None
            if declared is not None:
                if not declared.isdigit() or int(declared) > max_bytes:
                    raise RepositoryArtifactRefusal("official repository response exceeds its size limit")
                expected_length = int(declared)
            body = bytearray()
            while True:
                if self._clock() > deadline:
                    raise RepositoryArtifactRefusal("official repository transfer exceeded its time budget")
                chunk = response.read(min(_READ_CHUNK, max_bytes + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise RepositoryArtifactRefusal("official repository response exceeds its size limit")
            if expected_length is not None and len(body) != expected_length:
                raise RepositoryArtifactRefusal("official repository response was truncated")
            return 200, None, bytes(body)
        except RepositoryArtifactRefusal:
            raise
        except http.client.IncompleteRead as exc:
            raise RepositoryArtifactRefusal("official repository response was truncated") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RepositoryArtifactRefusal("official repository request timed out") from exc
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise RepositoryArtifactRefusal("official repository request failed") from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (OSError, http.client.HTTPException):
                    pass


def _parse_digest(data: bytes, *, names: Tuple[str, ...]) -> str:
    try:
        text = data.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RepositoryArtifactRefusal("official repository checksum is invalid") from exc
    match = _DIGEST_LINE.fullmatch(text)
    if match is None:
        raise RepositoryArtifactRefusal("official repository checksum is invalid")
    if match.group(2) is not None and match.group(2) not in names:
        raise RepositoryArtifactRefusal("official repository checksum names a different file")
    return match.group(1).lower()


def _md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _gunzip_bounded(data: bytes, limit: int) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
            output = stream.read(limit + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise RepositoryArtifactRefusal("official index is not a valid archive") from exc
    if len(output) > limit:
        raise RepositoryArtifactRefusal("official index exceeds its decompressed size limit")
    return output


def _metadata_location(addon) -> Tuple[Optional[str], Optional[int]]:
    """Return the declared ``<path>`` and ``<size>`` from the add-on's metadata extension."""
    for extension in addon.findall("extension"):
        if extension.get("point") != "kodi.addon.metadata":
            continue
        path_element = extension.find("path")
        size_element = extension.find("size")
        path = path_element.text.strip() if path_element is not None and path_element.text else None
        size = None
        if size_element is not None and size_element.text is not None:
            text = size_element.text.strip()
            if not text.isdigit():
                raise RepositoryArtifactRefusal("official index size is invalid")
            size = int(text)
        return path, size
    return None, None


def _parse_index(xml_bytes: bytes) -> Dict[Tuple[str, str], Optional[Tuple[Optional[str], Optional[int]]]]:
    """Map (id, version) to the declared archive location, or None when the entry is ambiguous."""
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise RepositoryArtifactRefusal("official index is invalid")
    entries: Dict[Tuple[str, str], Optional[Tuple[Optional[str], Optional[int]]]] = {}
    depth = 0
    seen_root = False
    try:
        for event, element in ET.iterparse(io.BytesIO(xml_bytes), events=("start", "end")):
            if event == "start":
                if not seen_root:
                    seen_root = True
                    if element.tag != "addons":
                        raise RepositoryArtifactRefusal("official index is invalid")
                depth += 1
                continue
            depth -= 1
            if depth == 1 and element.tag == "addon":
                key = (element.get("id", ""), element.get("version", ""))
                location = _metadata_location(element)
                entries[key] = None if key in entries else location
                element.clear()
    except (ET.ParseError, ValueError) as exc:
        raise RepositoryArtifactRefusal("official index is invalid") from exc
    return entries


class OfficialRepositoryProvider:
    """Exact official archive lookup. One instance caches its index for one capture run."""

    def __init__(
        self,
        config: OfficialRepositoryConfig,
        *,
        transport: Optional[BoundedHttpsGetter] = None,
        index_max_bytes: int = INDEX_MAX_BYTES,
        index_max_decompressed_bytes: int = INDEX_MAX_DECOMPRESSED_BYTES,
        archive_max_bytes: int = ARCHIVE_MAX_BYTES,
    ):
        self._config = config
        self._transport = transport or BoundedHttpsGetter()
        self._index_max_bytes = index_max_bytes
        self._index_max_decompressed_bytes = index_max_decompressed_bytes
        self._archive_max_bytes = archive_max_bytes
        self._index: Optional[Tuple[str, object]] = None

    def fetch_archive(self, addon_id: str, version: str) -> Tuple[str, bytes]:
        """Return (filename, bytes) for one exact official archive, or raise refusal."""
        if (not isinstance(addon_id, str) or not _ADDON_ID.fullmatch(addon_id)
                or not isinstance(version, str) or not _ADDON_VERSION.fullmatch(version)):
            raise RepositoryArtifactRefusal("exact add-on identity is invalid")
        entries = self._index_entries()
        key = (addon_id, version)
        if key not in entries:
            raise RepositoryArtifactRefusal("exact version is not listed in the official index")
        location = entries[key]
        if location is None:
            raise RepositoryArtifactRefusal("official index lists this version ambiguously")
        declared_path, declared_size = location
        filename = f"{addon_id}-{version}.zip"
        relative = f"{addon_id}/{filename}"
        if declared_path is not None and declared_path != relative:
            raise RepositoryArtifactRefusal("official index names a different archive path")
        archive_url = self._config.datadir_url + relative
        sidecar = self._transport.get(
            archive_url + ".md5", max_bytes=SIDECAR_MAX_BYTES, tail=(addon_id, filename + ".md5"),
        )
        expected = _parse_digest(sidecar, names=(filename,))
        archive = self._transport.get(archive_url, max_bytes=self._archive_max_bytes, tail=(addon_id, filename))
        if declared_size is not None and len(archive) != declared_size:
            raise RepositoryArtifactRefusal("archive size does not match the official index")
        if _md5(archive) != expected:
            raise RepositoryArtifactRefusal("archive checksum does not match the official sidecar")
        return filename, archive

    def _index_entries(self):
        if self._index is None:
            try:
                self._index = ("ok", self._load_index())
            except RepositoryArtifactRefusal as exc:
                self._index = ("refused", str(exc))
        status, value = self._index
        if status == "refused":
            raise RepositoryArtifactRefusal(str(value))
        return value

    def _load_index(self):
        config = self._config
        checksum = self._transport.get(
            config.checksum_url, max_bytes=SIDECAR_MAX_BYTES, tail=(config.checksum_name,),
        )
        expected = _parse_digest(checksum, names=("addons.xml", "addons.xml.gz"))
        raw = self._transport.get(config.index_url, max_bytes=self._index_max_bytes, tail=(config.index_name,))
        if config.index_name.endswith(".gz"):
            xml_bytes = _gunzip_bounded(raw, self._index_max_decompressed_bytes)
            accepted = {_md5(raw), _md5(xml_bytes)}
        else:
            xml_bytes = raw
            accepted = {_md5(raw)}
        if expected not in accepted:
            raise RepositoryArtifactRefusal("official index does not match its checksum")
        return _parse_index(xml_bytes)
