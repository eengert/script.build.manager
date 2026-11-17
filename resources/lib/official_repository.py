"""Exact-archive acquisition from the application-bundled official Kodi repository.

This provider is the optional third step of the frozen acquisition order
(PROJECT.md; D-003, D-004, D-028). It runs only after the verified artifact
store and the exact Kodi package cache have been tried, and never for
platform-provided add-ons. It returns one archive or raises
RepositoryArtifactRefusal, which callers must treat as fail-closed.

Trust anchor
    The single ``<dir>`` of the application-bundled ``repository.xbmc.org``
    add-on, read through Build Manager's trusted application root. Its ``info``,
    ``checksum`` and ``datadir`` define every location contacted. The shipped
    Kodi 21 descriptor declares ``<checksum verify="sha256">`` with a ``?sha256``
    URL, no ``compressed`` attribute, a ``datadir`` without ``zip`` or trailing
    slash, and ``<hashes>sha256</hashes>``; all of that is supported. The digest
    algorithm is whatever the descriptor declares (sha256, or an explicit legacy
    md5). It is never lowered. Callers supply only an add-on ID and an exact
    version. No caller-supplied URL is used, and no other repository is consulted.

Acquisition
    1. Read the index within bounds. Its digest must match the configured
       checksum: the raw bytes, or the decompressed bytes for a ``.gz`` index.
    2. Require exactly one index entry with the exact ID and version. Its
       declared ``<path>`` and ``<size>`` must name that archive when present.
       There is no fallback to any other version.
    3. Fetch ``<datadir>/<id>/<id>-<version>.zip.<hashes>`` and the archive over
       HTTPS, within size and time bounds. The archive must match the sidecar.

The sidecar is served by the same mirror as the archive, so it proves transfer
integrity, not authenticity. Authority over the bytes rests on the bundled trust
anchor, the exact identity checks in validate_addon_zip, and the installed-content
equality gate in frozen.py, which runs before anything is imported.

Network policy, applied to every request including the first: every hop must be
HTTPS on port 443, with no credentials or fragment, a DNS host rather than an
address literal, and the archive's own trailing path segments. Encoded
separators, dot segments and double encoding in a path are refused. The host is
resolved once per request, every resolved address must be publicly routable
(loopback, private, link-local, shared, reserved, multicast, mapped and
transition-embedded addresses are refused), and the connection is made to that
validated address while TLS certificate and host name verification still use the
DNS host. A later DNS answer therefore cannot redirect an approved request.
Mirror hosts are not allow-listed, because the official mirror itself redirects
to third-party mirrors. Environment proxies are never consulted.

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
from typing import Callable, Dict, Optional, Sequence, Tuple

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
_DIGEST_LENGTHS = {"md5": 32, "sha256": 64}
_DIGEST_FUNCTIONS = {"md5": lambda data: hashlib.md5(data, usedforsecurity=False), "sha256": hashlib.sha256}
_PATH_CHARACTERS = re.compile(r"[A-Za-z0-9._~!$&'()*+,;=:@%/-]*")
_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
MAX_RESOLVED_ADDRESSES = 8
_UNSUITABLE_NETWORKS = tuple(ipaddress.ip_network(text) for text in (
    "0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.88.99.0/24", "198.18.0.0/15", "240.0.0.0/4",
    "::/96", "::ffff:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2001::/32",
    "2002::/16", "fec0::/10",
))
_READ_CHUNK = 65536


class RepositoryArtifactRefusal(Exception):
    """Fail-closed refusal. The message is a fixed reason with no URL, path or secret."""


class RepositoryArtifactUnlisted(RepositoryArtifactRefusal):
    """The checksum-verified official index was read and does not list this exact version.

    This is the only refusal that proves the exact original is unavailable. Every other
    refusal (transport, TLS, checksum, ambiguity, malformed index) proves nothing about
    availability and must never lead to a weaker acquisition path (D-033).
    """


@dataclass(frozen=True)
class OfficialRepositoryConfig:
    """The validated single official directory of the bundled repository add-on."""

    index_url: str
    index_name: str
    checksum_url: str
    checksum_name: str
    datadir_url: str
    checksum_algorithm: str = "md5"
    sidecar_algorithm: str = "md5"


def _check_https_authority(parts: urllib.parse.SplitResult, *, queries: Tuple[str, ...] = ("",)) -> None:
    if parts.scheme != "https":
        raise RepositoryArtifactRefusal("official repository URL is not HTTPS")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise RepositoryArtifactRefusal("official repository URL carries credentials")
    if parts.fragment or parts.query not in queries:
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


def _check_segments(segments: Tuple[str, ...]) -> Tuple[str, ...]:
    """Decode path segments once, refusing separators, traversal and double encoding."""
    decoded = tuple(urllib.parse.unquote(segment) for segment in segments)
    for segment in decoded:
        if (segment in ("", ".", "..") or "/" in segment or "\\" in segment or "%" in segment
                or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in segment)):
            raise RepositoryArtifactRefusal("official repository URL path is unsafe")
    return decoded


def _check_path(path: str, *, directory: bool) -> Tuple[str, ...]:
    """Return decoded path segments, refusing anything that could escape the directory."""
    if not path.startswith("/") or path.endswith("/") != directory:
        raise RepositoryArtifactRefusal("official repository URL path is invalid")
    if not _PATH_CHARACTERS.fullmatch(path) or _PERCENT_ESCAPE.search(path):
        raise RepositoryArtifactRefusal("official repository URL path is unsafe")
    segments = path[1:].split("/")
    if directory:
        segments = segments[:-1]
    return _check_segments(tuple(segments))


def _https_url(
    value: object, label: str, *, directory: bool = False, queries: Tuple[str, ...] = ("",),
) -> urllib.parse.SplitResult:
    if not isinstance(value, str):
        raise RepositoryArtifactRefusal(f"bundled repository {label} is invalid")
    text = value.strip()
    if directory and text and not text.endswith("/"):
        text += "/"
    if not text or len(text) > 2048:
        raise RepositoryArtifactRefusal(f"bundled repository {label} is invalid")
    parts = urllib.parse.urlsplit(text)
    _check_https_authority(parts, queries=queries)
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
    hashes = directory.findall("hashes")
    if len(infos) != 1 or len(checksums) != 1 or len(datadirs) != 1 or len(hashes) > 1:
        raise RepositoryArtifactRefusal("bundled repository directory is incomplete or ambiguous")
    info, checksum, datadir = infos[0], checksums[0], datadirs[0]

    index = _https_url(info.text, "index")
    leaf = _leaf(index)
    if leaf not in ("addons.xml", "addons.xml.gz"):
        raise RepositoryArtifactRefusal("bundled repository index name is unexpected")
    index_name = leaf
    compressed = info.get("compressed")
    if compressed is not None and compressed != ("true" if index_name.endswith(".gz") else "false"):
        raise RepositoryArtifactRefusal("bundled repository index declares an unexpected compression")

    # Kodi's descriptor names the digest algorithm. It is honoured, never lowered. A missing
    # ``verify`` attribute is the legacy md5 layout.
    verify = checksum.get("verify")
    if verify is None:
        verify = "md5"
    if verify not in _DIGEST_LENGTHS:
        raise RepositoryArtifactRefusal("bundled repository checksum declares an unsupported algorithm")
    queries = ("", verify) if verify == "sha256" else ("",)
    checksum_url = _https_url(checksum.text, "checksum", queries=queries)
    checksum_name = _leaf(checksum_url)
    if verify == "sha256":
        valid = ((checksum_name == index_name and checksum_url.query == "sha256")
                 or (checksum_name == f"{index_name}.sha256" and not checksum_url.query))
    else:
        valid = checksum_name in (f"{index_name}.md5", "addons.xml.md5") and not checksum_url.query
    if not valid:
        raise RepositoryArtifactRefusal("bundled repository checksum name is unexpected")
    if _parent(checksum_url) != _parent(index) or checksum_url.hostname != index.hostname:
        raise RepositoryArtifactRefusal("bundled repository checksum is outside the index directory")

    sidecar = verify
    if hashes:
        sidecar = (hashes[0].text or "").strip()
        if sidecar not in _DIGEST_LENGTHS:
            raise RepositoryArtifactRefusal("bundled repository declares an unsupported archive hash")
    if datadir.get("zip") not in (None, "true"):
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
        checksum_algorithm=verify,
        sidecar_algorithm=sidecar,
    )


def _redirect_target(current: str, location: object, tail: Tuple[str, ...], queries: Tuple[str, ...]) -> str:
    if not isinstance(location, str) or not location or len(location) > 4096 or location != location.strip():
        raise RepositoryArtifactRefusal("official repository redirect is invalid")
    named = urllib.parse.urlsplit(location)
    # A named scheme must be HTTPS with a host. Otherwise urljoin would silently rebase the hop onto the current host.
    if named.scheme and (named.scheme != "https" or not named.netloc):
        raise RepositoryArtifactRefusal("official repository redirect is invalid")
    # Refuse traversal in the Location as sent, before urljoin can quietly normalise it away.
    if named.path:
        _check_segments(tuple(named.path[1:].split("/") if named.path.startswith("/") else named.path.split("/")))
    target = urllib.parse.urljoin(current, location)
    parts = urllib.parse.urlsplit(target)
    _check_https_authority(parts, queries=queries)
    decoded = _check_path(parts.path, directory=False)
    if decoded[-len(tail):] != tail:
        raise RepositoryArtifactRefusal("official repository redirect changed the archive name")
    return target


def is_public_address(text: object) -> bool:
    """True only for a plain, publicly routable unicast address."""
    if not isinstance(text, str) or "%" in text:
        return False
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    if address.is_multicast or address.is_unspecified or address.is_loopback or address.is_link_local:
        return False
    if any(address in network for network in _UNSUITABLE_NETWORKS if network.version == address.version):
        return False
    return bool(address.is_global)


def _default_resolve(host: str, port: int):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise RepositoryArtifactRefusal("official repository host could not be resolved") from exc
    ordered = []
    for info in infos:
        address = info[4][0]
        if address not in ordered:
            ordered.append(address)
    return ordered


def _tls_context():
    try:
        # Imported here, not at module load, so the capture core imports on hosts without a TLS library.
        import ssl
    except ImportError as exc:
        # Fail closed: without a TLS library there is no HTTPS, and plain HTTP is never an alternative.
        raise RepositoryArtifactRefusal("official repository TLS is unavailable") from exc
    # Certificate and host name verification are on. They are checked against the DNS host.
    return ssl.create_default_context()


class _PinnedHttpsConnection(http.client.HTTPConnection):
    """HTTPS to one already-approved address, verified against the original DNS host name."""

    default_port = 443

    def __init__(self, host, address, port, timeout, context, create_socket=None):
        super().__init__(host, port, timeout=timeout)
        self._address = address
        self._context = context
        self._create_socket = create_socket or socket.create_connection

    def connect(self):
        raw = self._create_socket((self._address, self.port), self.timeout)
        try:
            if ipaddress.ip_address(raw.getpeername()[0]) != ipaddress.ip_address(self._address):
                raise RepositoryArtifactRefusal("official repository connected to an unapproved address")
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _default_connect(host: str, address: str, port: int, timeout: float):
    return _PinnedHttpsConnection(host, address, port, timeout, _tls_context())


class BoundedHttpsGetter:
    """HTTPS GET with fixed size, time, redirect and destination bounds. Sends no credentials.

    ``connect(host, address, port, timeout)`` must connect to exactly ``address`` and verify
    TLS against ``host``. ``resolve(host, port)`` returns the host's addresses.
    """

    def __init__(
        self,
        *,
        connect: Optional[Callable[[str, str, int, float], object]] = None,
        resolve: Optional[Callable[[str, int], Sequence[str]]] = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._connect = connect or _default_connect
        self._resolve = resolve or _default_resolve
        self._timeout = timeout
        self._clock = clock

    def get(self, url: str, *, max_bytes: int, tail: Tuple[str, ...], query: str = "") -> bytes:
        deadline = self._clock() + TRANSFER_BUDGET_SECONDS
        queries = ("", query) if query else ("",)
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            parts = urllib.parse.urlsplit(current)
            status, location, body = self._request_once(
                parts, max_bytes=max_bytes, deadline=deadline, queries=queries,
            )
            if status == 200:
                return body
            if status not in _REDIRECT_STATUSES:
                raise RepositoryArtifactRefusal("official repository returned an unexpected status")
            if hop == MAX_REDIRECTS:
                break
            current = _redirect_target(current, location, tail, queries)
        raise RepositoryArtifactRefusal("official repository redirected too many times")

    def _approved_addresses(self, host: str):
        try:
            resolved = list(self._resolve(host, 443))
        except RepositoryArtifactRefusal:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise RepositoryArtifactRefusal("official repository host could not be resolved") from exc
        if not resolved or len(resolved) > MAX_RESOLVED_ADDRESSES * 4:
            raise RepositoryArtifactRefusal("official repository host could not be resolved")
        # One unsuitable answer taints the whole set: a mixed answer is how rebinding is staged.
        if not all(is_public_address(address) for address in resolved):
            raise RepositoryArtifactRefusal("official repository host resolves to an unsuitable address")
        return resolved[:MAX_RESOLVED_ADDRESSES]

    def _open(self, host: str, addresses):
        timed_out = False
        for address in addresses:
            try:
                return self._connect(host, address, 443, self._timeout)
            except RepositoryArtifactRefusal:
                raise
            except (TimeoutError, socket.timeout):
                timed_out = True
            except (OSError, http.client.HTTPException, ValueError):
                continue
        if timed_out:
            raise RepositoryArtifactRefusal("official repository request timed out")
        raise RepositoryArtifactRefusal("official repository request failed")

    def _request_once(self, parts: urllib.parse.SplitResult, *, max_bytes: int, deadline: float,
                      queries: Tuple[str, ...] = ("",)):
        _check_https_authority(parts, queries=queries)
        connection = None
        try:
            addresses = self._approved_addresses(parts.hostname)
            connection = self._open(parts.hostname, addresses)
            connection.request(
                "GET",
                parts.path + (f"?{parts.query}" if parts.query else ""),
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


def _parse_digest(data: bytes, *, names: Tuple[str, ...], algorithm: str) -> str:
    try:
        text = data.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RepositoryArtifactRefusal("official repository checksum is invalid") from exc
    match = re.fullmatch(rf"([0-9a-fA-F]{{{_DIGEST_LENGTHS[algorithm]}}})(?:[ \t]+\*?(\S+))?", text)
    if match is None:
        raise RepositoryArtifactRefusal("official repository checksum is invalid")
    if match.group(2) is not None and match.group(2) not in names:
        raise RepositoryArtifactRefusal("official repository checksum names a different file")
    return match.group(1).lower()


def _digest(algorithm: str, data: bytes) -> str:
    return _DIGEST_FUNCTIONS[algorithm](data).hexdigest()


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
            raise RepositoryArtifactUnlisted("exact version is not listed in the official index")
        location = entries[key]
        if location is None:
            raise RepositoryArtifactRefusal("official index lists this version ambiguously")
        declared_path, declared_size = location
        filename = f"{addon_id}-{version}.zip"
        relative = f"{addon_id}/{filename}"
        if declared_path is not None and declared_path != relative:
            raise RepositoryArtifactRefusal("official index names a different archive path")
        archive_url = self._config.datadir_url + relative
        algorithm = self._config.sidecar_algorithm
        suffix = "." + algorithm
        sidecar = self._transport.get(
            archive_url + suffix, max_bytes=SIDECAR_MAX_BYTES, tail=(addon_id, filename + suffix),
        )
        expected = _parse_digest(sidecar, names=(filename,), algorithm=algorithm)
        archive = self._transport.get(archive_url, max_bytes=self._archive_max_bytes, tail=(addon_id, filename))
        if declared_size is not None and len(archive) != declared_size:
            raise RepositoryArtifactRefusal("archive size does not match the official index")
        if _digest(algorithm, archive) != expected:
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
        checksum_parts = urllib.parse.urlsplit(config.checksum_url)
        checksum = self._transport.get(
            config.checksum_url, max_bytes=SIDECAR_MAX_BYTES, tail=(config.checksum_name,),
            query=checksum_parts.query,
        )
        algorithm = config.checksum_algorithm
        expected = _parse_digest(
            checksum, names=("addons.xml", "addons.xml.gz", config.checksum_name), algorithm=algorithm,
        )
        raw = self._transport.get(config.index_url, max_bytes=self._index_max_bytes, tail=(config.index_name,))
        if config.index_name.endswith(".gz"):
            xml_bytes = _gunzip_bounded(raw, self._index_max_decompressed_bytes)
            accepted = {_digest(algorithm, raw), _digest(algorithm, xml_bytes)}
        else:
            xml_bytes = raw
            accepted = {_digest(algorithm, raw)}
        if expected not in accepted:
            raise RepositoryArtifactRefusal("official index does not match its checksum")
        return _parse_index(xml_bytes)
