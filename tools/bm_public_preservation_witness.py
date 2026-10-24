"""Offline-copy-only semantic comparison, never a live profile admission tool.

Only fixed public files are read. PRESERVED names a projection, not a profile or
Item 7 PASS. Addons33 retains the existing identity/enabled-only witness; its
other tables/fields remain UNVERIFIED. No values or value digests leave compare().
Inputs must be quiescent, independently obtained copies. This tool cannot recover
October 16 before-values from hashes or establish native snapshot provenance.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET

try:
    from tools import bm_profile_isolation as isolation
    from tools import bm_test_app as bm
except ModuleNotFoundError:
    import bm_profile_isolation as isolation
    import bm_test_app as bm

ROOT = Path(__file__).absolute().parents[1]
FILES = (
    'userdata/Database/Addons33.db',
    'userdata/Database/Textures13.db',
    'userdata/guisettings.xml',
    'userdata/addon_data/skin.estuary/settings.xml',
    'userdata/peripheral_data/application_Keyboard.xml',
)
MAX_XML = 2 << 20
MAX_DB = 32 << 20
MAX_ROWS = 10000
# Kodi 21.3-Omega TextureDatabase::CreateTables/CreateAnalytics and
# dbwrappers/Database.cpp::CreateDatabase. Only these exact schema objects.
TEXTURE_SQL = (
    'CREATE TABLE version (idVersion integer, iCompressCount integer)',
    'CREATE TABLE texture (id integer primary key, url text, cachedurl text, imagehash text, lasthashcheck text)',
    'CREATE TABLE sizes (idtexture integer, size integer, width integer, height integer, usecount integer, lastusetime text)',
    'CREATE TABLE path (id integer primary key, url text, type text, texture text)',
    'CREATE INDEX idxTexture ON texture(url)',
    'CREATE INDEX idxSize ON sizes(idtexture, size)',
    'CREATE INDEX idxSize2 ON sizes(idtexture, width, height)',
    'CREATE INDEX idxPath ON path(url, type)',
    'CREATE TRIGGER textureDelete AFTER delete ON texture FOR EACH ROW BEGIN delete from sizes where sizes.idtexture=old.id; END',
)
SCOPES = ('installed.addonID,enabled ONLY; all other Addons33 content UNVERIFIED',
          'Textures13 exact schema and all typed rows, including usage/version fields',
          'flat settings-v2 records; explicit default flags and exact text values',
          'skin settings string/bool records', 'peripheral settings exact string records')


class Unverified(Exception):
    """Fixed codes only; never forward parser, filesystem or SQLite messages."""


def require(ok, code='unsupported_schema'):
    if not ok:
        raise Unverified(code)


def offline_root(value):
    raw = os.fspath(value)
    path = Path(raw)
    require(len(raw) <= 4096 and path.is_absolute() and os.path.normpath(raw) == raw and '..' not in path.parts,
            'unsafe_root')
    allowed = (Path('/private/tmp'), ROOT / '.qualification-evidence')
    require(any(base in path.parents for base in allowed) and not bm.is_forbidden_path(raw)
            and not any(part.casefold().endswith('.app') for part in path.parts), 'unsafe_root')
    return path


def identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_size,
            st.st_mtime_ns, st.st_ctime_ns)


def read_copy(root, relative, limit):
    """Reuse isolation's pinned ancestor reader; never open SQLite on the input."""
    with isolation.directory(root) as root_fd, contextlib.ExitStack() as stack:
        fd = root_fd
        links = []
        for part in Path(relative).parts[:-1]:
            child = os.open(part, isolation.DIR, dir_fd=fd)
            stack.callback(os.close, child)
            st = os.fstat(child)
            require(st.st_dev == os.fstat(root_fd).st_dev, 'unsafe_node')
            links.append((fd, part, child, (st.st_dev, st.st_ino)))
            fd = child
        name = Path(relative).name
        def sidecars_absent():
            if name.endswith('.db'):
                for suffix in ('-wal', '-shm', '-journal'):
                    require(isolation.exists(fd, name + suffix) is None, 'sqlite_sidecar_uncertain')
        sidecars_absent()
        st = isolation.exists(fd, name)
        if st is None:
            return None, None
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size <= limit,
                'unsafe_node')
        leaf = os.open(name, bm._read_flags(), dir_fd=fd)
        stack.callback(os.close, leaf)
        require(identity(st) == identity(os.fstat(leaf)), 'input_changed')
        chunks = []; total = 0
        while total <= limit:
            data = os.read(leaf, min(65536, limit + 1 - total))
            if not data:
                break
            chunks.append(data); total += len(data)
        require(total == st.st_size and total <= limit, 'input_changed')
        require(identity(st) == identity(os.fstat(leaf)) == identity(os.stat(
            name, dir_fd=fd, follow_symlinks=False)), 'input_changed')
        sidecars_absent()
        for parent, part, child, expected in links:
            linked = os.stat(part, dir_fd=parent, follow_symlinks=False)
            require(stat.S_ISDIR(linked.st_mode) and (linked.st_dev, linked.st_ino) == expected
                    and (os.fstat(child).st_dev, os.fstat(child).st_ino) == expected, 'input_changed')
        with isolation.directory(root) as again:
            require((os.fstat(again).st_dev, os.fstat(again).st_ino) ==
                    (os.fstat(root_fd).st_dev, os.fstat(root_fd).st_ino), 'input_changed')
        return b''.join(chunks), identity(st)


def xml_projection(raw, kind):
    require(len(raw) <= MAX_XML, 'input_too_large')
    raw.decode('utf-8')
    require(b'\x00' not in raw and b'<!' not in raw and b'<?' not in raw.replace(
        b'<?xml version="1.0" encoding="UTF-8"?>', b''), 'unsafe_xml')
    # Existing entity/DTD refusal is reused before full, strictly bounded XML parsing.
    bm.extract_settings(raw, ())
    root = ET.fromstring(raw)
    require(root.tag == 'settings' and not (root.text or '').strip())
    require(root.attrib == ({'version': '2'} if kind == 2 else {})
            or (kind == 3 and root.attrib == {'version': '2'}))
    require(len(root) <= MAX_ROWS, 'input_too_large')
    rows = {}
    for child in root:
        require(child.tag == 'setting' and not list(child) and not (child.tail or '').strip())
        require('id' in child.attrib and bool(child.attrib['id']))
        key = child.attrib['id']; require(key not in rows)
        text = child.text or ''
        if kind == 2:
            require(set(child.attrib) <= {'id', 'default'})
            flag = child.get('default')
            require(flag in (None, 'true', 'false'))
            # Unknown setting definitions are not guessed: serialized text is exact.
            value = ('serialized_text', flag, text)
        elif kind == 3:
            require(set(child.attrib) == {'id', 'type'})
            typ = child.attrib['type']; require(typ in ('bool', 'string'))
            require(typ != 'bool' or text in ('true', 'false'))
            value = (typ, text == 'true' if typ == 'bool' else text)
        else:
            require(set(child.attrib) == {'id', 'value'} and not text.strip())
            value = ('serialized_string', child.attrib['value'])
        rows[key] = value
    # Version metadata is evidence too; never silently erase a root-attribute change.
    return (tuple(sorted(root.attrib.items())), sorted(rows.items()))


def sql_normalize(sql):
    # Preserve token boundaries: INTEGER PRIMARY KEY != INTEGERPRIMARYKEY.
    tokens = re.findall(r'[A-Za-z_][A-Za-z_0-9]*|[(),=.;]', sql)
    require(''.join(tokens) == re.sub(r'\s+', '', sql))
    if tokens and tokens[-1] == ';':
        tokens.pop()
    return tuple(token.lower() for token in tokens)


def texture_projection(path):
    uri = 'file:' + urllib.parse.quote(os.fspath(path)) + '?mode=ro&immutable=1'
    connection = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        path.unlink()  # private copy only, before any schema/record query
        connection.execute('PRAGMA query_only=1')
        connection.execute('PRAGMA trusted_schema=OFF')
        budget = [0]
        def bounded():
            budget[0] += 1
            return int(budget[0] > 20000)
        connection.set_progress_handler(bounded, 1000)
        require(connection.execute('PRAGMA integrity_check(1)').fetchall() == [('ok',)])
        schema = connection.execute('SELECT sql FROM sqlite_master LIMIT 33').fetchall()
        require(len(schema) == len(TEXTURE_SQL) and all(type(row[0]) is str for row in schema))
        require({sql_normalize(row[0]) for row in schema} == {sql_normalize(s) for s in TEXTURE_SQL})
        result = []
        for table, kinds in (('version', 'ii'), ('texture', 'itttt'), ('sizes', 'iiiiit'), ('path', 'ittt')):
            rows = connection.execute('SELECT * FROM ' + table + ' LIMIT 10001').fetchall()
            require(len(rows) <= MAX_ROWS, 'input_too_large')
            for row in rows:
                require(len(row) == len(kinds))
                require(all(value is None or type(value) is (int if typ == 'i' else str)
                            for value, typ in zip(row, kinds)))
            if table == 'version':
                require(len(rows) == 1 and type(rows[0][0]) is int and rows[0][0] == 13
                        and type(rows[0][1]) is int)
            # Typed JSON bytes permit multiset ordering with NULL; remain in memory only.
            result.append((table, sorted(json.dumps(row, ensure_ascii=True).encode() for row in rows)))
        return result
    finally:
        connection.close()


def database_projection(raw, kind):
    """Disposable copy pattern matches the accepted public witness's cleanup gate."""
    require(raw[:16] == b'SQLite format 3\x00')
    # WAL-mode headers are uncertain even if sidecar copies have been omitted.
    require(len(raw) >= 100 and raw[18:20] == b'\x01\x01', 'sqlite_wal_mode_uncertain')
    result = None
    with tempfile.TemporaryDirectory(prefix='bm-semantic-', dir='/private/tmp') as temp:
        path = Path(temp) / 'copy.db'
        try:
            with path.open('xb') as stream:
                os.fchmod(stream.fileno(), 0o600); stream.write(raw)
            if kind == 0:
                report = {'status': 'UNKNOWN', 'integrity': 'UNKNOWN', 'schema': 'UNKNOWN',
                          'other_fields': 'UNKNOWN', 'entries': [], 'count': 0}
                projected = bm._project_public_database(path, report)
                require(projected['status'] == 'KNOWN')
                result = sorted((e['id'], e['enabled']) for e in projected['entries'])
            else:
                result = texture_projection(path)
        finally:
            path.unlink(missing_ok=True)
    # Context cleanup/connection errors prevent return of a known projection.
    return result


def compare(before, after):
    """Only this sanitized result is public; all private comparisons die in memory."""
    reports = [{'file': name, 'scope': scope, 'status': 'UNVERIFIED', 'reason': 'not_observed'}
               for name, scope in zip(FILES, SCOPES)]
    result = {'schema': 'bm-offline-semantic-comparison/1', 'scope_result': 'UNVERIFIED',
              'complete_preservation': 'UNVERIFIED', 'qualification': 'not_qualified', 'files': reports}
    try:
        roots = [offline_root(before), offline_root(after)]
        require(roots[0] != roots[1] and roots[0] not in roots[1].parents
                and roots[1] not in roots[0].parents, 'unsafe_root')
        observations = []
        for root in roots:
            observations.append([read_copy(root, name, MAX_DB if i < 2 else MAX_XML)
                                 for i, name in enumerate(FILES)])
        for i, report in enumerate(reports):
            try:
                values = []
                for snapshot in observations:
                    raw = snapshot[i][0]
                    values.append(None if raw is None else (database_projection(raw, i) if i < 2
                                                          else xml_projection(raw, i)))
                require(values != [None, None], 'missing_input')
                report.update(status='PRESERVED' if values[0] == values[1] else 'CHANGED_OR_MISSING',
                              reason='scoped_comparison')
            except (Unverified, OSError, ValueError, sqlite3.Error, ET.ParseError) as ex:
                report['reason'] = str(ex) if isinstance(ex, Unverified) else 'unsupported_or_malformed'
        # Re-read all sources through the same pinned/no-follow readers; reject moving observations.
        for root, snapshot in zip(roots, observations):
            require(snapshot == [read_copy(root, name, MAX_DB if i < 2 else MAX_XML)
                                 for i, name in enumerate(FILES)], 'input_changed')
        if all(r['status'] != 'UNVERIFIED' for r in reports):
            result['scope_result'] = ('PRESERVED' if all(r['status'] == 'PRESERVED' for r in reports)
                                      else 'CHANGED_OR_MISSING')
    except (Unverified, OSError, ValueError, TypeError) as ex:
        reason = str(ex) if isinstance(ex, Unverified) else 'unverifiable_input'
        for report in reports:
            report.update(status='UNVERIFIED', reason=reason)
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Unverified('arguments_invalid')


def main(argv=None):
    parser = Parser(description='Compare two quiescent offline copies; never reads live profiles.')
    parser.add_argument('--before', required=True)
    parser.add_argument('--after', required=True)
    parser.add_argument('--offline-copies', action='store_true', required=True)
    try:
        args = parser.parse_args(argv)
        result = compare(args.before, args.after)
    except (Unverified, KeyboardInterrupt):
        result = {'schema': 'bm-offline-semantic-comparison/1', 'scope_result': 'UNVERIFIED',
                  'complete_preservation': 'UNVERIFIED', 'qualification': 'not_qualified'}
    print(json.dumps(result, sort_keys=True))
    return {'PRESERVED': 0, 'CHANGED_OR_MISSING': 1, 'UNVERIFIED': 2}[result['scope_result']]


if __name__ == '__main__':
    raise SystemExit(main())
