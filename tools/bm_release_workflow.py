"""Fixed-input offline rehearsal, never publication. Success JSON is emitted last.

Private workspaces and kernel confinement restrict the authenticated builder;
verification is point-in-time, not immunity to a hostile same-UID writer.
Ambiguous failed workspaces are preserved rather than recursively deleted.
"""
import contextlib
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from xml.etree import ElementTree as ET

try:
    from tools import bm_release_source as source
except ModuleNotFoundError:
    import bm_release_source as source

PYTHON = '/Users/eengert/.pyenv/versions/3.10.9/bin/python3'
REPOSITORY = Path('/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex')
MANIFEST = REPOSITORY / '.qualification-evidence/item8-d028-native-stage-r3-20261022/stage-20261022T180238Z-a185e4d34622/stage_manifest.json'
BUILDER_REPOSITORY = Path('/Users/eengert/Documents/Kodi/repository.eengert')
BUILDER_COMMIT = '9a7bd9000a69f3b617fba2fb0d4a8147c1b9d0f0'
BUILDER_BLOB = 'd91ce24d8ae4f88387e017446f194f3d1e2acab7'
BUILDER_SHA256 = 'd75f55d9246e1cb120e7bfc03c04d36bab23d43c2ae6f8a2b78b07d7012606cb'
FIXTURE_SHA256 = '15c1410fb2943078da2539e6a2dd21a1894a0bda073a26076724543e290156b0'
PRODUCT_COMMIT = 'a185e4d346229c1797dfd75e79a7ba3ee016dd53'
PRODUCT_TREE = '278f3e7fa49586e2db4e8d055232bf6990c64418'
SOURCE_MANIFEST = '16cf4fb6fd076249ab9b7c8a11dc7a4e9fa2b776c78ecc294aa1ba0b0b6ef0fb'
RELEASE_MANIFEST = '975cbdcc2d5271e7d8687aea1ca4a78082a26f8db860b9303c541313b4970cda'
ZIP_SHA256 = 'c2b595ef68c2e1c50580b9d1d1e99e5d07d56c5bf6156a5a362ae5c607bbafae'
ZIP_SIZE = 719398
ICON_SHA256 = '207c44a0474e7e370cf6d210c7646ce243c704a0694ef422c12bd51401628d23'
PRODUCT = 'script.build.manager'
REPO = 'repository.eengert'
VERSION = '0.1.0'
need = source.need


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(path):
    with source.directory(path) as fd:
        s = os.fstat(fd)
        need(s.st_uid == os.geteuid() and not s.st_mode & 0o022, 'directory_owner')
        return source.identity(s)


def read(path):
    raw, sig = source.read_file(path)
    need(not sig[2] & 0o022, 'unsafe_mode')
    # File owner is checked at each no-follow tree boundary too.
    with source.directory(path.parent) as fd:
        need(os.stat(path.name, dir_fd=fd, follow_symlinks=False).st_uid == os.geteuid(), 'file_owner')
    return raw, sig


def write(path, raw, mode=0o600):
    with source.directory(path.parent) as fd:
        out = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
        try:
            os.fchmod(out, mode)
            need(os.write(out, raw) == len(raw), 'partial_write')
        finally:
            os.close(out)


def authenticate():
    need(sys.executable == PYTHON and sys.version_info[:3] == (3, 10, 9), 'python_identity')
    need(source.COMMIT == PRODUCT_COMMIT and source.TREE == PRODUCT_TREE
         and source.MANIFEST_SHA256 == SOURCE_MANIFEST, 'source_pin')
    data, manifest = source.admit(REPOSITORY, MANIFEST)
    need(len(data) == 76 and manifest['release_count'] == 75
         and digest(source.encoded(manifest)) == RELEASE_MANIFEST, 'release_pin')
    # Expected bytes are retained from Git admission, never read back from export.
    expected = {e['path']: data[e['path']] for e in manifest['included']}
    need(len(expected) == 75 and source.EXCLUSION not in expected, 'release_inventory')
    entries = manifest['included'] + manifest['excluded']
    need(len(entries) == 76 and {e['path'] for e in entries} == set(data), 'source_inventory')
    for entry in entries:
        body = data[entry['path']]
        blob = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        need(len(body) == entry['size'] and digest(body) == entry['sha256']
             and blob == entry['git_blob'] and entry['git_mode'] == '100644', 'source_bytes')
    builder_repository_identity = identity(BUILDER_REPOSITORY)
    blob = source.git(BUILDER_REPOSITORY, 'rev-parse', BUILDER_COMMIT + ':scripts/build_repository.py').decode().strip()
    need(blob == BUILDER_BLOB, 'builder_blob')
    builder = source.git(BUILDER_REPOSITORY, 'cat-file', 'blob', BUILDER_BLOB)
    need(hashlib.sha1(b'blob ' + str(len(builder)).encode() + b'\0' + builder).hexdigest() == BUILDER_BLOB
         and digest(builder) == BUILDER_SHA256, 'builder_digest')
    live, _ = read(BUILDER_REPOSITORY / 'scripts/build_repository.py')
    need(live == builder, 'live_builder_changed')
    fixture = source.git(BUILDER_REPOSITORY, 'show', BUILDER_COMMIT + ':repository.eengert/addon.xml')
    need(digest(fixture) == FIXTURE_SHA256, 'fixture_digest')
    addon = ET.fromstring(expected['addon.xml']); repo = ET.fromstring(fixture)
    need(addon.get('id') == PRODUCT and addon.get('version') == VERSION
         and repo.get('id') == REPO and repo.get('version') == '1.0.0', 'metadata_identity')
    need([n.text for n in addon.findall('./extension/assets/*')] == ['resources/images/icon.png']
         and not repo.findall('./extension/assets/*'), 'metadata_assets')
    need(digest(expected['resources/images/icon.png']) == ICON_SHA256, 'icon_digest')
    source.binding(BUILDER_REPOSITORY, builder_repository_identity)
    return expected, manifest, builder, fixture


def policy(repository):
    # Only this disposable repository is writable, including its TMPDIR.
    # Never probe these protected paths to test the policy.
    return ('(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n'
            '(allow file-write* (subpath ' + json.dumps(str(repository)) + '))\n'
            '(deny file-read* (literal "/Applications")'
            ' (subpath "/Applications/Kodi.app")'
            ' (subpath "/Applications/Kodi Build Manager Test.app")'
            ' (subpath "/System/Volumes/Data/Applications/Kodi.app")'
            ' (subpath "/System/Volumes/Data/Applications/Kodi Build Manager Test.app")'
            ' (subpath "/Users/eengert/Library/Application Support/Kodi")'
            ' (subpath "/System/Volumes/Data/Users/eengert/Library/Application Support/Kodi"))\n')


def environment(tmp):
    # No inherited PYTHON*, proxy, loader, Git, HOME or credential environment.
    return {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'TMPDIR': str(tmp), 'DEVELOPER_DIR': '/Library/Developer/CommandLineTools'}


# Retain the Popen object on an uncertain cleanup. Its destructor must not reap
# the identity anchor while this interpreter could still handle the refusal.
_UNCONFIRMED_CHILDREN = []


class _Siginfo(ctypes.Structure):
    # Darwin LP64 siginfo_t; unlike waitpid, WNOWAIT retains the child/PID.
    _fields_ = [('signo', ctypes.c_int), ('error', ctypes.c_int),
                ('code', ctypes.c_int), ('pid', ctypes.c_int),
                ('uid', ctypes.c_uint), ('status', ctypes.c_int),
                ('addr', ctypes.c_void_p), ('value', ctypes.c_void_p),
                ('band', ctypes.c_long), ('pad', ctypes.c_ulong * 7)]


class _Sigaction(ctypes.Structure):
    _fields_ = [('handler', ctypes.c_void_p), ('mask', ctypes.c_uint),
                ('flags', ctypes.c_int)]


class _ChildGroup:
    """Original setsid group only, anchored by our exclusively waited child.

    No poll/communicate/wait is allowed until confirmation. XNU removes group
    membership and releases the PID at reap, not at WNOWAIT observation.
    proc_listpgrppids supplies only this group's members, including zombies.
    This fixed CLI requires one thread and default SIGCHLD (no other reaper).
    Deliberate setpgid/setsid escape and hostile in-process code are not covered.
    """
    def __init__(self):
        need(sys.platform == 'darwin' and ctypes.sizeof(_Siginfo) == 104
             and ctypes.sizeof(_Sigaction) == 16, 'child_authority_unavailable')
        self.libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        self.libproc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self.libc.waitid.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                     ctypes.POINTER(_Siginfo), ctypes.c_int]
        self.libc.waitid.restype = ctypes.c_int
        self.libc.sigaction.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                        ctypes.POINTER(_Sigaction)]
        self.libc.sigaction.restype = ctypes.c_int
        self.libproc.proc_listpgrppids.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.libproc.proc_listpgrppids.restype = ctypes.c_int
        self.process = None
        self.confirmed = False
        self.require_exclusive_waiter()

    def require_exclusive_waiter(self):
        action = _Sigaction()
        need(threading.current_thread() is threading.main_thread()
             and threading.active_count() == 1, 'child_waiter_not_exclusive')
        need(self.libc.sigaction(signal.SIGCHLD, None, ctypes.byref(action)) == 0
             and not action.handler and not action.flags & 0x0020,
             'child_waiter_not_exclusive')  # Darwin SA_NOCLDWAIT

    def exited(self):
        self.require_exclusive_waiter()
        need(self.process.returncode is None, 'child_anchor_lost')
        info = _Siginfo()  # WNOHANG need not initialize a no-event result.
        result = self.libc.waitid(os.P_PID, self.process.pid, ctypes.byref(info),
                                  os.WEXITED | os.WNOHANG | os.WNOWAIT)
        need(result == 0 and info.pid in (0, self.process.pid), 'child_anchor_lost')
        return info.pid == self.process.pid

    def members(self):
        self.exited()  # ECHILD, another reaper or auto-reap forbids any signal.
        pids = (ctypes.c_int * 4096)()
        ctypes.set_errno(0)
        count = self.libproc.proc_listpgrppids(self.process.pid, pids, ctypes.sizeof(pids))
        need(ctypes.get_errno() == 0 and 0 < count < len(pids), 'child_group_unconfirmed')
        values = list(pids[:count])
        need(len(set(values)) == count and all(pid > 0 for pid in values)
             and self.process.pid in values, 'child_group_unconfirmed')
        return set(values)

    def finish(self, pump):
        def complete():
            members = self.members()
            return self.exited() and members == {self.process.pid}
        if complete():
            self.confirmed = True
            return
        for sig, grace in ((signal.SIGTERM, .5), (signal.SIGKILL, 2.0)):
            # Recheck the unreaped anchor immediately before each group signal.
            self.members()
            self.exited()
            try:
                os.killpg(self.process.pid, sig)
            except ProcessLookupError:
                pass  # A zombie-only group still requires explicit confirmation.
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                if complete():
                    self.confirmed = True
                    return
                pump()
        raise source.Refusal('child_cleanup_failed')


def run(argv, cwd, env, timeout=30):
    group = _ChildGroup()  # Admit authority before creating any process.
    process = None
    output = [bytearray(), bytearray()]
    selector = selectors.DefaultSelector()

    def pump():
        for key, _ in selector.select(.02):
            raw = os.read(key.fileobj.fileno(), 65536)
            if raw:
                output[key.data].extend(raw)
            else:
                selector.unregister(key.fileobj)

    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        group.process = process
        for index, stream in enumerate((process.stdout, process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, index)
        deadline = time.monotonic() + timeout
        while not group.exited():
            if time.monotonic() >= deadline:
                raise source.Refusal('child_timeout')
            pump()
        group.finish(pump)
        process.wait()  # Only now release the PID/PGID; no later group signal.
        deadline = time.monotonic() + .5
        while selector.get_map() and time.monotonic() < deadline:
            pump()
        need(not selector.get_map(), 'child_output_unconfirmed')
        out, err = map(bytes, output)
        need(len(out) <= 65536 and len(err) <= 65536, 'child_output_size')
        return process.returncode, out, err
    except BaseException:
        if process is not None and not group.confirmed:
            try:
                # Cleanup must not depend on healthy pipes or successful capture.
                group.finish(lambda: time.sleep(.02))
                process.wait()
            except BaseException:
                _UNCONFIRMED_CHILDREN.append(group)
                raise source.Refusal('child_cleanup_failed') from None
        raise
    finally:
        selector.close()
        if process is not None:
            process.stdout.close()
            process.stderr.close()


def sandbox_argv(work, script_args):
    return ['/usr/bin/sandbox-exec', '-f', str(work['policy']), PYTHON, '-B', *script_args]


PROBE = r'''
import errno,json,os,socket,subprocess,sys
paths=json.loads(sys.argv[1]);role=sys.argv[2]
result={}
for label in ('outside','source','builder'):
    try:
        with open(paths[label],'ab') as f:f.write(b'INEFFECTIVE')
    except OSError as e:result[label]=e.errno in (errno.EPERM,errno.EACCES)
    else:result[label]=False
p=paths['allowed']+'-'+role
with open(p,'xb') as f:f.write(b'allowed')
os.unlink(p);result['allowed']=True
with socket.socket() as s:
    s.settimeout(2)
    try:s.connect(('127.0.0.1',paths['port']))
    except OSError as e:result['network']=e.errno in (errno.EPERM,errno.EACCES)
    else:result['network']=False
if role=='parent':
    child=subprocess.run([sys.executable,'-B','-c',sys.argv[3],sys.argv[1],'child'],
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
    if child.returncode or child.stderr:raise SystemExit(2)
    result['inherited']=json.loads(child.stdout)
print(json.dumps(result,sort_keys=True))
'''


def confinement(work):
    paths = {'outside': str(work['outside']), 'source': str(work['product'] / 'default.py'),
             'builder': str(work['builder']), 'allowed': str(work['tmp'] / 'allowed')}
    # Prove OS permissions alone do not account for the subsequent refusals.
    for name in ('outside', 'source', 'builder'):
        fd = os.open(paths[name], os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        os.close(fd)
    before = {n: read(Path(paths[n])) for n in ('outside', 'source', 'builder')}
    with socket.socket() as endpoint:
        endpoint.bind(('127.0.0.1', 0)); endpoint.listen(4); endpoint.settimeout(2)
        paths['port'] = endpoint.getsockname()[1]
        with socket.create_connection(('127.0.0.1', paths['port']), timeout=2):
            client, _ = endpoint.accept(); client.close()
        # A real local listening endpoint and successful unsandboxed positive
        # control distinguish denied connect from refusal/unavailable networking.
        code, out, err = run(sandbox_argv(work, ['-c', PROBE, json.dumps(paths), 'parent', PROBE]),
                             work['root'], environment(work['tmp']), 20)
        need(code == 0 and not err, 'sandbox_unavailable')
        proof = json.loads(out)
        required = {'outside': True, 'source': True, 'builder': True, 'allowed': True, 'network': True}
        need(proof == dict(required, inherited=required), 'sandbox_ineffective')
        endpoint.settimeout(0.1)
        try:
            extra, _ = endpoint.accept(); extra.close()
        except socket.timeout:
            pass
        else:
            raise source.Refusal('sandbox_network_reached_endpoint')
    need(all(read(Path(paths[n])) == b for n, b in before.items()), 'canary_changed')
    return {'kernel_checks': proof, 'loopback_positive_control': True,
            'baseline_target_write_permission': True, 'protected_paths_probed': False,
            'policy': work['policy_record'][0].decode('utf-8'),
            'policy_sha256': digest(work['policy_record'][0]),
            'preflight_argv': sandbox_argv(work, ['-c', PROBE, json.dumps(paths), 'parent', PROBE])}


def allocate():
    root = Path(tempfile.mkdtemp(prefix='bm-release-workflow-', dir='/private/tmp'))
    need(stat.S_IMODE(root.stat().st_mode) == 0o700, 'workspace_mode')
    return {'root': root, 'identity': identity(root)}


def create_workspace(work, expected, manifest, builder, fixture):
    root = work['root']
    # On setup failure the exclusive root remains for review, never broad cleanup.
    for name in ('builder-private', 'repository', 'canaries', 'repository-sibling'):
        (root / name).mkdir(mode=0o700)
    repo = root / 'repository'; (repo / REPO).mkdir(mode=0o700); (repo / 'tmp').mkdir(mode=0o700)
    work.update(repo=repo, tmp=repo / 'tmp', export=root / 'export',
                builder=root / 'builder-private/build_repository.py', policy=root / 'canaries/policy.sb',
                outside=root / 'repository-sibling/outside', product=root / 'export' / PRODUCT)
    source.export(REPOSITORY, MANIFEST, work['export'])
    write(work['builder'], builder, 0o700); write(repo / REPO / 'addon.xml', fixture, 0o644)
    write(work['policy'], policy(repo).encode()); write(work['outside'], b'outside control')
    work['bindings'] = {p: identity(p) for p in (root, work['export'], root / 'builder-private', repo,
                        work['tmp'], root / 'canaries', root / 'repository-sibling')}
    work['builder_record'] = read(work['builder']); work['policy_record'] = read(work['policy'])
    work['fixture_record'] = read(repo / REPO / 'addon.xml')
    work['expected_builder'] = builder
    return work


def check_inputs(work, expected, manifest):
    for p, token in work['bindings'].items():
        need(identity(p) == token, 'workspace_changed')
    source.verify_export(REPOSITORY, MANIFEST, work['export'])
    need(read(work['builder']) == work['builder_record']
         and work['builder_record'][0] == work['expected_builder'], 'builder_snapshot_changed')
    need(read(work['policy']) == work['policy_record'], 'policy_changed')
    need(read(work['repo'] / REPO / 'addon.xml') == work['fixture_record'], 'fixture_changed')
    with source.directory(work['product']) as fd:
        actual, dirs = source.scan(fd)
    need(set(actual) == set(expected) and all(actual[n][0] == b for n, b in expected.items()), 'source_changed')
    need(digest(source.encoded(manifest)) == RELEASE_MANIFEST, 'release_pin')
    # Generated targets and completion records cannot already exist.
    for name in ('omega', REPO + '-1.0.0.zip'):
        with source.directory(work['repo']) as fd:
            try:
                os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise source.Refusal('output_already_exists')


def xml_bytes(root):
    tree = ET.ElementTree(root); ET.indent(tree, space='  ')
    result = io.BytesIO(); tree.write(result, encoding='UTF-8', xml_declaration=True)
    return result.getvalue()


def archive(raw, expected):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        info = z.infolist(); names = [i.filename for i in info]
        need(len(names) == len(set(names)) == len({n.casefold() for n in names}) == len(expected)
             and set(names) == set(expected), 'archive_members')
        for item in info:
            need(item.external_attr >> 16 == stat.S_IFREG | 0o644 and not item.is_dir()
                 and not item.extra and not item.comment and not item.flag_bits & 1, 'archive_mode')
            need(item.file_size == len(expected[item.filename]), 'archive_size')
            need(z.read(item) == expected[item.filename], 'archive_bytes')
        need(z.testzip() is None and not z.comment, 'archive_crc')


def tree(path):
    """Bounded no-follow inventory, preserving identities rather than extracting."""
    def walk(fd, prefix=''):
        files = {}; dirs = {}
        for name in sorted(os.listdir(fd)):
            need(name not in ('', '.', '..') and '/' not in name and '\\' not in name, 'output_name')
            s = os.stat(name, dir_fd=fd, follow_symlinks=False); rel = prefix + name
            need(s.st_uid == os.geteuid() and not s.st_mode & 0o022, 'output_owner')
            if stat.S_ISDIR(s.st_mode):
                child = os.open(name, source.DIR, dir_fd=fd)
                try:
                    need(source.identity(os.fstat(child)) == source.identity(s), 'output_changed')
                    f, d = walk(child, rel + '/'); files.update(f); dirs.update(d)
                    need(source.signature(os.fstat(child)) == source.signature(s), 'output_changed')
                    dirs[rel] = source.signature(s)
                finally:
                    os.close(child)
            else:
                files[rel] = source.read_at(fd, name)
        return files, dirs
    with source.directory(path) as fd:
        token = source.identity(os.fstat(fd)); result = walk(fd); source.binding(path, token)
    return result


def verify_outputs(work, expected, fixture):
    product = ET.fromstring(expected['addon.xml']); product.set('version', VERSION)
    addon_xml = xml_bytes(product)
    repo_xml = ET.fromstring(fixture)
    index = ET.Element('addons'); index.append(repo_xml); index.append(ET.fromstring(addon_xml))
    index_bytes = xml_bytes(index)
    repo_zip_name = 'omega/zips/' + REPO + '/' + REPO + '-1.0.0.zip'
    product_zip_name = 'omega/zips/' + PRODUCT + '/' + PRODUCT + '-' + VERSION + '.zip'
    first = tree(work['repo']); files, dirs = first
    expected_files = {REPO + '/addon.xml': fixture,
        'omega/zips/' + PRODUCT + '/addon.xml': addon_xml,
        'omega/zips/' + PRODUCT + '/resources/images/icon.png': expected['resources/images/icon.png'],
        'omega/zips/' + REPO + '/addon.xml': fixture,
        'omega/zips/addons.xml': index_bytes,
        'omega/zips/addons.xml.md5': hashlib.md5(index_bytes).hexdigest().encode()}
    need(set(files) == set(expected_files) | {repo_zip_name, REPO + '-1.0.0.zip', product_zip_name}, 'output_members')
    for name, body in expected_files.items():
        need(files[name][0] == body, 'output_metadata')
    raw = files[product_zip_name][0]
    need(len(expected) == 75, 'release_inventory')
    archived = {PRODUCT + '/' + n: (addon_xml if n == 'addon.xml' else b) for n, b in expected.items()}
    archive(raw, archived)
    need(len(raw) == ZIP_SIZE and digest(raw) == ZIP_SHA256, 'product_zip_digest')
    repo_raw = files[repo_zip_name][0]
    archive(repo_raw, {REPO + '/addon.xml': fixture})
    need(repo_raw == files[REPO + '-1.0.0.zip'][0], 'repository_zip_copy')
    wanted_dirs = {'tmp'} | {str(p) for n in files for p in Path(n).parents if str(p) != '.'}
    need(set(dirs) == wanted_dirs, 'output_directories')
    need(tree(work['repo']) == first and identity(work['repo']) == work['bindings'][work['repo']], 'output_changed')
    return {'package_sha256': digest(raw), 'package_size': len(raw), 'package_members': len(archived),
            'index_sha256': digest(index_bytes), 'index_md5': hashlib.md5(index_bytes).hexdigest(),
            'repository_zip_sha256': digest(repo_raw), 'MD5_is_signature': False,
            'output_inventory': [{'path': n, 'sha256': digest(b), 'size': len(b)} for n, (b, _) in sorted(files.items())]}


def cleanup(work):
    root = work['root']; need(root.parent == Path('/private/tmp') and root.name.startswith('bm-release-workflow-'), 'cleanup_root')
    need(identity(root) == work['identity'], 'cleanup_identity')
    tree(root)  # Refuse symlinks, hardlinks, foreign ownership or unsafe modes.
    def remove(fd):
        for name in os.listdir(fd):
            s = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(s.st_mode):
                c = os.open(name, source.DIR, dir_fd=fd)
                try:
                    need(source.identity(os.fstat(c)) == source.identity(s), 'cleanup_changed'); remove(c)
                finally:
                    os.close(c)
                need(source.identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) == source.identity(s), 'cleanup_changed')
                os.rmdir(name, dir_fd=fd)
            else:
                need(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_uid == os.geteuid(), 'cleanup_type')
                need(source.signature(os.stat(name, dir_fd=fd, follow_symlinks=False)) == source.signature(s), 'cleanup_changed')
                os.unlink(name, dir_fd=fd)
    with source.directory(root.parent) as parent:
        fd = os.open(root.name, source.DIR, dir_fd=parent)
        try:
            need(source.identity(os.fstat(fd)) == work['identity'], 'cleanup_changed'); remove(fd)
        finally:
            os.close(fd)
        need(source.identity(os.stat(root.name, dir_fd=parent, follow_symlinks=False)) == work['identity'], 'cleanup_changed')
        os.rmdir(root.name, dir_fd=parent)


def rehearse():
    work = None; phase = 'admission'; old_umask = os.umask(0o077)
    try:
        expected, manifest, builder, fixture = authenticate()
        phase = 'workspace'; work = allocate()
        create_workspace(work, expected, manifest, builder, fixture)
        check_inputs(work, expected, manifest)
        phase = 'confinement'; proof = confinement(work)
        phase = 'pre-execution'; check_inputs(work, expected, manifest)
        phase = 'builder'
        argv = sandbox_argv(work, [str(work['builder']), '--source', str(work['product']),
                                  '--version', VERSION, '--repository-root', str(work['repo'])])
        code, _, err = run(argv, work['root'], environment(work['tmp']), 60)
        need(code == 0 and not err, 'builder_failed')
        phase = 'verification'; outputs = verify_outputs(work, expected, fixture)
        # Authenticate source/snapshot/policy again without requiring absent outputs.
        need(read(work['builder']) == work['builder_record'] and read(work['policy']) == work['policy_record'], 'inputs_changed')
        source.verify_export(REPOSITORY, MANIFEST, work['export'])
        phase = 'finalization'; cleanup(work)
        # Sole success record, constructed after every gate including cleanup.
        return {'schema': 'bm-offline-release-rehearsal/1', 'ok': True, 'publication_authorized': False,
                'phase': 'complete', 'cleanup': 'complete', 'product_commit': PRODUCT_COMMIT,
                'product_tree': PRODUCT_TREE, 'source_manifest_sha256': SOURCE_MANIFEST,
                'release_manifest_sha256': RELEASE_MANIFEST, 'builder_blob': BUILDER_BLOB,
                'builder_sha256': BUILDER_SHA256, 'fixture_sha256': FIXTURE_SHA256,
                'source_inventory': manifest['included'], 'exclusion': manifest['excluded'],
                'python': PYTHON, 'python_version': sys.version,
                'workspace_bindings': [{'path': str(p), 'device_inode': token}
                                       for p, token in work['bindings'].items()],
                'sandbox': proof, 'builder_argv': argv, 'environment': environment(work['tmp']), **outputs}
    except Exception:
        return {'schema': 'bm-offline-release-rehearsal/1', 'ok': False, 'publication_authorized': False,
                'phase': phase, 'error': 'rehearsal_refused', 'partial_state': 'unverified',
                'cleanup': 'not_confirmed',
                'workspace': str(work['root']) if work else None}
    finally:
        os.umask(old_umask)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args != ['rehearse']:
        result = {'ok': False, 'error': 'arguments_invalid', 'publication_authorized': False}
    else:
        result = rehearse()
    try:
        raw = source.encoded(result)
        if os.write(1, raw) != len(raw): return 2
    except Exception:
        return 2
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
