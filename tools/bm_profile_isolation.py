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
        self.rename_between(fd, source, fd, destination)

    def rename_between(self, source_fd, source, destination_fd, destination):
        result = self.lib.renameatx_np(source_fd, os.fsencode(source), destination_fd,
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
                    'recover': 'valid pending intent; exactly one identity-verified source or destination',
                    'reconcile': 'one identifiable torn trailing record; valid prefix and unique verified topology'},
                'state': 'unobserved; guarded operations establish state'}

    def guard(self, fd):
        self.safety()
        with directory(self.parent) as now:
            need(identity(os.fstat(now)) == identity(os.fstat(fd)), 'parent_identity_changed')

    def probe_lock(self, directory_fd, name):
        observed = exists(directory_fd, name)
        if observed is None:
            return
        lock = os.open(name, FILE, dir_fd=directory_fd)  # intentionally no O_CREAT
        try:
            st = os.fstat(lock)
            need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid()
                 and not st.st_mode & 0o022 and identity(st) == identity(observed),
                 'lock_identity_invalid')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            attached = exists(directory_fd, name)
            need(attached is not None and identity(attached) == identity(st), 'lock_identity_changed')
        finally:
            os.close(lock)  # releases only our advisory probe; never alters the file

    def resolution_guard(self, fd):
        from resources.lib.frozen_resolution import FrozenInstallResolutionManifest
        for name in os.listdir(fd):
            need(re.fullmatch('[0-9a-f]{64}\.json', name), 'resolution_artifact_uncertain')
            raw, _ = self.read_record(fd, name, strict_mode=False)
            try:
                manifest = FrozenInstallResolutionManifest.from_dict(bm.parse_json_strict(raw))
                need(manifest.resolution_fingerprint == name[:-5], 'resolution_identity_invalid')
            except Exception:
                raise Refusal('resolution_artifact_uncertain') from None

    def producer_directory(self, fd, name, policy):
        observed = exists(fd, name)
        need(observed is not None and stat.S_ISDIR(observed.st_mode), 'coordinator_directory_invalid')
        child = os.open(name, DIR, dir_fd=fd)
        try:
            need(identity(os.fstat(child)) == identity(observed), 'coordinator_directory_changed')
            policy(child)
            attached = exists(fd, name)
            need(attached is not None and identity(attached) == identity(os.fstat(child)),
                 'coordinator_directory_changed')
        finally:
            os.close(child)

    def producer_guard(self, fd, kind):
        """Finite producer-specific paths; completed payloads remain opaque."""
        for name in os.listdir(fd):
            if kind == 'artifact-root':
                need(name == 'artifacts', 'artifact_coordinator_uncertain')
                self.producer_directory(fd, name, lambda child: self.producer_guard(child, 'artifacts'))
                continue
            if kind == 'private' and name == 'create.lock':
                self.probe_lock(fd, name)
                continue
            if kind == 'private':
                # PrivateOverlayStore._safe_id/path_for; no private JSON parsing.
                allowed = re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}\.json', name)
                code = 'private_overlay_coordinator_uncertain'
            elif kind == 'builds':
                # BuildLibrary._atomic publishes SHA-addressed envelopes here.
                allowed = re.fullmatch(r'[0-9a-f]{64}\.json', name)
                code = 'saved_build_coordinator_uncertain'
            else:
                # ArtifactStore publishes only SHA-addressed ZIP and metadata.
                allowed = re.fullmatch(r'[0-9a-f]{64}\.(zip|json)', name)
                code = 'artifact_coordinator_uncertain'
            # These allowlists refuse .create-*, .private-overlay.*.tmp,
            # .stage-*, .<sha>.*.tmp/.json.tmp and unclassified writer artifacts.
            need(allowed is not None, code)
            need(stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode),
                 'coordinator_entry_invalid')

    def coordinator_guard(self, fd, *, library=False):
        locks = {'library.lock'} if library else {
            'restart_transaction.lock', 'frozen_install_transaction.lock', 'create_capture_transaction.lock'}
        for name in os.listdir(fd):
            if name in locks:
                self.probe_lock(fd, name)
            elif ('transaction' in name or 'hold' in name or name.endswith('.lock') or
                  name == 'applied-publication.json' or name.startswith(('.stage-', '.frozen-install.'))):
                raise Refusal('transaction_or_hold_requires_reconciliation')
            elif library and name == 'builds':
                self.producer_directory(fd, name, lambda child: self.producer_guard(child, 'builds'))
            elif not library and name in ('private_overlays', 'frozen-artifacts'):
                kind = 'private' if name == 'private_overlays' else 'artifact-root'
                self.producer_directory(fd, name, lambda child: self.producer_guard(child, kind))
            elif not library and name in ('build-library', 'install_resolutions'):
                nested = os.open(name, DIR, dir_fd=fd)
                try:
                    if name == 'build-library':
                        self.coordinator_guard(nested, library=True)
                    else:
                        self.resolution_guard(nested)
                finally:
                    os.close(nested)

    def clear_transactions(self, fd, name):
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
            if st is not None:
                self.coordinator_guard(root)
        finally:
            os.close(root)
        stage_fd = os.open(name, DIR, dir_fd=fd)
        try:
            need(exists(stage_fd, bm.STAGE_AREA_NAME) is None, 'stage_requires_reconciliation')
        finally:
            os.close(stage_fd)

    def read_record(self, fd, name, *, strict_mode=True):
        observed = exists(fd, name)
        rf = os.open(name, FILE, dir_fd=fd)
        try:
            st = os.fstat(rf)
            need(observed is not None and identity(observed) == identity(st) and
                 stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid()
                 and (stat.S_IMODE(st.st_mode) == 0o600 if strict_mode else not st.st_mode & 0o022),
                 'record_invalid')
            with os.fdopen(os.dup(rf), 'rb') as stream:
                raw = stream.read(64 * 1024 * 1024 + 1)
            need(len(raw) <= 64 * 1024 * 1024, 'record_invalid')
            after = os.fstat(rf)
            need((st.st_size, st.st_mtime_ns, st.st_ctime_ns) ==
                 (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'record_changed')
            self.native.sync(rf, regular=True)
            return raw, identity(st)
        finally:
            os.close(rf)

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

    def prefix(self, journal, op, fd, names):
        need(names and names == ['%03d.json' % i for i in range(len(names))], 'record_invalid')
        prior = None
        allowed = {None: {'prepared'}, 'prepared': {'preserved', 'cancelled'},
                   'preserved': {'parking'}, 'parking': {'parked', 'preserved'},
                   'parked': {'restoring'}, 'restoring': {'restored', 'parked'}}
        for i, name in enumerate(names):
            raw, _ = self.read_record(journal, name)
            rec = bm.parse_json_strict(raw)
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

    def inventory(self, journal):
        records, repairs = [], []
        for name in sorted(os.listdir(journal)):
            if re.fullmatch(r'\d{3,}\.json', name):
                records.append(name)
            elif re.fullmatch(r'reconcile-\d{3,}', name):
                repairs.append(name)
            else:
                raise Refusal('journal_unexpected_artifact')
        need(records == ['%03d.json' % i for i in range(len(records))], 'record_invalid')
        return records, repairs

    def plan_read(self, repair):
        raw, _ = self.read_record(repair, 'plan.json')
        plan = bm.parse_json_strict(raw)
        need(isinstance(plan, dict) and set(plan) == {'version', 'operation', 'journal', 'parent',
             'repair', 'index', 'prefix', 'source_id', 'source_sha', 'source_size', 'replacements'},
             'reconciliation_plan_invalid')
        need(plan['version'] == 1 and type(plan['index']) is int and plan['index'] > 0 and
             isinstance(plan['replacements'], list) and 1 <= len(plan['replacements']) <= 2,
             'reconciliation_plan_invalid')
        need(raw == encoded(plan), 'reconciliation_plan_invalid')
        return plan

    def repair_artifacts(self, repair, plan, *, complete):
        expected = {'plan.json': encoded(plan)}
        expected.update({'%03d.json' % (plan['index'] + i): encoded(rec)
                         for i, rec in enumerate(plan['replacements'])})
        for name in os.listdir(repair):
            if name in ('plan.json', 'quarantine.bin'):
                self.read_record(repair, name)
                continue
            if name.endswith('.pending') and name[:-8] in expected and not complete:
                raw, _ = self.read_record(repair, name)
                need(expected[name[:-8]].startswith(raw), 'reconciliation_stage_invalid')
                continue
            match = re.fullmatch(r'fragment-(plan\.json|\d{3,}\.json)-([0-9a-f]{64})-(\d+)', name)
            need(match and match[1] in expected, 'reconciliation_unexpected_artifact')
            raw, ident = self.read_record(repair, name)
            need(digest(raw) == match[2] and ident[1] == int(match[3]) and
                 expected[match[1]].startswith(raw) and len(raw) < len(expected[match[1]]),
                 'reconciliation_fragment_invalid')

    def audit_plan(self, journal, repair, plan, op, fd, names, *, complete):
        index = plan['index']
        need(stat.S_IMODE(os.fstat(repair).st_mode) == 0o700 and
             os.fstat(repair).st_uid == os.getuid(), 'reconciliation_identity_invalid')
        need(plan['operation'] == op and plan['journal'] == identity(os.fstat(journal)) and
             plan['parent'] == identity(os.fstat(fd)) and plan['repair'] == identity(os.fstat(repair)),
             'reconciliation_identity_invalid')
        prior, _ = self.prefix(journal, op, fd, names[:index])
        need(plan['prefix'] == digest(encoded(prior)), 'reconciliation_prefix_invalid')
        self.repair_artifacts(repair, plan, complete=complete)
        if complete:
            raw, ident = self.read_record(repair, 'quarantine.bin')
            need(ident == plan['source_id'] and digest(raw) == plan['source_sha'] and
                 len(raw) == plan['source_size'], 'quarantine_identity_invalid')
            first = encoded(plan['replacements'][0])
            need(raw and len(raw) < len(first) and first.startswith(raw),
                 'trailing_record_not_identifiable')
            try:
                json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                raise Refusal('trailing_record_not_torn')
            for i, rec in enumerate(plan['replacements']):
                raw, _ = self.read_record(journal, '%03d.json' % (index + i))
                need(raw == encoded(rec), 'reconciliation_publication_invalid')
            self.native.sync(repair)
            self.native.sync(journal)
        return prior

    def load(self, journal, op, fd):
        names, repairs = self.inventory(journal)
        rec, index = self.prefix(journal, op, fd, names)
        for name in repairs:
            repair = os.open(name, DIR, dir_fd=journal)
            try:
                plan = self.plan_read(repair)
                need(name == 'reconcile-%03d' % plan['index'], 'reconciliation_plan_invalid')
                self.audit_plan(journal, repair, plan, op, fd, names, complete=True)
            finally:
                os.close(repair)
        return rec, index

    def derive_replacement(self, fd, prior, raw):
        paths = prior['paths']
        if prior['phase'] in ('prepared', 'parking', 'restoring'):
            phase = self.recover(fd, prior)
            replacements = [dict(prior, phase=phase, previous=digest(encoded(prior)))]
        elif prior['phase'] in ('preserved', 'parked'):
            verify(fd, paths['original'], prior['original'], self.native)
            need(exists(fd, paths['parked'] if prior['phase'] == 'preserved' else paths['active'])
                 is None, 'recovery_ambiguous')
            if prior['phase'] == 'preserved':
                fresh = snapshot(fd, paths['active'], self.native, durable=True)
                if prior['fresh'] is not None:
                    need(fresh == prior['fresh'], 'fresh_identity_invalid')
                need(fresh[digest(b'')]['id'] != prior['original'][digest(b'')]['id'],
                     'fresh_identity_invalid')
                intent = dict(prior, phase='parking', fresh=fresh, previous=digest(encoded(prior)))
            else:
                verify(fd, paths['parked'], prior['fresh'], self.native)
                intent = dict(prior, phase='restoring', previous=digest(encoded(prior)))
            # An incomplete intent cannot precede a completed profile rename:
            # run() requires a complete durable intent before attempting it.
            replacements = [intent, dict(intent, phase=prior['phase'], previous=digest(encoded(intent)))]
        else:
            raise Refusal('phase_refused')
        need(raw and len(raw) < len(encoded(replacements[0])) and
             encoded(replacements[0]).startswith(raw), 'trailing_record_not_identifiable')
        try:
            json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        else:
            raise Refusal('trailing_record_not_torn')
        for key in ('active', 'original', 'parked'):
            if exists(fd, paths[key]) is not None:
                self.clear_transactions(fd, paths[key])
        return replacements

    def publish_reconciliation(self, repair, name, destination, data, check):
        """Atomic no-overwrite publication; incomplete stage bytes are retained."""
        need(len(data) <= 64 * 1024 * 1024, 'record_too_large')
        check()
        if exists(destination, name) is not None:
            raw, _ = self.read_record(destination, name)
            need(raw == data, 'reconciliation_destination_collision')
            return
        stage = name + '.pending'
        if exists(repair, stage) is not None:
            raw, ident = self.read_record(repair, stage)
            need(data.startswith(raw), 'reconciliation_stage_invalid')
            if raw != data:
                fragment = 'fragment-' + name + '-' + digest(raw) + '-' + str(ident[1])
                self.fault('before_fragment_' + name)
                check()
                self.native.rename(repair, stage, fragment)
                self.native.sync(repair)
                self.fault('after_fragment_' + name)
        if exists(repair, stage) is None:
            self.fault('before_write_reconciliation_' + name)
            check()
            handle = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=repair)
            try:
                view = memoryview(data)
                while view:
                    n = os.write(handle, view)
                    need(n > 0, 'record_write_failed')
                    view = view[n:]
                self.fault('after_write_reconciliation_' + name)
                self.native.sync(handle, regular=True)
                self.fault('after_file_sync_reconciliation_' + name)
            finally:
                os.close(handle)
        # Re-open and flush a surviving complete stage before publication.
        raw, _ = self.read_record(repair, stage)
        need(raw == data, 'reconciliation_stage_invalid')
        self.fault('before_publish_reconciliation_' + name)
        check()
        self.native.rename_between(repair, stage, destination, name)
        self.fault('after_publish_reconciliation_' + name)
        self.native.sync(repair)
        self.native.sync(destination)
        self.fault('after_sync_reconciliation_' + name)

    def reconcile(self, journal, op, fd):
        names, repairs = self.inventory(journal)
        pending = []
        for name in repairs:
            repair = os.open(name, DIR, dir_fd=journal)
            try:
                if exists(repair, 'plan.json') is None:
                    pending.append(name)
                else:
                    plan = self.plan_read(repair)
                    need(name == 'reconcile-%03d' % plan['index'], 'reconciliation_plan_invalid')
                    self.audit_plan(journal, repair, plan, op, fd, names, complete=False)
                    if (exists(repair, 'quarantine.bin') is None or
                        any(exists(journal, '%03d.json' % (plan['index'] + i)) is None
                            for i in range(len(plan['replacements'])))):
                        pending.append(name)
                    else:
                        self.audit_plan(journal, repair, plan, op, fd, names, complete=True)
            finally:
                os.close(repair)
        need(len(pending) <= 1, 'multiple_damaged_records')
        if pending:
            repair_name = pending[0]
            index = int(repair_name.split('-')[1])
        else:
            need(len(names) >= 2, 'no_trusted_prefix')
            index = len(names) - 1
            # Validate the WHOLE prefix before treating the last record as torn.
            self.prefix(journal, op, fd, names[:index])
            raw, _ = self.read_record(journal, names[index])
            try:
                json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                raise Refusal('trailing_record_not_torn')
            repair_name = 'reconcile-%03d' % index
        prior, _ = self.prefix(journal, op, fd, names[:index])
        source = '%03d.json' % index
        need(len(names) <= index + 2, 'multiple_damaged_records')
        if exists(journal, repair_name) is None:
            # Classify and verify all trees BEFORE creating reconciliation state.
            raw, _ = self.read_record(journal, source)
            self.derive_replacement(fd, prior, raw)
            self.fault('before_reconciliation_create')
            self.guard(fd)
            os.mkdir(repair_name, 0o700, dir_fd=journal)
            self.fault('after_reconciliation_create')
            self.native.sync(journal)
            self.fault('after_reconciliation_create_sync')
        repair = os.open(repair_name, DIR, dir_fd=journal)
        try:
            need(stat.S_IMODE(os.fstat(repair).st_mode) == 0o700 and
                 os.fstat(repair).st_uid == os.getuid(), 'reconciliation_identity_invalid')
            def check():
                self.guard(fd)
                attached = exists(fd, self.paths(op)['record'])
                child = exists(journal, repair_name)
                need(attached is not None and identity(attached) == identity(os.fstat(journal)) and
                     child is not None and identity(child) == identity(os.fstat(repair)),
                     'reconciliation_identity_invalid')
            check()
            planned = exists(repair, 'plan.json') is not None
            if planned:
                plan = self.plan_read(repair)
                self.audit_plan(journal, repair, plan, op, fd, names, complete=False)
                raw, ident = self.read_record(repair if exists(repair, 'quarantine.bin') else journal,
                                             'quarantine.bin' if exists(repair, 'quarantine.bin') else source)
                need(ident == plan['source_id'] and digest(raw) == plan['source_sha'] and
                     len(raw) == plan['source_size'], 'quarantine_identity_invalid')
            else:
                need(set(os.listdir(repair)) <= {'plan.json.pending'} or
                     all(n == 'plan.json.pending' or n.startswith('fragment-plan.json-')
                         for n in os.listdir(repair)), 'reconciliation_unexpected_artifact')
                raw, ident = self.read_record(journal, source)
                plan = {'version': 1, 'operation': op, 'journal': identity(os.fstat(journal)),
                        'parent': identity(os.fstat(fd)), 'repair': identity(os.fstat(repair)),
                        'index': index, 'prefix': digest(encoded(prior)), 'source_id': ident,
                        'source_sha': digest(raw), 'source_size': len(raw),
                        'replacements': self.derive_replacement(fd, prior, raw)}
                self.repair_artifacts(repair, plan, complete=False)
                self.publish_reconciliation(repair, 'plan.json', repair, encoded(plan), check)
            need(plan['replacements'] == self.derive_replacement(fd, prior, raw),
                 'reconciliation_topology_changed')
            check()
            if exists(repair, 'quarantine.bin') is None:
                self.fault('before_quarantine')
                check()
                current, current_id = self.read_record(journal, source)
                need(current == raw and current_id == ident, 'trailing_identity_changed')
                self.native.rename_between(journal, source, repair, 'quarantine.bin')
                self.fault('after_quarantine')
            self.native.sync(journal)
            self.native.sync(repair)
            self.fault('after_quarantine_sync')
            for i, rec in enumerate(plan['replacements']):
                self.publish_reconciliation(repair, '%03d.json' % (index + i), journal,
                                            encoded(rec), check)
            # The ordinary reader must accept the complete chain and evidence.
            rec, _ = self.load(journal, op, fd)
            need(plan['replacements'] == self.derive_replacement(fd, prior, raw),
                 'reconciliation_topology_changed')
            self.guard(fd)
            return {'operation': op, 'phase': rec['phase'], 'original_verified': True,
                    'automatic_deletion': False, 'reconciled_trailing_index': index}
        finally:
            os.close(repair)

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
        need(action in ('preserve', 'park', 'restore', 'recover', 'reconcile'), 'action_invalid')
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
                if action == 'reconcile':
                    return self.reconcile(journal, op, fd)
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
    parser.add_argument('action', choices=('preview', 'preserve', 'park', 'restore', 'recover', 'reconcile'))
    parser.add_argument('--operation', required=True, help='32 lowercase hex characters; choose once')
    parser.add_argument('--confirm', choices=('preserve', 'park', 'restore', 'recover', 'reconcile'))
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
