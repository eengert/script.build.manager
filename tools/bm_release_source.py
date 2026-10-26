"""Pinned, offline release export. This tool neither builds nor publishes packages.

The repository argument supplies Git objects ONLY, never checkout files. Updating
these pins requires a fresh reviewed admission decision. Partial exports are kept
on error; there is deliberately no recursive deletion or repair operation.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

COMMIT = 'a185e4d346229c1797dfd75e79a7ba3ee016dd53'
TREE = '278f3e7fa49586e2db4e8d055232bf6990c64418'
MANIFEST_SHA256 = '16cf4fb6fd076249ab9b7c8a11dc7a4e9fa2b776c78ecc294aa1ba0b0b6ef0fb'
EXCLUSION = 'resources/config/packages/bm022-fixture/package.json'
EXCLUSION_BLOB = '25256659fb8d852a413b02de86999aece094d2fa'
EXCLUSION_SHA256 = '058c6eee2536f9f116412a959f66de8cc94167f92ea72cca6295211723b61ac7'
PRODUCT = 'script.build.manager'
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
LIMIT = 4 * 1024 * 1024


class Refusal(Exception):
    """Only fixed, nonprivate refusal codes are exposed by the CLI."""


def need(ok, code):
    if not ok:
        raise Refusal(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii') + b'\n'


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, 'ambiguous_json')
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=pairs)


def path(value):
    raw = os.fspath(value)
    need(type(raw) is str and raw.startswith('/') and '\\' not in raw and '\0' not in raw
         and len(raw) <= 4096 and all(p not in ('', '.', '..') for p in raw.split('/')[1:]), 'unsafe_path')
    result = Path(raw)
    forbidden = Path('/Users/eengert/Library/Application Support/Kodi')
    need(not result.is_relative_to(forbidden)
         and not any(p.casefold().endswith('.app') for p in result.parts), 'protected_path')
    return result


def relative(value):
    need(type(value) is str and 0 < len(value) < 1024 and '\\' not in value and '\0' not in value,
         'unsafe_member')
    parts = value.split('/')
    need(all(p and p not in ('.', '..') and not p.startswith('.')
             and len(p) <= 255 and all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.+-' for c in p)
             and p.casefold() not in ('tools', 'tests', 'test', '__pycache__') for p in parts), 'unsafe_member')
    need(value in ('addon.xml', 'default.py', 'service.py') or parts[0] == 'resources', 'unsafe_member')
    return parts


@contextlib.contextmanager
def directory(value):
    value = path(value)
    fd = os.open('/', DIR)
    try:
        for part in value.parts[1:]:
            nxt = os.open(part, DIR, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def identity(st):
    return st.st_dev, st.st_ino


def signature(st):
    return identity(st) + (st.st_mode, st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def binding(value, expected):
    with directory(value) as fd:
        need(identity(os.fstat(fd)) == expected, 'directory_changed')


def read_at(fd, name):
    before = os.stat(name, dir_fd=fd, follow_symlinks=False)
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= LIMIT, 'unsafe_file')
    opened = os.open(name, FILE, dir_fd=fd)
    try:
        need(signature(os.fstat(opened)) == signature(before), 'file_changed')
        chunks = []; size = 0
        while True:
            part = os.read(opened, 65536)
            if not part:
                break
            chunks.append(part); size += len(part)
            need(size <= LIMIT, 'file_too_large')
        need(signature(os.fstat(opened)) == signature(before), 'file_changed')
        need(signature(os.stat(name, dir_fd=fd, follow_symlinks=False)) == signature(before), 'file_changed')
        data = b''.join(chunks)
        need(len(data) == before.st_size, 'file_changed')
        return data, signature(before)
    finally:
        os.close(opened)


def read_file(value):
    value = path(value)
    with directory(value.parent) as fd:
        parent = identity(os.fstat(fd)); data, sig = read_at(fd, value.name)
        binding(value.parent, parent)
        return data, sig


def git(repository, *args):
    # Ignore inherited Git routing/configuration and replacement-object authority.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_NO_REPLACE_OBJECTS='1')
    result = subprocess.run(['git', '--no-lazy-fetch', '--no-replace-objects', '--no-optional-locks',
                             '-c', 'protocol.allow=never', '-C', str(repository), *args],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False)
    need(result.returncode == 0 and len(result.stdout) <= LIMIT, 'git_unavailable')
    return result.stdout


def admit(repository, manifest):
    """Reconstruct all 76 trusted blobs in memory, including the excluded file."""
    repository = path(repository); manifest = path(manifest)
    with directory(repository) as fd:
        repo_identity = identity(os.fstat(fd))
    raw, manifest_sig = read_file(manifest)
    need(digest(raw) == MANIFEST_SHA256, 'manifest_digest')
    record = decode(raw)
    need(record['candidate']['commit'] == COMMIT and record['candidate']['tree'] == TREE, 'candidate_identity')
    need(git(repository, 'rev-parse', COMMIT + '^{commit}').decode().strip() == COMMIT, 'commit_identity')
    need(git(repository, 'rev-parse', COMMIT + '^{tree}').decode().strip() == TREE, 'tree_identity')
    entries = record['build_manager']['files']
    need(type(entries) is list and len(entries) == record['build_manager']['file_count'] == 76, 'source_count')
    data = {}; names = set(); total = 0
    for entry in entries:
        name = entry['path']; relative(name)
        need(name.casefold() not in names, 'member_collision'); names.add(name.casefold())
        need(set(entry) == {'path', 'git_blob', 'git_mode', 'sha256', 'size'}
             and entry['git_mode'] == '100644' and type(entry['size']) is int
             and 0 <= entry['size'] <= LIMIT, 'source_entry')
        row = git(repository, 'ls-tree', '-z', COMMIT, '--', name)
        need(row.count(b'\0') == 1, 'tree_entry')
        meta, actual_path = row[:-1].split(b'\t'); mode, kind, blob = meta.decode().split()
        need(actual_path.decode() == name and mode == '100644' and kind == 'blob'
             and blob == entry['git_blob'], 'blob_identity')
        body = git(repository, 'cat-file', 'blob', blob)
        git_sha = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        need(git_sha == blob and len(body) == entry['size'] and digest(body) == entry['sha256'], 'blob_content')
        data[name] = body; total += len(body)
    need(total == record['build_manager']['total_bytes'], 'source_size')
    exclusion = next(e for e in entries if e['path'] == EXCLUSION)
    need(exclusion['git_blob'] == EXCLUSION_BLOB and exclusion['sha256'] == EXCLUSION_SHA256, 'exclusion_identity')
    need({'addon.xml', 'default.py', 'service.py', 'resources/images/icon.png'} <= data.keys(), 'required_product_files')
    # Recheck input/path identities after object reconstruction. Blob bytes have
    # independent immutable object and SHA256 binding, not checkout authority.
    again, sig = read_file(manifest)
    need(again == raw and sig == manifest_sig, 'manifest_changed')
    binding(repository, repo_identity)
    included = sorted((dict(e) for e in entries if e['path'] != EXCLUSION), key=lambda e: e['path'])
    need(len(included) == 75, 'release_count')
    release = {'schema': 'bm-release-source/1', 'product_commit': COMMIT, 'product_tree': TREE,
               'source_manifest_sha256': MANIFEST_SHA256, 'source_count': 76, 'release_count': 75,
               'included': included, 'excluded': [dict(exclusion, reason='Supervisor-approved synthetic configuration fixture')],
               'qualification': 'offline_export_only', 'publication_authorized': False}
    return data, release


def put(fd, name, data):
    parts = name.split('/'); owned = []
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            fd = os.open(part, DIR, dir_fd=fd); owned.append(fd)
        output = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        try:
            os.fchmod(output, 0o644)
            need(os.write(output, data) == len(data), 'incomplete_write')
        finally:
            os.close(output)
    finally:
        for child in reversed(owned):
            os.close(child)


def scan(fd, prefix=''):
    files = {}; dirs = set()
    for name in sorted(os.listdir(fd)):
        need(name not in ('', '.', '..') and '/' not in name and '\\' not in name, 'unsafe_export')
        rel = prefix + name; s = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(s.st_mode):
            child = os.open(name, DIR, dir_fd=fd)
            try:
                need(identity(os.fstat(child)) == identity(s), 'directory_changed')
                subfiles, subdirs = scan(child, rel + '/')
                files.update(subfiles); dirs.update(subdirs); dirs.add(rel)
            finally:
                os.close(child)
        else:
            data, sig = read_at(fd, name)
            need(stat.S_IMODE(sig[2]) == 0o644, 'export_mode')
            files[rel] = (data, sig)
    return files, dirs


def expected_export(data, release):
    expected = {PRODUCT + '/' + e['path']: data[e['path']] for e in release['included']}
    expected['release-source.json'] = encoded(release)
    dirs = {str(p) for name in expected for p in Path(name).parents if str(p) != '.'}
    return expected, dirs


def verify_export(repository, manifest, output):
    """Fresh Git/manifest admission and exact export verification; never repairs."""
    data, release = admit(repository, manifest)
    output = path(output)
    need(output.is_relative_to('/private/tmp') and output != Path('/private/tmp'), 'output_root')
    expected, dirs = expected_export(data, release)
    with directory(output) as fd:
        root_identity = identity(os.fstat(fd)); first, actual_dirs = scan(fd)
        need(actual_dirs == dirs and set(first) == set(expected), 'export_members')
        need(all(first[n][0] == b for n, b in expected.items()), 'export_content')
        second, second_dirs = scan(fd)
        need(second == first and second_dirs == actual_dirs, 'export_changed')
        binding(output, root_identity)
    return {'ok': True, 'release_manifest_sha256': digest(encoded(release)), 'release_count': 75,
            'product_directory': str(output / PRODUCT), 'publication_authorized': False}


def export(repository, manifest, output):
    data, release = admit(repository, manifest)  # No output created before admission.
    output = path(output)
    need(output.is_relative_to('/private/tmp') and output != Path('/private/tmp'), 'output_root')
    with directory(output.parent) as parent:
        parent_identity = identity(os.fstat(parent))
        os.mkdir(output.name, 0o700, dir_fd=parent)  # Exclusive; never reuse/delete.
        created_identity = identity(os.stat(output.name, dir_fd=parent, follow_symlinks=False))
        with directory(output) as fd:
            root_identity = identity(os.fstat(fd))
            need(root_identity == created_identity, 'directory_changed')
            for entry in release['included']:
                put(fd, PRODUCT + '/' + entry['path'], data[entry['path']])
            put(fd, 'release-source.json', encoded(release))  # Complete record last.
            binding(output, root_identity); binding(output.parent, parent_identity)
    return verify_export(repository, manifest, output)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refusal('arguments_invalid')


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('action', choices=('export', 'verify'))
        parser.add_argument('--repository', required=True)
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--output', required=True)
        args = parser.parse_args(argv)
        operation = export if args.action == 'export' else verify_export
        result = operation(args.repository, args.manifest, args.output)
        code = 0
    except Exception:
        # Partial output is preserved. No exception/path/private detail emitted.
        result = {'ok': False, 'error': 'release_source_refused', 'publication_authorized': False}; code = 2
    try:
        raw = encoded(result)
        if os.write(1, raw) != len(raw):
            return 2
    except Exception:
        return 2
    return code


if __name__ == '__main__':
    raise SystemExit(main())
