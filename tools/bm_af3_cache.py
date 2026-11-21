"""Fixed Test.app AF3 cache quarantine. Never launches Kodi or extracts a ZIP."""
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import stat
import uuid
import zipfile

from tools import bm023a_adapter_support as adapter
from tools import bm_profile_isolation as fs
from tools import bm_test_app as host

EVIDENCE = Path(__file__).absolute().parents[1] / '.qualification-evidence'
INVENTORY = EVIDENCE / 'active-af3-admission-20261121T131812Z/cache-inventory.json'
BACKUP = EVIDENCE / 'af3-prelaunch-controls-20261121T132458Z/af3-cache-backup.zip'
INVENTORY_SHA = '6921bf4bef13c4a9ed3f4d04919901c14838676dd8970079e999283be4513211'
BACKUP_SHA = '1bece9232d9dc24dd87b63dc7984b9ca26a4c1b8bb93cc88c34ce6c57cbf38a9'
INFO_SHA = '9f37ef7b63021ef2ab01b98a44f2f62c8eb68c3f61c014510cc3b7166450bcac'
EXE_SHA = '565ed77a5279df1d34586ba86bf59d81007d125e6593b18866b139718e4bad3c'
AREA = '.bm-af3-cache-quarantine-v1'
LIMIT = 16 << 20


def pinned(path, limit, digest):
    raw = adapter._platform_read(path, limit)
    fs.need(fs.digest(raw) == digest, 'input_identity_changed')
    return raw


def original_sources(inventory):
    _, packages = adapter._af3_inputs(adapter._AF3_MANIFEST, adapter._AF3_STORE)
    sources = {}
    for aid, (data, _) in packages.items():
        tree = adapter._af3_expected_tree(data, aid, adapter._AF3_PACKAGES[aid][0])
        for name in inventory:
            path = Path(name)
            if path.parts[0] != aid:
                continue
            source = path.parent.parent / (path.name.split('.cpython-311.', 1)[0] + '.py')
            value = tree
            for part in source.parts[1:]:
                value = value[part]
            fs.need(isinstance(value, str), 'source_not_in_original')
            sources[source.as_posix()] = value
    return sources


def cache_names(fd, prefix):
    found = set()
    for name in os.listdir(fd):
        leaf = prefix + '/' + name
        info = fs.exists(fd, name)
        fs.need(info is not None, 'package_tree_changed')
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, fs.DIR, dir_fd=fd)
            try:
                fs.need(fs.identity(info) == fs.identity(os.fstat(child)), 'package_tree_changed')
                found.update(cache_names(child, leaf))
            finally:
                os.close(child)
        else:
            fs.need(stat.S_ISREG(info.st_mode), 'unsafe_package_member')
            if name.casefold().endswith('.pyc'):
                found.add(leaf)
    return found


def file_record(fd, name, native, limit):
    item = os.open(name, fs.FILE, dir_fd=fd)
    try:
        before = os.fstat(item)
        fs.need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid == os.geteuid() and before.st_size <= limit, 'unsafe_cache_file')
        with os.fdopen(os.dup(item), 'rb') as stream:
            data = stream.read(limit + 1)
        attrs = native.attrs(item)
        after = os.fstat(item)
        fs.need((before.st_dev, before.st_ino, before.st_mode, before.st_nlink, before.st_size,
                 before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_size,
                 after.st_mtime_ns, after.st_ctime_ns)
                and len(data) == before.st_size, 'cache_changed')
        return data, [before.st_dev, before.st_ino, before.st_mode, before.st_nlink,
                      before.st_size, before.st_mtime_ns, before.st_ctime_ns,
                      before.st_uid, before.st_gid, before.st_flags,
                      before.st_birthtime, attrs]
    finally:
        os.close(item)


def record(fd, name, data, native):
    # A uniquely named unpublished record cannot authorize a cache move.
    temporary = 'pending-' + uuid.uuid4().hex
    item = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                   0o600, dir_fd=fd)
    with os.fdopen(item, 'wb') as stream:
        stream.write(data)
        stream.flush()
        native.sync(stream.fileno(), regular=True)
    native.rename(fd, temporary, name)
    native.sync(fd)


@contextlib.contextmanager
def transaction_area(parent):
    fd = os.open(AREA, fs.DIR, dir_fd=parent)
    try:
        info = os.fstat(fd)
        fs.need(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700
                and info.st_dev == os.fstat(parent).st_dev, 'transaction_directory_invalid')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        os.close(fd)


def transact(addons, inventory, backup, sources, packages, *, action, stopped, native):
    """One transaction. The journal plus exclusive inode locations recover prefix moves."""
    fs.need(action in ('quarantine', 'restore'), 'action_invalid')
    names = sorted(inventory)
    for name in names:
        path = Path(name)
        fs.need(not path.is_absolute() and path.as_posix() == name and '..' not in path.parts
                and path.parts[0] in packages and path.parent.name == '__pycache__'
                and path.suffix == '.pyc', 'inventory_path_invalid')
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        fs.need(sorted(archive.namelist()) == names, 'backup_inventory_changed')
        originals = {name: archive.read(name) for name in names}
    for name, data in originals.items():
        fs.need(len(data) == inventory[name]['size'] <= LIMIT
                and fs.digest(data) == inventory[name]['sha256'], 'backup_member_changed')

    stopped()
    with fs.directory(addons.parent) as parent:
        if fs.exists(parent, AREA) is None:
            fs.need(action == 'quarantine', 'transaction_absent')
            os.mkdir(AREA, 0o700, dir_fd=parent)
            native.sync(parent)
        with transaction_area(parent) as area:
            return _resume(addons, inventory, names, originals, sources, packages, action, stopped, native, area)


def _resume(addons, inventory, names, originals, sources, packages, action, stopped, native, area):
    slots = {name: '%03d.pyc' % index for index, name in enumerate(names)}
    leaves = set(os.listdir(area))
    unknown = leaves - set(slots.values()) - {'inventory.json', 'restoring'}
    for leaf in unknown:
        info = fs.exists(area, leaf)
        fs.need(leaf.startswith('pending-') and len(leaf) == 40 and info is not None
                and stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
                'unknown_transaction_member')
    fresh = 'inventory.json' not in leaves
    if fresh:
        fs.need(action == 'quarantine' and leaves == unknown, 'transaction_record_absent')
        baseline = {}
    else:
        baseline = json.loads(file_record(area, 'inventory.json', native, 1 << 20)[0])
        fs.need(isinstance(baseline, dict) and set(baseline) == set(names)
                and all(isinstance(row, list) and len(row) == 12 for row in baseline.values()),
                'transaction_inventory_changed')
        native.sync(area)
    restoring = 'restoring' in leaves
    if restoring:
        fs.need(file_record(area, 'restoring', native, 32)[0] == b'restore\n'
                and action == 'restore', 'restoration_already_requested')
    for source, digest in sources.items():
        fs.need(fs.digest(adapter._platform_read(addons / source, LIMIT)) == digest, 'original_source_changed')
    all_caches = set()
    for aid in sorted(packages):
        with fs.directory(addons / aid) as fd:
            all_caches.update(cache_names(fd, aid))
    if action == 'quarantine':
        fs.need(all_caches <= set(names), 'unexpected_cache')
    moves = []
    collisions = []
    parent_ids = {}
    for name in names:
        path = addons / name
        slot = slots[name]
        with fs.directory(path.parent) as fd:
            parent_ids[name] = fs.identity(os.fstat(fd))
            live = fs.exists(fd, path.name)
            held = fs.exists(area, slot)
            if live is not None and held is not None:
                fs.need(action == 'restore', 'cache_collision')
                collisions.append(name)
            fs.need(live is not None or held is not None, 'original_cache_missing')
            data, actual = file_record(area if held is not None else fd,
                                       slot if held is not None else path.name, native, LIMIT)
            fs.need(data == originals[name], 'cache_bytes_changed')
            if fresh:
                fs.need(actual[:7] == inventory[name]['identity'], 'original_cache_identity_changed')
                baseline[name] = actual
            else:
                fs.need(actual[:6] == inventory[name]['identity'][:6]
                        and actual[:6] + actual[7:] == baseline[name][:6] + baseline[name][7:],
                        'cache_metadata_changed')
            if action == 'quarantine' and held is None:
                fs.need(actual[:7] == inventory[name]['identity'], 'original_cache_identity_changed')
            if (held is None) == (action == 'quarantine'):
                moves.append(name)
            if not fresh:
                native.sync(fd)
    if collisions:
        return {'status': 'collision', 'paths': collisions, 'moved': 0}
    stopped()
    with fs.directory(addons.parent / AREA) as current:
        fs.need(fs.identity(os.fstat(area)) == fs.identity(os.fstat(current)), 'transaction_path_changed')
    if fresh:
        record(area, 'inventory.json', fs.encoded(baseline), native)
    if action == 'restore' and not restoring:
        record(area, 'restoring', b'restore\n', native)
    for name in moves:
        stopped()
        path = addons / name
        slot = slots[name]
        with fs.directory(path.parent) as live_fd, fs.directory(addons.parent / AREA) as current:
            fs.need(fs.identity(os.fstat(area)) == fs.identity(os.fstat(current))
                    and fs.identity(os.fstat(live_fd)) == parent_ids[name], 'transaction_path_changed')
            src, leaf, dst, destination = ((live_fd, path.name, area, slot) if action == 'quarantine'
                                           else (area, slot, live_fd, path.name))
            data, actual = file_record(src, leaf, native, LIMIT)
            expected = baseline[name]
            fs.need(data == originals[name] and actual[:6] + actual[7:] == expected[:6] + expected[7:],
                    'cache_changed_before_rename')
            attached = fs.exists(src, leaf)
            fs.need(attached is not None and fs.identity(attached) == actual[:2]
                    and attached.st_ctime_ns == actual[6], 'cache_path_changed')
            native.rename_between(src, leaf, dst, destination)
            moved_data, moved_record = file_record(dst, destination, native, LIMIT)
            fs.need(moved_data == data and moved_record[:6] + moved_record[7:] ==
                    actual[:6] + actual[7:], 'cache_changed_after_rename')
            native.sync(src)
            native.sync(dst)
    stopped()
    if action == 'quarantine':
        for aid in sorted(packages):
            with fs.directory(addons / aid) as fd:
                fs.need(not cache_names(fd, aid), 'quarantine_incomplete')
    return {'status': 'quarantined' if action == 'quarantine' else 'restored', 'moved': len(moves)}


def run(action):
    services = host.Services.production()
    target = services.target

    executable = target.root / 'Contents/MacOS/Kodi'

    def target_token():
        with fs.directory(executable.parent) as parent, fs.directory(target.addons_dir) as addons:
            info = fs.exists(parent, executable.name)
            fs.need(info is not None and stat.S_ISREG(info.st_mode), 'bundle_executable_invalid')
            return (info.st_dev, info.st_ino, info.st_size, info.st_ctime_ns, info.st_mtime_ns,
                    *fs.identity(os.fstat(addons)))

    expected = target_token()

    def stopped():
        identity = host.identify(services, require='not_running').report()
        fs.need(identity['bundle']['info_plist_sha256'] == INFO_SHA, 'bundle_identity_changed')
        target.require_chain(target.addons_dir)
        fs.need(target_token() == expected, 'target_identity_changed')

    stopped()
    pinned(executable, 159486800, EXE_SHA)
    stopped()
    inventory = json.loads(pinned(INVENTORY, 1 << 20, INVENTORY_SHA))
    fs.need(len(inventory) == 235, 'inventory_count_changed')
    sources = original_sources(inventory)
    return transact(target.addons_dir, inventory, pinned(BACKUP, 4 << 20, BACKUP_SHA),
                    sources, adapter._AF3_PACKAGES, action=action, stopped=stopped, native=fs.Native())


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('quarantine', 'restore'))
    args = parser.parse_args()
    try:
        result = run(args.action)
    except (fs.Refusal, host.HelperError) as exc:
        parser.exit(1, f'AF3 cache operation refused ({exc.args[0]}). Preserve the transaction directory.\n')
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        parser.exit(1, 'AF3 cache operation refused. Preserve the transaction directory.\n')
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(result['status'] == 'collision')
