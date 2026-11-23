"""Stopped, exact-file transaction for the one reviewed AF3 adapter."""
import argparse
import fcntl
import io
import json
import os
from pathlib import Path
import stat
import zipfile

from tools import bm_af3_cache as cache
from tools import bm_profile_isolation as fs
from tools import bm_test_app as host

AREA = '.bm-af3-adapter-config-v1'
CONFIG = 'adapter_config.py'
SLOT = 'configuration.slot'
RECORD = 'transaction.json'
ORIGINAL = 'c24e53e29173c822828533b06ea382c8dd96b001643651405cb4a166bead604b'
CANDIDATE = 'cc5691368481e5fc178b0a78b694d26dadce51056828a0740829ce7391e43d43'
ARCHIVE = '76ce64952561dd79df53f76c0efae28a28ad9074b1254e00852f99b0954acceb'
CANDIDATE_TREE = '61772ae0f3838e258f0e1bc7fc8a4df90e5810e7e8770e0a78e271034bc12db6'


def stable_metadata(row):
    # Rename updates ctime. Content reads can advance atime.
    return row[:6] + row[7:]


def read(fd, leaf, native):
    data, metadata = cache.file_record(fd, leaf, native, 300000)
    attached = fs.exists(fd, leaf)
    fs.need(attached is not None and fs.identity(attached) == metadata[:2]
            and attached.st_ctime_ns == metadata[6], 'adapter_leaf_changed')
    return fs.digest(data), stable_metadata(metadata)


def exchange(native, driver, journal):
    """Darwin RENAME_SWAP preserves the original inode and never leaves a gap."""
    if native.lib.renameatx_np(driver, os.fsencode(CONFIG), journal, os.fsencode(SLOT), 0x2):
        raise fs.Refusal('adapter_atomic_swap_failed')


def transact(target, action, candidate, *, original_sha, candidate_sha, stopped, verify, native,
             swap=exchange):
    """Only the production wrapper selects a target. Tests inject disposable fixtures."""
    fs.need(action in ('stage', 'restore'), 'adapter_action_invalid')
    fs.need(fs.digest(candidate) == candidate_sha != original_sha, 'adapter_candidate_mismatch')
    driver_path = target.addon_dir(host.DRIVER_ID)
    stopped()
    with fs.directory(target.portable_data) as parent, fs.directory(driver_path) as driver:
        if fs.exists(parent, AREA) is None:
            fs.need(action == 'stage', 'adapter_transaction_absent')
            verify('original')
            stopped()
            os.mkdir(AREA, 0o700, dir_fd=parent)
            native.sync(parent)
        journal = os.open(AREA, fs.DIR, dir_fd=parent)
        try:
            info = os.fstat(journal)
            fs.need(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.geteuid()
                    and info.st_dev == os.fstat(driver).st_dev, 'adapter_transaction_directory')
            fcntl.flock(journal, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return _apply(target, driver_path, driver, journal, action, candidate, original_sha,
                          candidate_sha, stopped, verify, native, swap)
        finally:
            os.close(journal)


def _apply(target, driver_path, driver, journal, action, candidate, original_sha, candidate_sha,
           stopped, verify, native, swap):
    before = read(driver, CONFIG, native)
    if before[0] == original_sha:
        current = 'original'
    elif before[0] == candidate_sha:
        current = 'candidate'
    else:
        raise fs.Refusal('adapter_installed_config_mismatch')
    verify(current)
    if fs.exists(journal, RECORD) is None:
        fs.need(current == 'original' and action == 'stage', 'adapter_rollback_record_absent')
        if fs.exists(journal, SLOT) is None:
            fd = os.open(SLOT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=journal)
            with os.fdopen(fd, 'wb') as out:
                out.write(candidate)
                out.flush()
                native.sync(out.fileno(), regular=True)
        held = read(journal, SLOT, native)
        fs.need(held[0] == candidate_sha, 'adapter_candidate_slot_mismatch')
        # Resync the slot when recovering a publication interrupted before the journal.
        fd = os.open(SLOT, fs.FILE, dir_fd=journal)
        try:
            native.sync(fd, regular=True)
        finally:
            os.close(fd)
        fd = os.open(CONFIG, fs.FILE, dir_fd=driver)
        try:
            fs.need(fs.identity(os.fstat(fd)) == before[1][:2], 'adapter_leaf_changed')
            native.sync(fd, regular=True)
        finally:
            os.close(fd)
        cache.record(journal, RECORD, fs.encoded({
            'schema': 1, 'driver': fs.identity(os.fstat(driver)),
            'original': before, 'candidate': held,
        }), native)

    raw, _ = cache.file_record(journal, RECORD, native, 32768)
    record = json.loads(raw)
    fs.need(isinstance(record, dict) and set(record) == {'schema', 'driver', 'original', 'candidate'}
            and record['schema'] == 1 and record['driver'] == fs.identity(os.fstat(driver))
            and record['original'][0] == original_sha and record['candidate'][0] == candidate_sha,
            'adapter_rollback_record_mismatch')
    other = 'candidate' if current == 'original' else 'original'
    fs.need(list(before) == record[current] and list(read(journal, SLOT, native)) == record[other],
            'adapter_transaction_collision')
    desired = 'candidate' if action == 'stage' else 'original'
    stopped()
    with fs.directory(driver_path) as fresh_driver, fs.directory(target.portable_data / AREA) as fresh_journal:
        fs.need(fs.identity(os.fstat(fresh_driver)) == fs.identity(os.fstat(driver))
                and fs.identity(os.fstat(fresh_journal)) == fs.identity(os.fstat(journal)),
                'adapter_transaction_path_changed')
        fs.need(list(read(driver, CONFIG, native)) == record[current]
                and list(read(journal, SLOT, native)) == record[other], 'adapter_transaction_collision')
        if desired != current:
            swap(native, driver, journal)
        native.sync(driver)
        native.sync(journal)
        held = 'original' if desired == 'candidate' else 'candidate'
        fs.need(list(read(driver, CONFIG, native)) == record[desired]
                and list(read(journal, SLOT, native)) == record[held], 'adapter_transaction_collision')
    stopped()
    verification = verify(desired)
    return {'status': 'staged' if desired == 'candidate' else 'restored',
            'changed': current != desired, 'verification': verification}


def verify_installation(services, state, candidate):
    target = services.target
    source, expected_config = host.load_af3_zip_source(
        services, host.PROJECT, prepare=state == 'original')
    fs.need(expected_config == candidate and source.manifest['driver']['tree_sha256'] == CANDIDATE_TREE,
            'adapter_projection_mismatch')
    product = source.manifest['build_manager']
    root = target.addon_dir(host.BUILD_MANAGER_ID)
    target.require_chain(root)
    report = host.verify_tree_dir(root, product, source.manifest['candidate']['object_format'])
    fs.need(report['ok'], 'adapter_product_mismatch')
    return {'product_tree_sha256': report['tree_sha256_actual'],
            'adapter_tree_sha256': (host._AF3_ZIP_PRIOR_DRIVER_TREE if state == 'original'
                                    else CANDIDATE_TREE)}


def run(action):
    services = host.Services.production()
    target = services.target
    fs.need(target.production and target.root == Path(host.AUTHORIZED_TEST_APP), 'adapter_wrong_target')

    def stopped():
        identity = host.identify(services, require='not_running')
        fs.need(identity.bundle.info_plist_sha256 == cache.INFO_SHA, 'adapter_wrong_bundle')
        target.require_chain(target.addon_dir(host.DRIVER_ID))


    stopped()
    cache.pinned(target.root / 'Contents/MacOS/Kodi', 159486800, cache.EXE_SHA)
    raw = cache.pinned(cache.EVIDENCE / 'af3-zip-binding-20261121/adapter-candidate.zip', 2 << 20, ARCHIVE)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        candidate = archive.read(host.DRIVER_ID + '/' + CONFIG)
    return transact(target, action, candidate, original_sha=ORIGINAL, candidate_sha=CANDIDATE,
                    stopped=stopped, verify=lambda state: verify_installation(services, state, candidate),
                    native=fs.Native())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'restore'))
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.action), sort_keys=True))
    except (fs.Refusal, host.HelperError) as error:
        parser.exit(1, f'Adapter transaction refused ({error.args[0]}). Preserve the transaction.\n')
    except (OSError, ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile):
        parser.exit(1, 'Adapter transaction refused. Preserve the transaction.\n')


if __name__ == '__main__':
    main()
