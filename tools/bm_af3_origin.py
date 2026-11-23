"""Read-only AF3 registration and bounded startup-source evidence for Test.app."""
import argparse
import json
import os
import struct
import time

from tools import bm_af3_cache as cache
from tools import bm_af3_adapter_stage as stage
from tools import bm_profile_isolation as fs
from tools import bm_test_app as host

ADDON = 'plugin.video.themoviedb.helper'
MONITOR = ADDON + '/resources/tmdbhelper/lib/monitor/service.py'
PYC = MONITOR.removesuffix('service.py') + '__pycache__/service.cpython-311.opt-1.pyc'
LABEL = 'Window(Home).Property(TMDbHelper.ServiceStarted)'
SOURCES = {
    ADDON + '/addon.xml': '1e66bfeab08c6bc4b6f9a422202cf6e0588d7ab46caa7f1d7449b83a87342ac6',
    ADDON + '/resources/service.py': '4c28f1d23964b950c92ac37d176d4f508383156f3bf3325bd36e72fdbd1c062b',
    MONITOR: 'be6dbaa4855e25f644d45f4c23ef3934323095f4e87d3a528e08f81d0a56473a',
    'script.module.jurialmunkey/resources/modules/jurialmunkey/window.py':
        '9f8bf242b206cac116c3a708c44c090757e0073241a8f514bb57d829fd9b54fa',
}


def source_tokens(target, native):
    result = {}
    for relative, digest in SOURCES.items():
        path = target.addons_dir / relative
        with fs.directory(path.parent) as parent:
            data, metadata = cache.file_record(parent, path.name, native, 300000)
            link = fs.exists(parent, path.name)
            fs.need(link is not None and fs.identity(link) == metadata[:2]
                    and link.st_ctime_ns == metadata[6], 'af3_witness_source_changed')
        fs.need(fs.digest(data) == digest, 'af3_witness_source_changed')
        result[relative] = metadata
    return result


def identify(services, require):
    identity = host.identify(services, require=require)
    fs.need(identity.bundle.info_plist_sha256 == cache.INFO_SHA, 'af3_witness_wrong_bundle')
    return identity


def verify_zip(services):
    cache.pinned(services.target.root / 'Contents/MacOS/Kodi', 159486800, cache.EXE_SHA)
    source, _ = host.load_af3_zip_source(services, host.PROJECT, prepare=False)
    source.verify(services)
    fs.need(source.manifest['driver']['tree_sha256'] == stage.CANDIDATE_TREE, 'af3_witness_adapter')
    return source.manifest_sha256


def before_launch(services, native):
    identity = identify(services, 'not_running')
    projection = verify_zip(services)
    target = services.target
    for aid in sorted(host._adapter._AF3_PACKAGES):
        with fs.directory(target.addon_dir(aid)) as fd:
            fs.need(not cache.cache_names(fd, aid), 'af3_witness_cache_present')
    sources = source_tokens(target, native)
    with fs.directory(target.addons_dir) as fd:
        root = fs.identity(os.fstat(fd))
    fs.need(identify(services, 'not_running') == identity, 'af3_witness_identity_changed')
    return {'schema': 1, 'phase': 'stopped_cache_free', 'recorded_ns': time.time_ns(),
            'projection_sha256': projection, 'addons_identity': root, 'sources': sources}


def home_registration(client, target):
    packages = {}
    for aid, (version, _, _) in host._adapter._AF3_PACKAGES.items():
        response = client.call('Addons.GetAddonDetails',
            {'addonid': aid, 'properties': ['version', 'enabled', 'broken', 'path']})
        addon = response.get('addon') if isinstance(response, dict) else None
        fs.need(isinstance(addon, dict) and addon.get('addonid') == aid
                and addon.get('version') == version and addon.get('enabled') is True
                and addon.get('broken') is False, 'af3_witness_registration')
        expected = target.addon_dir(aid)
        ordinary = str(expected)
        allowed = (ordinary, '/System/Volumes/Data' + ordinary, 'special://home/addons/' + aid)
        reported = addon.get('path')
        fs.need(isinstance(reported, str) and reported.removesuffix('/') in allowed,
                'af3_witness_not_home')
        # Never traverse a server-provided path. Verify the corresponding fixed local directory.
        with fs.directory(expected):
            pass
        packages[aid] = {'version': version, 'origin': 'portable_home'}
    return packages


def cache_witness(data, row, source, since, now):
    fs.need(len(data) > 16 and data[:4] == b'\xa7\r\r\n', 'af3_witness_cache_format')
    flags, mtime, size = struct.unpack('<III', data[4:16])
    fs.need(flags == 0 and mtime == (source[5] // 1_000_000_000) & 0xffffffff
            and size == source[4] & 0xffffffff, 'af3_witness_cache_header')
    fs.need(since <= row[5] <= now and since <= row[6] <= now
            and since <= int(row[10] * 1_000_000_000) <= now, 'af3_witness_cache_not_fresh')
    return fs.digest(data)


def observe(services, native, baseline, expected_pid):
    fs.need(baseline.get('schema') == 1 and baseline.get('phase') == 'stopped_cache_free'
            and type(baseline.get('recorded_ns')) is int
            and 0 < baseline['recorded_ns'] < time.time_ns(), 'af3_witness_baseline')
    identity = identify(services, 'running')
    fs.need(type(expected_pid) is int and expected_pid > 0 and identity.pid == expected_pid,
            'af3_witness_pid_changed')
    target = services.target
    projection = verify_zip(services)
    fs.need(projection == baseline.get('projection_sha256'), 'af3_witness_projection_changed')
    with fs.directory(target.addons_dir) as fd:
        fs.need(fs.identity(os.fstat(fd)) == baseline.get('addons_identity'), 'af3_witness_target_changed')
    client = host.RpcClient(services, identity.pid, '127.0.0.1', 8080, 'kodi')
    fs.need(client.call('JSONRPC.Ping', {}) == 'pong' and client.authenticated,
            'af3_witness_not_authenticated')
    packages = home_registration(client, target)
    label = client.call('XBMC.GetInfoLabels', {'labels': [LABEL]})
    fs.need(label == {LABEL: 'True'}, 'af3_witness_startup_marker_missing')
    sources = source_tokens(target, native)
    fs.need(sources == baseline.get('sources'), 'af3_witness_source_changed')
    path = target.addons_dir / PYC
    with fs.directory(path.parent) as fd:
        data, row = cache.file_record(fd, path.name, native, cache.LIMIT)
    digest = cache_witness(data, row, sources[MONITOR], baseline['recorded_ns'], time.time_ns())
    fs.need(identify(services, 'running') == identity, 'af3_witness_identity_changed')
    return {'status': 'observed', 'pid': identity.pid, 'authenticated': True,
            'registration': packages, 'startup_service': ADDON,
            'startup_marker': True, 'fresh_monitor_cache_sha256': digest,
            'fresh_monitor_cache_mtime_ns': row[5],
            'scope': 'tmdb_helper_monitor_initialization_only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    stopped = commands.add_parser('prepare')
    stopped.add_argument('--output', required=True)
    running = commands.add_parser('observe')
    running.add_argument('--baseline', required=True)
    running.add_argument('--baseline-sha256', required=True)
    running.add_argument('--expected-pid', type=int, required=True)
    args = parser.parse_args()
    services = host.Services.production()
    native = fs.Native()
    try:
        if args.command == 'prepare':
            out = host.check_cli_path(args.output, services)
            raw = fs.encoded(before_launch(services, native))
            host.write_new_file_atomic(out, raw, 0o600)
            result = {'status': 'prepared', 'baseline_sha256': fs.digest(raw)}
        else:
            path = host.check_cli_path(args.baseline, services)
            baseline = json.loads(cache.pinned(path, 32768, args.baseline_sha256))
            fs.need(isinstance(baseline, dict), 'af3_witness_baseline')
            result = observe(services, native, baseline, args.expected_pid)
            result['baseline_sha256'] = args.baseline_sha256
        print(json.dumps(result, sort_keys=True))
    except (host.HelperError, fs.Refusal) as error:
        parser.exit(1, f'AF3 observation refused ({error.args[0]}).\n')
    except (OSError, ValueError, TypeError):
        parser.exit(1, 'AF3 observation refused.\n')


if __name__ == '__main__':
    main()
