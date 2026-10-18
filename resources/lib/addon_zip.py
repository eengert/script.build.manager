"""One bounded, identity-checked single-directory Kodi package contract.

The archive's root is metadata, not an add-on identity. Original bytes are never
rewritten. No package code is imported. Filesystem writes use no-follow directory
descriptors and exclusive file creation; existing destinations are never replaced.
"""
from dataclasses import dataclass
import io
import os
from pathlib import Path
import re
import stat
import unicodedata
import xml.etree.ElementTree as ET
import zipfile


class AddonZipError(ValueError):
    pass


@dataclass(frozen=True)
class PackageRoot:
    root: str
    addon_id: str
    version: str
    xml_bytes: bytes


class _NoDTD(ET.TreeBuilder):
    def doctype(self, *args):
        raise AddonZipError("package XML DTD is unsupported")


def validated_root(data, expected_addon_id, expected_version=None):
    """Validate every member and CRC before returning verified root/identity."""
    try:
        if not isinstance(data, bytes) or not 0 < len(data) <= 100 * 1024**2:
            raise AddonZipError("package byte limit")
        if not isinstance(expected_addon_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', expected_addon_id):
            raise AddonZipError("invalid expected package identity")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if not 0 < len(infos) <= 20000 or sum(i.file_size for i in infos) > 512 * 1024**2:
                raise AddonZipError("package entry/expanded byte limit")
            roots, entries, spellings, files, parents = set(), set(), {}, set(), set()
            for item in infos:
                name = item.filename
                if (not name or name.startswith('/') or '\\' in name or ':' in name
                        or any(unicodedata.category(c) in ('Cc', 'Cf') for c in name)):
                    raise AddonZipError("unsafe package path")
                parts = name.rstrip('/').split('/')
                if any(p in ('', '.', '..') for p in parts):
                    raise AddonZipError("unsafe package path")
                roots.add(parts[0])
                normalized = '/'.join(parts)
                canonical = unicodedata.normalize('NFC', normalized).casefold()
                if canonical in entries:
                    raise AddonZipError("duplicate/colliding package entries")
                entries.add(canonical)
                for n in range(1, len(parts) + 1):
                    spelling = '/'.join(parts[:n]); key = unicodedata.normalize('NFC', spelling).casefold()
                    if key in spellings and spellings[key] != spelling:
                        raise AddonZipError("ambiguous package path spelling")
                    spellings[key] = spelling
                    if n < len(parts):
                        parents.add(key)
                mode = stat.S_IFMT(item.external_attr >> 16)
                if mode not in (0, stat.S_IFDIR, stat.S_IFREG) or (mode == stat.S_IFDIR and not item.is_dir()):
                    raise AddonZipError("symlink or unsafe package member type")
                if item.is_dir():
                    if mode == stat.S_IFREG:
                        raise AddonZipError("incoherent package member type")
                    parents.add(canonical)
                else:
                    files.add(canonical)
                    if len(parts) < 2:
                        raise AddonZipError("package addon.xml requires one top-level directory")
                if (item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or item.file_size > 128 * 1024**2
                        or item.file_size > max(1, item.compress_size) * 5000):
                    raise AddonZipError("unsafe package compression/size")
                with z.open(item) as stream:
                    while stream.read(1024 * 1024):
                        pass
            if len(roots) != 1 or files.intersection(parents):
                raise AddonZipError("ambiguous package roots or file/directory collision")
            root = next(iter(roots))
            xml_name = root + '/addon.xml'
            if xml_name not in z.namelist() or z.getinfo(xml_name).file_size > 4 * 1024**2:
                raise AddonZipError("package addon.xml unavailable")
            xml = z.read(xml_name)
            addon = ET.fromstring(xml, parser=ET.XMLParser(target=_NoDTD()))
            version = addon.get('version', '')
            if addon.tag != 'addon' or addon.get('id') != expected_addon_id:
                raise AddonZipError("package addon.xml ID does not match expected identity")
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+~-]{0,63}', version):
                raise AddonZipError("package addon.xml version invalid")
            if expected_version is not None and version != expected_version:
                raise AddonZipError("package addon.xml version does not match")
            return PackageRoot(root, expected_addon_id, version, xml)
    except AddonZipError:
        raise
    except Exception as exc:
        raise AddonZipError("package ZIP or invalid XML") from exc


def _directory(path, create=False):
    """Walk from filesystem root through no-follow directory descriptors."""
    absolute = Path(os.path.abspath(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def _write(z, package, fd):
    if os.listdir(fd):
        raise AddonZipError("package extraction destination is not empty")
    for item in z.infolist():
        if item.is_dir():
            continue
        parts = item.filename.split('/')[1:]
        current = os.dup(fd)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, dir_fd=current)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                os.close(current); current = child
            out = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=current)
            with os.fdopen(out, 'wb') as stream, z.open(item) as source:
                while chunk := source.read(1024 * 1024):
                    stream.write(chunk)
        finally:
            os.close(current)


def extract_package(data, addon_id, target, expected_version=None):
    package = validated_root(data, addon_id, expected_version)
    fd = _directory(target, create=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            _write(z, package, fd)
    finally:
        os.close(fd)
    return package


def _rename_exclusive(parent, source, target):
    """Publish a complete sibling directory atomically, refusing every owner.

    Darwin RENAME_EXCL and Linux RENAME_NOREPLACE are kernel no-replace
    operations. Unsupported platforms fail closed; plain POSIX rename is unsafe.
    """
    import ctypes
    import sys
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = libc.renameatx_np
        flag = 4  # RENAME_EXCL, Darwin sys/stdio.h
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        rename = libc.renameat2
        flag = 1  # RENAME_NOREPLACE, Linux stdio.h
    else:
        raise AddonZipError("atomic exclusive package publication unavailable")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(source), parent, os.fsencode(target), flag):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _remove_owned(parent, name, identity):
    """Remove only the pinned owned directory, with no-follow fd traversal."""
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            return  # Preserve ambiguous state.
        for child in os.listdir(fd):
            entry = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(entry.st_mode):
                _remove_owned(fd, child, entry)
            else:
                os.unlink(child, dir_fd=fd)
        entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (entry.st_dev, entry.st_ino) == (identity.st_dev, identity.st_ino):
            os.rmdir(name, dir_fd=parent)
    finally:
        os.close(fd)


def publish_package(data, addon_id, target, expected_version=None):
    """Validate, stage, and atomically publish under the verified ID.

    All directory operations are relative to a no-follow parent descriptor.
    Never replace an existing destination, including an empty directory/symlink.
    Registration must happen only after successful publication.
    """
    import secrets
    package = validated_root(data, addon_id, expected_version)
    target = Path(target)
    if target.name != package.addon_id:
        raise AddonZipError("installation directory differs from verified ID")
    parent = _directory(target.parent)
    stage = '.bm-package-' + secrets.token_hex(16)
    created = False
    identity = None
    try:
        os.mkdir(stage, mode=0o700, dir_fd=parent)
        created = True
        fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            identity = os.fstat(fd)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                _write(z, package, fd)
            # Pin the staged inode through publication, so a replaced stage
            # entry cannot be mistaken for the directory we just populated.
            identity = os.fstat(fd)
            entry = os.stat(stage, dir_fd=parent, follow_symlinks=False)
            if (identity.st_dev, identity.st_ino) != (entry.st_dev, entry.st_ino):
                created = False  # Ambiguous ownership: preserve evidence.
                raise AddonZipError("package stage identity changed")
            _rename_exclusive(parent, stage, target.name)
            created = False
            published = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
            if (identity.st_dev, identity.st_ino) != (published.st_dev, published.st_ino):
                raise AddonZipError("published package identity changed; registration denied")
        finally:
            os.close(fd)
    finally:
        try:
            if created and identity is not None:
                try:
                    _remove_owned(parent, stage, identity)
                except OSError:
                    pass  # Retain uncertain scratch state; preserve original error.
        finally:
            os.close(parent)
    return package
