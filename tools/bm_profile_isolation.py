"""Explicit, no-delete portable Test.app isolation. See docs/PROFILE_ISOLATION.md.

The CLI has no target override. Scratch wiring is only exposed to offline tests.
All errors are secret-blind codes; never print exception text from filesystem APIs.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

try:
    from tools import bm_test_app as bm
except ModuleNotFoundError:
    import bm_test_app as bm


class Refusal(Exception):
    pass


def need(ok, code):
    if not ok:
        raise Refusal(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(st):
    return [st.st_dev, st.st_ino]


DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


@contextlib.contextmanager
def directory(path):
    """Open each ancestor relative to an already opened non-symlink directory."""
    need(path.is_absolute() and '..' not in path.parts, 'path_invalid')
    fd = os.open('/', DIR)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, DIR, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def exists(fd, name):
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


class Native:
    """macOS fd metadata, exclusive rename, and strict durability primitives."""
    def __init__(self):
        need(sys.platform == 'darwin', 'macos_required')
        self.lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        self.lib.flistxattr.restype = ctypes.c_ssize_t
        self.lib.fgetxattr.restype = ctypes.c_ssize_t
        self.lib.acl_get_fd_np.restype = ctypes.c_void_p
        self.lib.acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
        self.lib.acl_to_text.restype = ctypes.c_void_p
        self.lib.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)]
        self.lib.acl_free.argtypes = [ctypes.c_void_p]
        self.lib.filesec_init.restype = ctypes.c_void_p
        self.lib.filesec_free.argtypes = [ctypes.c_void_p]
        self.lib.filesec_query_property.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                    ctypes.POINTER(ctypes.c_int)]
        self.lib.fstatx_np.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]

    def attrs(self, fd):
        n = self.lib.flistxattr(fd, None, 0, 0)
        need(n >= 0, 'xattrs_unavailable')
        buf = ctypes.create_string_buffer(n or 1)
        need(self.lib.flistxattr(fd, buf, n, 0) == n, 'xattrs_changed')
        rows = []
        for name in sorted(buf.raw[:n].split(b'\0')):
            if not name:
                continue
            size = self.lib.fgetxattr(fd, name, None, 0, 0, 0)
            need(size >= 0, 'xattrs_unavailable')
            value = ctypes.create_string_buffer(size or 1)
            need(self.lib.fgetxattr(fd, name, value, size, 0, 0) == size, 'xattrs_changed')
            rows.append([digest(name), digest(value.raw[:size])])
        # acl_get_fd_np returns NULL even for a successfully observed absent
        # ACL. Establish absence explicitly using the filesec property query.
        sec = self.lib.filesec_init()
        need(bool(sec), 'acl_unavailable')
        try:
            st_buffer = ctypes.create_string_buffer(4096)
            need(self.lib.fstatx_np(fd, st_buffer, sec) == 0, 'acl_unavailable')
            present = ctypes.c_int()
            need(self.lib.filesec_query_property(sec, 5, ctypes.byref(present)) == 0,
                 'acl_unavailable')
        finally:
            self.lib.filesec_free(sec)
        if not present.value:
            return [rows, 'absent']
        acl = self.lib.acl_get_fd_np(fd, 0x100)  # ACL_TYPE_EXTENDED
        need(bool(acl), 'acl_unavailable')
        try:
            length = ctypes.c_ssize_t()
            text = self.lib.acl_to_text(acl, ctypes.byref(length))
            need(bool(text), 'acl_unavailable')
            try:
                acl_hash = digest(ctypes.string_at(text, length.value))
            finally:
                self.lib.acl_free(text)
        finally:
            self.lib.acl_free(acl)
        return [rows, acl_hash]

    def sync(self, fd, *, regular=False):
        os.fsync(fd)
        fcntl.fcntl(fd, 51)  # F_FULLFSYNC for files AND directories; fail closed

    def rename(self, fd, source, destination):
        # RENAME_EXCL makes the absence check atomic, including case collisions.
        result = self.lib.renameatx_np(fd, os.fsencode(source), fd,
                                      os.fsencode(destination), 0x4)
        if result:
            raise Refusal('exclusive_rename_failed')


def snapshot(parent, name, native, *, durable=False):
    """Hash bytes, topology and metadata via fd-only traversal; reject links/specials.

    Path and xattr names are represented only by opaque digests. Reading may
    update atime; rename changes root ctime. Neither is a preservation invariant.
    """
    rows = {}
    def walk(fd, rel):
        before = os.fstat(fd)
        need(before.st_dev == os.fstat(parent).st_dev, 'cross_volume')
        is_dir = stat.S_ISDIR(before.st_mode)
        need(is_dir or stat.S_ISREG(before.st_mode), 'unsupported_node')
        row = {'id': identity(before), 'mode': before.st_mode,
               'uid': before.st_uid, 'gid': before.st_gid,
               'flags': before.st_flags, 'mtime': before.st_mtime_ns,
               'birthtime': before.st_birthtime,
               'attrs': native.attrs(fd)}
        if is_dir:
            names = sorted(os.listdir(fd))
            for child in names:
                st = os.stat(child, dir_fd=fd, follow_symlinks=False)
                need(stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode), 'unsupported_node')
                child_fd = os.open(child, DIR if stat.S_ISDIR(st.st_mode) else FILE, dir_fd=fd)
                try:
                    need(identity(os.fstat(child_fd)) == identity(st), 'tree_changed')
                    walk(child_fd, rel + b'/' + os.fsencode(child))
                finally:
                    os.close(child_fd)
            need(sorted(os.listdir(fd)) == names, 'tree_changed')
        else:
            h = hashlib.sha256()
            while True:
                data = os.read(fd, 1024 * 1024)
                if not data:
                    break
                h.update(data)
            row.update(size=before.st_size, bytes=h.hexdigest(), links=before.st_nlink)
            need(before.st_nlink == 1, 'external_hardlink_uncertain')
        after = os.fstat(fd)
        need((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
             (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'tree_changed')
        need(native.attrs(fd) == row['attrs'], 'metadata_changed')
        if durable:
            native.sync(fd, regular=not is_dir)
        rows[digest(rel)] = row
    fd = os.open(name, DIR, dir_fd=parent)
    try:
        walk(fd, b'')
    finally:
        os.close(fd)
    return rows


def verify(parent, name, expected, native):
    actual = snapshot(parent, name, native)
    differences = []
    for key in sorted(set(actual) | set(expected)):
        if key not in actual or key not in expected:
            differences.append([key, 'structure'])
        else:
            differences.extend([key, field] for field in sorted(set(actual[key]) | set(expected[key]))
                               if actual[key].get(field) != expected[key].get(field))
    if differences:
        # Opaque path keys and fixed field labels only, never private names/values.
        raise Refusal('integrity_difference:' + encoded(differences).decode())


def validate_evidence(value):
    need(isinstance(value, dict) and value and digest(b'') in value, 'record_invalid')
    base = {'id', 'mode', 'uid', 'gid', 'flags', 'mtime', 'birthtime', 'attrs'}
    def hexhash(v):
        return isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v)
    for key, row in value.items():
        need(hexhash(key) and isinstance(row, dict), 'record_invalid')
        need(set(row) in (base, base | {'size', 'bytes', 'links'}), 'record_invalid')
        need(isinstance(row['id'], list) and len(row['id']) == 2 and
             all(type(i) is int and i >= 0 for i in row['id']), 'record_invalid')
        need(all(type(row[k]) is int and row[k] >= 0 for k in
                 ('mode', 'uid', 'gid', 'flags', 'mtime')), 'record_invalid')
        need(type(row['birthtime']) in (float, int), 'record_invalid')
        attrs = row['attrs']
        need(isinstance(attrs, list) and len(attrs) == 2 and isinstance(attrs[0], list) and
             (attrs[1] == 'absent' or hexhash(attrs[1])), 'record_invalid')
        need(all(isinstance(a, list) and len(a) == 2 and all(hexhash(x) for x in a)
                 for a in attrs[0]), 'record_invalid')
        if 'bytes' in row:
            need(stat.S_ISREG(row['mode']) and hexhash(row['bytes']) and
                 type(row['size']) is int and row['size'] >= 0 and row['links'] == 1,
                 'record_invalid')
        else:
            need(stat.S_ISDIR(row['mode']), 'record_invalid')
    need(stat.S_ISDIR(value[digest(b'')]['mode']), 'record_invalid')


class Isolation:
    def __init__(self, services, *, scratch=False, native=None, fault=lambda point: None):
        self.services = services
        self.target = services.target
        if scratch:
            raw = str(self.target.root)
            need(raw.startswith('/private/tmp/') and not self.target.production,
                 'scratch_boundary_invalid')
        else:
            need(self.target.production and str(self.target.root) == bm.AUTHORIZED_TEST_APP,
                 'target_not_authorized')
        self.parent = self.target.portable_data.parent
        self.native = native or Native()
        self.fault = fault

    def safety(self):
        bm.identify(self.services, require='not_running')

    def paths(self, op):
        need(isinstance(op, str) and re.fullmatch('[0-9a-f]{32}', op), 'operation_invalid')
        return {'active': 'portable_data', 'original': 'portable_data.bm-original-' + op,
                'parked': 'portable_data.bm-qualified-' + op,
                'record': '.bm-profile-isolation-' + op}

    def preview(self, op):
        # Purely lexical: no private profile read/hash or even metadata probe.
        return {'target': str(self.target.root), 'mode': '-p', 'operation': op,
                'paths': {k: str(self.parent / v) for k, v in self.paths(op).items()},
                'phases': {
                    'preserve': 'active original present; original and parked destinations absent',
                    'park': 'verified original preserved; distinct fresh active present; parked absent',
                    'restore': 'verified original and parked fresh present; active absent',
                    'recover': 'valid pending intent; exactly one identity-verified source or destination'},
                'state': 'unobserved; guarded operations establish state'}

    def guard(self, fd):
        self.safety()
        with directory(self.parent) as now:
            need(identity(os.fstat(now)) == identity(os.fstat(fd)), 'parent_identity_changed')

    def clear_transactions(self, fd, name):
        # Conservative: any persisted coordinator/hold evidence requires separate
        # reconciliation, even a terminal record. No decoding of private values.
        rel = ('userdata', 'addon_data', bm.BUILD_MANAGER_ID)
        root = os.open(name, DIR, dir_fd=fd)
        try:
            for part in rel:
                st = exists(root, part)
                if st is None:
                    break
                nxt = os.open(part, DIR, dir_fd=root)
                os.close(root)
                root = nxt
            names = os.listdir(root) if st is not None else []
            need(not any('transaction' in n or 'hold' in n or n.endswith('.lock') for n in names),
                 'transaction_or_hold_requires_reconciliation')
        finally:
            os.close(root)
        stage_fd = os.open(name, DIR, dir_fd=fd)
        try:
            need(exists(stage_fd, bm.STAGE_AREA_NAME) is None, 'stage_requires_reconciliation')
        finally:
            os.close(stage_fd)

    def save(self, journal, record, index):
        self.fault('before_record_' + record['phase'])
        with directory(self.parent) as parent:
            attached = exists(parent, record['paths']['record'])
            need(attached is not None and identity(attached) == identity(os.fstat(journal)),
                 'journal_identity_changed')
        self.safety()
        raw = encoded(record)
        need(len(raw) <= 64 * 1024 * 1024, 'record_too_large')
        fd = os.open('%03d.json' % index, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=journal)
        try:
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                need(written > 0, 'record_write_failed')
                view = view[written:]
            self.fault('after_write_' + record['phase'])
            self.native.sync(fd, regular=True)
            self.fault('after_file_sync_' + record['phase'])
        finally:
            os.close(fd)
        self.native.sync(journal)
        self.fault('after_record_' + record['phase'])

    def load(self, journal, op, fd):
        names = sorted(os.listdir(journal))
        need(names and names == ['%03d.json' % i for i in range(len(names))], 'record_invalid')
        prior = None
        allowed = {None: {'prepared'}, 'prepared': {'preserved', 'cancelled'},
                   'preserved': {'parking'}, 'parking': {'parked', 'preserved'},
                   'parked': {'restoring'}, 'restoring': {'restored', 'parked'}}
        for i, name in enumerate(names):
            rf = os.open(name, FILE, dir_fd=journal)
            try:
                st = os.fstat(rf)
                need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and
                     stat.S_IMODE(st.st_mode) == 0o600 and st.st_uid == os.getuid(), 'record_invalid')
                with os.fdopen(os.dup(rf), 'rb') as stream:
                    raw = stream.read(64 * 1024 * 1024 + 1)
                need(len(raw) <= 64 * 1024 * 1024, 'record_invalid')
                rec = bm.parse_json_strict(raw)
                self.native.sync(rf, regular=True)
            finally:
                os.close(rf)
            need(isinstance(rec, dict) and set(rec) == {'version', 'operation', 'target', 'paths',
                 'parent', 'bundle', 'phase', 'previous', 'original', 'fresh'}, 'record_invalid')
            need(rec['version'] == 1 and rec['operation'] == op and rec['target'] == str(self.target.root)
                 and rec['paths'] == self.paths(op) and rec['parent'] == identity(os.fstat(fd)), 'record_binding_invalid')
            need(rec['phase'] in allowed.get(prior['phase'] if prior else None, set()) and
                 rec['previous'] == (digest(encoded(prior)) if prior else None), 'record_phase_invalid')
            validate_evidence(rec['original'])
            if rec['fresh'] is not None:
                validate_evidence(rec['fresh'])
            need(rec['fresh'] is not None or rec['phase'] in ('prepared', 'preserved', 'cancelled'),
                 'record_invalid')
            if prior:
                need(all(rec[k] == prior[k] for k in ('original', 'bundle', 'parent')), 'record_binding_invalid')
                if prior['fresh'] is not None:
                    need(rec['fresh'] == prior['fresh'], 'record_binding_invalid')
            prior = rec
        self.native.sync(journal)
        need(rec['bundle'] == bm.inspect_bundle(self.target).info_plist_sha256, 'bundle_identity_changed')
        return rec, len(names)

    def rename(self, fd, source, dest, evidence, phase):
        self.guard(fd)
        need(exists(fd, dest) is None, 'destination_collision')
        need(exists(fd, source) is not None, 'source_missing')
        need(exists(fd, source).st_dev == os.fstat(fd).st_dev, 'cross_volume')
        verify(fd, source, evidence, self.native)
        self.clear_transactions(fd, source)
        self.guard(fd)
        self.fault('before_rename_' + phase)
        self.guard(fd)
        source_stat = exists(fd, source)
        need(source_stat is not None and identity(source_stat) == evidence[digest(b'')]['id'],
             'source_identity_changed')
        self.native.rename(fd, source, dest)
        self.fault('after_rename_' + phase)
        self.native.sync(fd)
        self.fault('after_sync_' + phase)
        need(exists(fd, source) is None, 'source_reappeared')
        verify(fd, dest, evidence, self.native)
        self.guard(fd)

    def run(self, action, op, *, confirm, portable):
        need(action in ('preserve', 'park', 'restore', 'recover'), 'action_invalid')
        need(confirm == action and portable is True, 'explicit_gate_required')
        paths = self.paths(op)
        self.safety()
        with directory(self.parent) as fd:
            # Nonblocking advisory lock of the parent serializes our invocations.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.guard(fd)
            self.native.sync(fd)  # establish directory fsync support BEFORE mutation
            if action == 'preserve':
                need(not any(n.startswith(('.bm-profile-isolation-', 'portable_data.bm-original-',
                                           'portable_data.bm-qualified-')) for n in os.listdir(fd)),
                     'existing_operation_requires_reconciliation')
                for k in ('original', 'parked', 'record'):
                    need(exists(fd, paths[k]) is None, 'destination_collision')
                st = exists(fd, paths['active'])
                need(st is not None and stat.S_ISDIR(st.st_mode), 'original_missing')
                need(st.st_dev == os.fstat(fd).st_dev, 'cross_volume')
                self.clear_transactions(fd, paths['active'])
                original = snapshot(fd, paths['active'], self.native, durable=True)
                rec = {'version': 1, 'operation': op, 'target': str(self.target.root), 'paths': paths,
                       'parent': identity(os.fstat(fd)), 'bundle': bm.inspect_bundle(self.target).info_plist_sha256,
                       'phase': 'prepared', 'previous': None, 'original': original, 'fresh': None}
                self.guard(fd)
                self.fault('before_journal_create')
                os.mkdir(paths['record'], 0o700, dir_fd=fd)
                self.fault('after_journal_create')
                self.native.sync(fd)
                self.fault('after_journal_sync')
            need([n for n in os.listdir(fd) if n.startswith('.bm-profile-isolation-')] ==
                 [paths['record']], 'other_operation_requires_reconciliation')
            journal = os.open(paths['record'], DIR, dir_fd=fd)
            try:
                need(stat.S_IMODE(os.fstat(journal).st_mode) == 0o700 and
                     os.fstat(journal).st_uid == os.getuid(), 'record_invalid')
                if action == 'preserve':
                    self.save(journal, rec, 0)
                    index = 1
                    self.rename(fd, paths['active'], paths['original'], rec['original'], 'preserve')
                    phase = 'preserved'
                else:
                    rec, index = self.load(journal, op, fd)
                    if action != 'recover':
                        verify(fd, paths['original'] if rec['phase'] != 'restored' else paths['active'],
                               rec['original'], self.native)
                    if action == 'park':
                        need(rec['phase'] == 'preserved', 'phase_refused')
                        need(exists(fd, paths['parked']) is None, 'destination_collision')
                        self.clear_transactions(fd, paths['active'])
                        fresh = snapshot(fd, paths['active'], self.native, durable=True)
                        need(fresh[digest(b'')]['id'] != rec['original'][digest(b'')]['id'], 'fresh_identity_invalid')
                        intent = dict(rec, phase='parking', fresh=fresh, previous=digest(encoded(rec)))
                        self.save(journal, intent, index)
                        rec, index = intent, index + 1
                        self.rename(fd, paths['active'], paths['parked'], fresh, 'park')
                        phase = 'parked'
                    elif action == 'restore':
                        need(rec['phase'] == 'parked', 'phase_refused')
                        verify(fd, paths['parked'], rec['fresh'], self.native)
                        need(exists(fd, paths['active']) is None, 'destination_collision')
                        intent = dict(rec, phase='restoring', previous=digest(encoded(rec)))
                        self.save(journal, intent, index)
                        rec, index = intent, index + 1
                        self.rename(fd, paths['original'], paths['active'], rec['original'], 'restore')
                        phase = 'restored'
                    else:
                        phase = self.recover(fd, rec)
                self.guard(fd)
                final = dict(rec, phase=phase, previous=digest(encoded(rec)))
                self.save(journal, final, index)
                return {'operation': op, 'phase': phase, 'original_verified': True,
                        'automatic_deletion': False}
            finally:
                os.close(journal)

    def recover(self, fd, rec):
        """Only reconcile a persisted intent; never rename, guess, or roll back."""
        transitions = {'prepared': ('active', 'original', 'original', 'cancelled', 'preserved'),
                       'parking': ('active', 'parked', 'fresh', 'preserved', 'parked'),
                       'restoring': ('original', 'active', 'original', 'parked', 'restored')}
        need(rec['phase'] in transitions, 'phase_refused')
        src, dest, evidence, before, after = transitions[rec['phase']]
        paths = rec['paths']
        s, d = exists(fd, paths[src]), exists(fd, paths[dest])
        need((s is None) != (d is None), 'recovery_ambiguous')
        verify(fd, paths[src] if s else paths[dest], rec[evidence], self.native)
        if rec['phase'] == 'prepared':
            need(exists(fd, paths['parked']) is None, 'recovery_ambiguous')
        elif rec['phase'] == 'parking':
            verify(fd, paths['original'], rec['original'], self.native)
        elif rec['phase'] == 'restoring':
            verify(fd, paths['parked'], rec['fresh'], self.native)
        self.native.sync(fd)
        return before if s else after


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preview', 'preserve', 'park', 'restore', 'recover'))
    parser.add_argument('--operation', required=True, help='32 lowercase hex characters; choose once')
    parser.add_argument('--confirm', choices=('preserve', 'park', 'restore', 'recover'))
    parser.add_argument('--portable', action='store_true')
    args = parser.parse_args(argv)
    try:
        helper = Isolation(bm.Services.production())
        result = (helper.preview(args.operation) if args.action == 'preview' else
                  helper.run(args.action, args.operation, confirm=args.confirm, portable=args.portable))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refusal, bm.HelperError, OSError, ValueError, KeyError, TypeError):
        # Keep OS exception strings, filenames and arbitrary persisted values private.
        exc = sys.exc_info()[1]
        code = str(exc) if isinstance(exc, Refusal) else 'guard_or_io_failure'
        print(json.dumps({'ok': False, 'code': code, 'instruction': 'STOP; retain every tree and record'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
