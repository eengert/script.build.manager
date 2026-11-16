"""Offline tests for the official-repository exact-archive provider and its installed-content gate.

Every HTTPS interaction goes through FakeMirror, which answers from an explicit
route table and never opens a socket. Nothing here reads a real Kodi profile,
application bundle, package cache or artifact store.
"""

import gzip
import hashlib
import http.client
import io
import os
import socket
import tempfile
import unittest
import zipfile
from pathlib import Path

from resources.lib.artifacts import ArtifactStore
from resources.lib.frozen import (
    ArtifactAcquirer,
    CaptureStatus,
    KodiInventoryBackend,
    capture_frozen_build,
)
from resources.lib.official_repository import (
    MAX_REDIRECTS,
    BoundedHttpsGetter,
    OfficialRepositoryProvider,
    RepositoryArtifactRefusal,
    parse_official_repository_config,
)

HOST = "mirrors.kodi.tv"
MIRROR = "mirror.example.org"
INDEX_PATH = "/addons/omega/addons.xml"
GZ_INDEX_PATH = "/addons/omega/addons.xml.gz"
CHECKSUM_PATH = "/addons/omega/addons.xml.md5"
ADDON = "script.module.requests"
VERSION = "2.31.0"
FILENAME = f"{ADDON}-{VERSION}.zip"
ARCHIVE_PATH = f"/addons/omega/{ADDON}/{FILENAME}"
SIDECAR_PATH = ARCHIVE_PATH + ".md5"


def _md5(data):
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _addon_xml(addon_id=ADDON, version=VERSION, requires=""):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{addon_id}" name="{addon_id}" version="{version}" provider-name="Example">'
        f"{requires}"
        '<extension point="xbmc.python.module" library="lib.py"/></addon>\n'
    ).encode("utf-8")


def _addon_zip(addon_id=ADDON, version=VERSION, files=None, root=None, requires=""):
    if files is None:
        files = {"addon.xml": _addon_xml(addon_id, version, requires), "lib.py": b"VALUE = 1\n"}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(f"{root or addon_id}/{name}", data)
    return output.getvalue()


def _index(entries):
    """entries: (addon_id, version, declared_path, declared_size); path and size may be None."""
    parts = ["<?xml version='1.0' encoding='utf-8'?>", "<addons>"]
    for addon_id, version, path, size in entries:
        metadata = ""
        if path is not None or size is not None:
            inner = ""
            if path is not None:
                inner += f"<path>{path}</path>"
            if size is not None:
                inner += f"<size>{size}</size>"
            metadata = f'<extension point="kodi.addon.metadata">{inner}</extension>'
        parts.append(f'<addon id="{addon_id}" version="{version}" name="{addon_id}">{metadata}</addon>')
    parts.append("</addons>")
    return "".join(parts).encode("utf-8")


def _gzip(data):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as stream:
        stream.write(data)
    return output.getvalue()


def _config_xml(*, info=f"https://{HOST}{INDEX_PATH}", compressed="false",
                checksum=f"https://{HOST}{CHECKSUM_PATH}", datadir=f"https://{HOST}/addons/omega/",
                zip_attribute="true", extra_dirs=""):
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<addon id="repository.xbmc.org" name="Kodi Add-on repository" version="1.0.1" provider-name="Team Kodi">'
        '<extension point="xbmc.addon.repository" name="Kodi Add-on repository">'
        f'<dir><info compressed="{compressed}">{info}</info>'
        f"<checksum>{checksum}</checksum>"
        f'<datadir zip="{zip_attribute}">{datadir}</datadir></dir>{extra_dirs}'
        "</extension></addon>"
    ).encode("utf-8")


class _FakeResponse:
    def __init__(self, route):
        self.status = route["status"]
        self._headers = {name.lower(): value for name, value in route["headers"].items()}
        self._body = io.BytesIO(route["body"])
        self._read_error = route["read_error"]

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)

    def read(self, amount=-1):
        if self._read_error is not None:
            raise self._read_error
        return self._body.read(amount)

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, mirror, host):
        self._mirror = mirror
        self._host = host
        self._route = None

    def request(self, method, path, headers=None):
        self._mirror.requests.append((self._host, path))
        route = self._mirror.routes.get((self._host, path))
        if route is None:
            raise AssertionError(f"unrouted request {self._host}{path}")
        self._route = route

    def getresponse(self):
        return _FakeResponse(self._route)

    def close(self):
        pass


class FakeMirror:
    """Answers HTTPS requests from an explicit route table. No socket is ever opened."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        self.connect_errors = {}

    def route(self, host, path, *, status=200, body=b"", headers=None, read_error=None):
        self.routes[(host, path)] = {
            "status": status, "body": body, "headers": dict(headers or {}), "read_error": read_error,
        }

    def redirect(self, host, path, location):
        self.route(host, path, status=302, headers={"Location": location})

    def connect(self, host, port, timeout):
        if port != 443:
            raise AssertionError("non-default port requested")
        error = self.connect_errors.get(host)
        if error is not None:
            raise error
        return _FakeConnection(self, host)

    def publish(self, *, archive, index_xml, compressed=False, sidecar=None, checksum=None):
        """Register a complete official repository for one archive."""
        if compressed:
            self.route(HOST, GZ_INDEX_PATH, body=_gzip(index_xml))
        else:
            self.route(HOST, INDEX_PATH, body=index_xml)
        digest = checksum if checksum is not None else f"{_md5(index_xml)}  addons.xml\n".encode("ascii")
        self.route(HOST, CHECKSUM_PATH, body=digest)
        self.route(HOST, SIDECAR_PATH,
                   body=sidecar if sidecar is not None else f"{_md5(archive)}  {FILENAME}\n".encode("ascii"))
        self.route(HOST, ARCHIVE_PATH, body=archive)


def _standard_index(archive, *, path=f"{ADDON}/{FILENAME}", size=None):
    return _index([(ADDON, VERSION, path, len(archive) if size is None else size)])


def _provider(mirror, *, compressed=False, **limits):
    info = f"https://{HOST}{GZ_INDEX_PATH if compressed else INDEX_PATH}"
    config = parse_official_repository_config(
        _config_xml(info=info, compressed="true" if compressed else "false"),
    )
    return OfficialRepositoryProvider(config, transport=BoundedHttpsGetter(connect=mirror.connect), **limits)


class ConfigurationTests(unittest.TestCase):
    def test_plain_index_configuration_is_accepted(self):
        config = parse_official_repository_config(_config_xml())
        self.assertEqual(f"https://{HOST}{INDEX_PATH}", config.index_url)
        self.assertEqual("addons.xml", config.index_name)
        self.assertEqual("addons.xml.md5", config.checksum_name)
        self.assertEqual(f"https://{HOST}/addons/omega/", config.datadir_url)

    def test_compressed_index_configuration_is_accepted(self):
        config = parse_official_repository_config(
            _config_xml(info=f"https://{HOST}{GZ_INDEX_PATH}", compressed="true"),
        )
        self.assertEqual("addons.xml.gz", config.index_name)
        self.assertEqual(f"https://{HOST}{GZ_INDEX_PATH}", config.index_url)

    def test_unsafe_or_ambiguous_configurations_are_refused(self):
        minimal = (
            b'<?xml version="1.0"?><addon id="repository.xbmc.org" version="1.0.1">'
            b'<extension point="xbmc.addon.repository"><dir>'
            b'<info compressed="false">https://mirrors.kodi.tv/addons/omega/addons.xml</info>'
            b"<checksum>https://mirrors.kodi.tv/addons/omega/addons.xml.md5</checksum>"
            b'<datadir zip="true">https://mirrors.kodi.tv/addons/omega/</datadir>'
            b"</dir></extension></addon>"
        )
        cases = {
            "empty": b"",
            "not xml": b"not xml at all",
            "doctype": b"<!DOCTYPE addon [<!ENTITY x 'y'>]>" + minimal,
            "wrong id": minimal.replace(b'id="repository.xbmc.org"', b'id="repository.other"'),
            "no repository extension": b'<addon id="repository.xbmc.org" version="1.0.1"/>',
            "two directories": minimal.replace(b"</dir>", b"</dir><dir/>"),
            "missing info": minimal.replace(
                b'<info compressed="false">https://mirrors.kodi.tv/addons/omega/addons.xml</info>', b""),
            "unknown compression": _config_xml(compressed="maybe"),
            "index name mismatch": _config_xml(compressed="true"),
            "plain http": _config_xml(info=f"http://{HOST}{INDEX_PATH}"),
            "credentials": _config_xml(info=f"https://user:secret@{HOST}{INDEX_PATH}"),
            "non-default port": _config_xml(info=f"https://{HOST}:8443{INDEX_PATH}"),
            "address literal": _config_xml(info=f"https://203.0.113.5{INDEX_PATH}"),
            "query string": _config_xml(info=f"https://{HOST}{INDEX_PATH}?token=1"),
            "checksum other host": _config_xml(checksum="https://other.example.org/addons/omega/addons.xml.md5"),
            "checksum other name": _config_xml(checksum=f"https://{HOST}/addons/omega/other.md5"),
            "datadir not zip": _config_xml(zip_attribute="false"),
            "datadir without slash": _config_xml(datadir=f"https://{HOST}/addons/omega"),
            "datadir other host": _config_xml(datadir="https://mirror.example.org/addons/omega/"),
            "datadir traversal": _config_xml(datadir=f"https://{HOST}/addons/../omega/"),
            "second directory": _config_xml(extra_dirs="<dir/>"),
        }
        for label, xml_bytes in cases.items():
            with self.subTest(label):
                with self.assertRaises(RepositoryArtifactRefusal):
                    parse_official_repository_config(xml_bytes)


class ProviderIndexTests(unittest.TestCase):
    def test_exact_archive_is_fetched_from_the_official_layout(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_standard_index(archive))
        filename, data = _provider(mirror).fetch_archive(ADDON, VERSION)
        self.assertEqual(FILENAME, filename)
        self.assertEqual(archive, data)
        self.assertEqual(
            [(HOST, CHECKSUM_PATH), (HOST, INDEX_PATH), (HOST, SIDECAR_PATH), (HOST, ARCHIVE_PATH)],
            mirror.requests,
        )
        self.assertFalse(any(f"/{VERSION}/" in path for _, path in mirror.requests))

    def test_gzip_index_is_accepted_with_decompressed_checksum(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        index_xml = _standard_index(archive)
        mirror.publish(archive=archive, index_xml=index_xml, compressed=True)
        self.assertEqual(archive, _provider(mirror, compressed=True).fetch_archive(ADDON, VERSION)[1])

    def test_gzip_index_is_accepted_with_raw_checksum(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        index_xml = _standard_index(archive)
        raw_index = _gzip(index_xml)
        mirror.publish(archive=archive, index_xml=index_xml, compressed=True,
                       checksum=f"{_md5(raw_index)}  addons.xml.gz\n".encode("ascii"))
        mirror.route(HOST, GZ_INDEX_PATH, body=raw_index)
        self.assertEqual(archive, _provider(mirror, compressed=True).fetch_archive(ADDON, VERSION)[1])

    def test_index_checksum_mismatch_is_refused_before_any_archive_request(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_standard_index(archive),
                       checksum=f"{'0' * 32}  addons.xml\n".encode("ascii"))
        with self.assertRaises(RepositoryArtifactRefusal):
            _provider(mirror).fetch_archive(ADDON, VERSION)
        self.assertNotIn((HOST, ARCHIVE_PATH), mirror.requests)

    def test_missing_id_is_refused_without_archive_request(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_index([("other.addon", VERSION, None, None)]))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "not listed"):
            _provider(mirror).fetch_archive(ADDON, VERSION)
        self.assertNotIn((HOST, ARCHIVE_PATH), mirror.requests)

    def test_wrong_version_is_refused_without_fallback(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_index([(ADDON, "2.31.1", None, None)]))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "not listed"):
            _provider(mirror).fetch_archive(ADDON, VERSION)
        self.assertNotIn((HOST, ARCHIVE_PATH), mirror.requests)

    def test_ambiguous_index_entry_is_refused(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_index([
            (ADDON, VERSION, None, None), (ADDON, VERSION, None, None),
        ]))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "ambiguously"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_declared_archive_path_must_name_the_exact_archive(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_standard_index(archive, path=f"{ADDON}/other.zip"))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "different archive path"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_declared_size_must_match_the_downloaded_archive(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_standard_index(archive, size=len(archive) + 1))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "size does not match"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_invalid_declared_size_refuses_the_index(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        xml = (b"<?xml version='1.0'?><addons><addon id=\"%s\" version=\"%s\">"
               b'<extension point="kodi.addon.metadata"><size>12x</size></extension>'
               b"</addon></addons>") % (ADDON.encode(), VERSION.encode())
        mirror.publish(archive=archive, index_xml=xml)
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "size is invalid"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_index_with_wrong_root_or_doctype_is_refused(self):
        archive = _addon_zip()
        for label, xml in {
            "wrong root": b"<catalog><addon id=\"x\" version=\"1\"/></catalog>",
            "doctype": b"<!DOCTYPE addons [<!ENTITY a 'b'>]><addons/>",
            "malformed": b"<addons><addon",
        }.items():
            with self.subTest(label):
                mirror = FakeMirror()
                mirror.publish(archive=archive, index_xml=xml)
                with self.assertRaisesRegex(RepositoryArtifactRefusal, "index is invalid"):
                    _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_oversized_index_is_refused(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_standard_index(archive))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "exceeds its size limit"):
            _provider(mirror, index_max_bytes=64).fetch_archive(ADDON, VERSION)

    def test_gzip_bomb_is_refused_by_decompressed_limit(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_standard_index(archive), compressed=True)
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "decompressed size limit"):
            _provider(mirror, compressed=True, index_max_decompressed_bytes=64).fetch_archive(ADDON, VERSION)

    def test_index_refusal_is_cached_for_one_run(self):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_standard_index(archive))
        mirror.route(HOST, INDEX_PATH, status=404)
        provider = _provider(mirror)
        with self.assertRaises(RepositoryArtifactRefusal):
            provider.fetch_archive(ADDON, VERSION)
        requests_after_first = len(mirror.requests)
        with self.assertRaises(RepositoryArtifactRefusal):
            provider.fetch_archive(ADDON, VERSION)
        self.assertEqual(requests_after_first, len(mirror.requests))


class ProviderArchiveTests(unittest.TestCase):
    def _published(self, **overrides):
        mirror = FakeMirror()
        archive = _addon_zip()
        mirror.publish(archive=archive, index_xml=_standard_index(archive))
        for (host, path), value in overrides.items():
            mirror.route(host, path, **value)
        return mirror, archive

    def test_sidecar_digest_mismatch_is_refused(self):
        mirror, _ = self._published()
        mirror.route(HOST, SIDECAR_PATH, body=f"{'0' * 32}  {FILENAME}\n".encode("ascii"))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "does not match the official sidecar"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_sidecar_naming_another_file_is_refused(self):
        mirror, archive = self._published()
        mirror.route(HOST, SIDECAR_PATH, body=f"{_md5(archive)}  other.zip\n".encode("ascii"))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "different file"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_malformed_sidecar_is_refused(self):
        mirror, _ = self._published()
        mirror.route(HOST, SIDECAR_PATH, body=b"not a checksum")
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "checksum is invalid"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_archive_bytes_that_differ_from_the_sidecar_are_refused(self):
        mirror, archive = self._published()
        tampered = bytearray(archive)
        tampered[-1] ^= 0x01
        mirror.route(HOST, ARCHIVE_PATH, body=bytes(tampered))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "does not match the official sidecar"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_declared_content_length_above_limit_is_refused_before_reading(self):
        mirror, archive = self._published()
        mirror.route(HOST, ARCHIVE_PATH, body=archive, headers={"Content-Length": str(10 ** 9)})
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "exceeds its size limit"):
            _provider(mirror, archive_max_bytes=len(archive) - 1).fetch_archive(ADDON, VERSION)

    def test_body_above_limit_without_declared_length_is_refused(self):
        mirror, archive = self._published()
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "exceeds its size limit"):
            _provider(mirror, archive_max_bytes=len(archive) - 1).fetch_archive(ADDON, VERSION)

    def test_truncated_body_is_refused(self):
        mirror, archive = self._published()
        mirror.route(HOST, ARCHIVE_PATH, body=archive, headers={"Content-Length": str(len(archive) + 100)})
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "truncated"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_incomplete_read_is_refused_as_truncated(self):
        mirror, archive = self._published()
        mirror.route(HOST, ARCHIVE_PATH, body=archive[:10],
                     read_error=http.client.IncompleteRead(b"partial"))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "truncated"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_unexpected_status_is_refused(self):
        mirror, _ = self._published()
        mirror.route(HOST, ARCHIVE_PATH, status=404, body=b"missing")
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "unexpected status"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_content_encoding_is_refused(self):
        mirror, archive = self._published()
        mirror.route(HOST, ARCHIVE_PATH, body=archive, headers={"Content-Encoding": "gzip"})
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "encoding is unsupported"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_timeout_is_reported_safely(self):
        mirror, _ = self._published()
        mirror.connect_errors[HOST] = TimeoutError("timed out")
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "timed out"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_socket_timeout_while_reading_is_reported_safely(self):
        mirror, archive = self._published()
        mirror.route(HOST, ARCHIVE_PATH, body=archive, read_error=socket.timeout("timed out"))
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "timed out"):
            _provider(mirror).fetch_archive(ADDON, VERSION)

    def test_network_failure_is_reported_without_exception_text(self):
        mirror, _ = self._published()
        mirror.connect_errors[HOST] = OSError("network unreachable at 203.0.113.9")
        with self.assertRaises(RepositoryArtifactRefusal) as context:
            _provider(mirror).fetch_archive(ADDON, VERSION)
        self.assertEqual("official repository request failed", str(context.exception))

    def test_identity_with_path_characters_is_refused_before_any_request(self):
        mirror, _ = self._published()
        for addon_id in ("plugin/evil", "../evil", "a b"):
            with self.subTest(addon_id):
                with self.assertRaisesRegex(RepositoryArtifactRefusal, "identity is invalid"):
                    _provider(mirror).fetch_archive(addon_id, VERSION)
        self.assertEqual([], mirror.requests)


class RedirectPolicyTests(unittest.TestCase):
    TAIL = (ADDON, FILENAME)

    def _getter(self, mirror):
        return BoundedHttpsGetter(connect=mirror.connect)

    def _url(self):
        return f"https://{HOST}{ARCHIVE_PATH}"

    def test_redirect_to_another_https_mirror_is_followed(self):
        mirror = FakeMirror()
        mirror.redirect(HOST, ARCHIVE_PATH, f"https://{MIRROR}/kodi/addons/omega/{ADDON}/{FILENAME}")
        mirror.route(MIRROR, f"/kodi/addons/omega/{ADDON}/{FILENAME}", body=b"ZIPBYTES")
        self.assertEqual(b"ZIPBYTES", self._getter(mirror).get(self._url(), max_bytes=100, tail=self.TAIL))

    def test_relative_redirect_stays_on_the_same_host(self):
        mirror = FakeMirror()
        mirror.redirect(HOST, ARCHIVE_PATH, f"/mirror/{ADDON}/{FILENAME}")
        mirror.route(HOST, f"/mirror/{ADDON}/{FILENAME}", body=b"ZIPBYTES")
        self.assertEqual(b"ZIPBYTES", self._getter(mirror).get(self._url(), max_bytes=100, tail=self.TAIL))

    def test_unsafe_redirects_are_refused(self):
        unsafe = {
            "plain http": f"http://{MIRROR}/kodi/{ADDON}/{FILENAME}",
            "credentials": f"https://user:secret@{MIRROR}/kodi/{ADDON}/{FILENAME}",
            "address literal": f"https://192.0.2.10/kodi/{ADDON}/{FILENAME}",
            "non-default port": f"https://{MIRROR}:8443/kodi/{ADDON}/{FILENAME}",
            "query string": f"https://{MIRROR}/kodi/{ADDON}/{FILENAME}?token=1",
            "fragment": f"https://{MIRROR}/kodi/{ADDON}/{FILENAME}#x",
            "changed archive name": f"https://{MIRROR}/kodi/{ADDON}/other.zip",
            "dot segments": f"https://{MIRROR}/kodi/../{ADDON}/{FILENAME}",
            "encoded dot segments": f"https://{MIRROR}/kodi/%2e%2e/{ADDON}/{FILENAME}",
            "single-label host": f"https://localhost/kodi/{ADDON}/{FILENAME}",
            "missing scheme host": f"https:///kodi/{ADDON}/{FILENAME}",
        }
        for label, location in unsafe.items():
            with self.subTest(label):
                mirror = FakeMirror()
                mirror.redirect(HOST, ARCHIVE_PATH, location)
                mirror.route(MIRROR, f"/kodi/{ADDON}/{FILENAME}", body=b"SHOULD-NOT-BE-READ")
                with self.assertRaises(RepositoryArtifactRefusal):
                    self._getter(mirror).get(self._url(), max_bytes=100, tail=self.TAIL)
                self.assertFalse(any(host == MIRROR for host, _ in mirror.requests))

    def test_redirect_loop_is_bounded(self):
        mirror = FakeMirror()
        mirror.redirect(HOST, ARCHIVE_PATH, self._url())
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "redirected too many times"):
            self._getter(mirror).get(self._url(), max_bytes=100, tail=self.TAIL)
        self.assertEqual(MAX_REDIRECTS + 1, len(mirror.requests))

    def test_redirect_without_location_is_refused(self):
        mirror = FakeMirror()
        mirror.route(HOST, ARCHIVE_PATH, status=302)
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "redirect is invalid"):
            self._getter(mirror).get(self._url(), max_bytes=100, tail=self.TAIL)


class ConfiguredProviderPrivacyTests(unittest.TestCase):
    def test_refusal_messages_contain_no_url_credentials_or_host(self):
        messages = []
        archive = _addon_zip()
        scenarios = [
            lambda m: m.route(HOST, INDEX_PATH, status=500),
            lambda m: m.connect_errors.__setitem__(HOST, OSError("secret-token-value")),
            lambda m: m.route(HOST, ARCHIVE_PATH, status=302, headers={"Location": "http://x.example.org/a"}),
        ]
        for scenario in scenarios:
            mirror = FakeMirror()
            mirror.publish(archive=archive, index_xml=_standard_index(archive))
            scenario(mirror)
            with self.assertRaises(RepositoryArtifactRefusal) as context:
                _provider(mirror).fetch_archive(ADDON, VERSION)
            messages.append(str(context.exception))
        for message in messages:
            for forbidden in ("https", "http://", "@", HOST, MIRROR, "secret", "/addons", "x.example.org"):
                self.assertNotIn(forbidden, message)


class OfficialBackendFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "home" / "addons"
        self.application = self.base / "application" / "addons"
        self.packages = self.base / "packages"
        self.store_root = self.base / "store"
        self.home.mkdir(parents=True)
        self.application.mkdir(parents=True)
        self.packages.mkdir()
        self.store = ArtifactStore(self.store_root)
        self.mirror = FakeMirror()
        self.archive = _addon_zip()
        self.index_xml = _standard_index(self.archive)
        self.mirror.publish(archive=self.archive, index_xml=self.index_xml)
        self.install_bundled_configuration()
        self.installed_files = {"addon.xml": _addon_xml(), "lib.py": b"VALUE = 1\n"}
        self.install(ADDON, self.installed_files)
        self.listing = [self.listing_entry(ADDON)]

    def install_bundled_configuration(self, xml_bytes=None):
        directory = self.application / "repository.xbmc.org"
        directory.mkdir(exist_ok=True)
        (directory / "addon.xml").write_bytes(_config_xml() if xml_bytes is None else xml_bytes)

    def install(self, addon_id, files, *, root=None):
        directory = (root or self.home) / addon_id
        for name, data in files.items():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return directory

    def listing_entry(self, addon_id, *, version=VERSION, path=None, addon_type="xbmc.python.module"):
        return {
            "addonid": addon_id, "version": version, "enabled": True, "installed": True, "broken": False,
            "path": path if path is not None else f"special://home/addons/{addon_id}/",
            "type": addon_type, "dependencies": [],
        }

    def backend(self, *, listing=None, application=True, recorded=None):
        entries = self.listing if listing is None else listing

        def rpc(method, params):
            if recorded is not None:
                recorded.append((method, params))
            if method == "Addons.GetAddons":
                return {"addons": [dict(entry) for entry in entries]}
            if method == "Application.GetProperties":
                return {"version": {"major": 21, "minor": 3}}
            raise AssertionError(method)

        kwargs = {"application_addons_dir": self.application} if application else {}
        return KodiInventoryBackend(
            rpc, addons_dir=self.home, package_cache_dir=self.packages,
            https_connect=self.mirror.connect, **kwargs,
        )

    def acquire(self, backend=None):
        backend = backend or self.backend()
        return ArtifactAcquirer(self.store, backend).acquire(ADDON, VERSION)

    def stored_artifacts(self):
        return sorted(path.name for path in (self.store_root / "artifacts").iterdir())

    def assertNoRegistration(self):
        self.assertEqual([], self.stored_artifacts())


class OfficialBackendAcquisitionTests(OfficialBackendFixture):
    def test_exact_official_archive_is_acquired_when_installed_content_matches(self):
        result = self.acquire()
        self.assertEqual(CaptureStatus.COMPLETE, result.status)
        self.assertEqual("repository", result.source)
        self.assertEqual(hashlib.sha256(self.archive).hexdigest(), result.metadata.sha256)
        self.assertEqual("repository", result.metadata.source)
        self.assertEqual(4, len(self.mirror.requests))

    def test_installed_bytecode_caches_do_not_block_acquisition(self):
        self.install(ADDON, {
            "__pycache__/lib.cpython-311.pyc": b"\x00bytecode",
            "lib.pyo": b"\x00optimized",
            "resources/cache.pyc": b"\x00bytecode",
        })
        self.assertEqual(CaptureStatus.COMPLETE, self.acquire().status)

    def test_modified_installed_file_is_refused_and_registers_nothing(self):
        (self.home / ADDON / "lib.py").write_bytes(b"VALUE = 2\n")
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("differs from the official archive", result.error)
        self.assertNoRegistration()

    def test_extra_installed_file_is_refused(self):
        (self.home / ADDON / "notes.txt").write_bytes(b"local edit")
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertNoRegistration()

    def test_missing_installed_file_is_refused(self):
        (self.home / ADDON / "lib.py").unlink()
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertNoRegistration()

    def test_symbolic_link_is_refused_before_any_network_request(self):
        os.symlink("lib.py", self.home / ADDON / "alias.py")
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("symbolic link", result.error)
        self.assertEqual([], self.mirror.requests)
        self.assertNoRegistration()

    def test_special_file_is_refused_before_any_network_request(self):
        os.mkfifo(self.home / ADDON / "pipe")
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("unsupported file type", result.error)
        self.assertEqual([], self.mirror.requests)

    def test_unsafe_installed_name_is_refused_before_any_network_request(self):
        (self.home / ADDON / "bad\\name.py").write_bytes(b"x = 1\n")
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("unsafe name", result.error)
        self.assertEqual([], self.mirror.requests)

    def test_archive_root_must_name_the_add_on(self):
        archive = _addon_zip(root="other.addon")
        self.mirror.publish(archive=archive, index_xml=_standard_index(archive))
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("root does not match", result.error)
        self.assertNoRegistration()

    def test_archive_with_another_version_fails_exact_validation(self):
        archive = _addon_zip(version="2.31.1")
        self.mirror.publish(archive=archive, index_xml=_standard_index(archive))
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("failed exact validation", result.error)
        self.assertNoRegistration()

    def test_archive_with_another_add_on_identity_fails_exact_validation(self):
        archive = _addon_zip(files={"addon.xml": _addon_xml("script.module.other"), "lib.py": b"VALUE = 1\n"})
        self.mirror.publish(archive=archive, index_xml=_standard_index(archive))
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("failed exact validation", result.error)
        self.assertNoRegistration()

    def test_store_priority_skips_the_repository(self):
        self.store.import_zip(self.archive, expected_addon_id=ADDON, expected_version=VERSION,
                              source="package_cache")
        self.mirror.requests.clear()
        result = self.acquire()
        self.assertEqual(CaptureStatus.COMPLETE, result.status)
        self.assertEqual("artifact_store", result.source)
        self.assertEqual([], self.mirror.requests)

    def test_package_cache_priority_skips_the_repository(self):
        (self.packages / FILENAME).write_bytes(self.archive)
        result = self.acquire()
        self.assertEqual(CaptureStatus.COMPLETE, result.status)
        self.assertEqual("package_cache", result.source)
        self.assertEqual([], self.mirror.requests)

    def test_network_failure_is_reported_and_registers_nothing(self):
        self.mirror.connect_errors[HOST] = OSError("network down")
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("official repository request failed", result.error)
        self.assertNoRegistration()

    def test_missing_bundled_configuration_is_refused_without_network(self):
        (self.application / "repository.xbmc.org" / "addon.xml").unlink()
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("bundled official repository configuration is unavailable", result.error)
        self.assertEqual([], self.mirror.requests)

    def test_invalid_bundled_configuration_is_refused_without_network(self):
        self.install_bundled_configuration(_config_xml(info=f"http://{HOST}{INDEX_PATH}"))
        result = self.acquire()
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertEqual([], self.mirror.requests)
        self.assertNoRegistration()

    def test_missing_application_root_is_refused_without_network(self):
        result = self.acquire(self.backend(application=False))
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("trusted application repository configuration is unavailable", result.error)
        self.assertEqual([], self.mirror.requests)

    def test_untrusted_installed_location_is_refused_without_network(self):
        outside = self.base / "outside" / ADDON
        self.install(ADDON, self.installed_files, root=self.base / "outside")
        listing = [self.listing_entry(ADDON, path=str(outside) + "/")]
        result = self.acquire(self.backend(listing=listing))
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn("not trusted", result.error)
        self.assertEqual([], self.mirror.requests)

    def test_platform_provided_add_on_is_never_fetched(self):
        pil_directory = self.application / "script.module.pil"
        pil_directory.mkdir()
        (pil_directory / "addon.xml").write_bytes(_addon_xml("script.module.pil", "5.1.0"))
        backend = self.backend(listing=[self.listing_entry(
            "script.module.pil", version="5.1.0", path="special://xbmc/addons/script.module.pil/")])
        with self.assertRaisesRegex(RepositoryArtifactRefusal, "never acquired"):
            backend.get_repository_artifact("script.module.pil", "5.1.0")
        self.assertEqual([], self.mirror.requests)

    def test_installed_listing_requests_the_type_property(self):
        recorded = []
        self.backend(recorded=recorded).get_installed_addons()
        methods = [params for method, params in recorded if method == "Addons.GetAddons"]
        self.assertTrue(methods)
        self.assertIn("type", methods[0]["properties"])

    def test_capture_acquires_the_managed_root_and_keeps_pil_platform_provided(self):
        pil_directory = self.application / "script.module.pil"
        pil_directory.mkdir()
        (pil_directory / "addon.xml").write_bytes(_addon_xml("script.module.pil", "5.1.0"))
        requires = '<requires><import addon="script.module.pil" version="5.1.0"/></requires>'
        archive = _addon_zip(requires=requires)
        self.mirror.publish(archive=archive, index_xml=_standard_index(archive))
        self.install(ADDON, {"addon.xml": _addon_xml(requires=requires), "lib.py": b"VALUE = 1\n"})
        listing = [self.listing_entry(ADDON),
                   self.listing_entry("script.module.pil", version="5.1.0",
                                      path="special://xbmc/addons/script.module.pil/")]
        result = capture_frozen_build(
            backend=self.backend(listing=listing), store=self.store, root_addon_ids=[ADDON],
            build_id="build-official-repository", name="Official repository fixture", created_at="now",
        )
        statuses = {node.addon_id: node.status for node in result.manifest.addons}
        self.assertEqual(CaptureStatus.COMPLETE, statuses[ADDON])
        self.assertEqual(CaptureStatus.PLATFORM_PROVIDED, statuses["script.module.pil"])
        self.assertFalse(any("script.module.pil" in path for _, path in self.mirror.requests))
        managed = next(node for node in result.manifest.addons if node.addon_id == ADDON)
        self.assertEqual("repository", managed.artifact.source)


if __name__ == "__main__":
    unittest.main()
