"""One foreground A15 session. Never launches, controls, or recovers Kodi.

Only public receipts/statuses leave this driver. The accepted bridge owns the
private in-memory baseline; process loss is never resumable qualification.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import select
import stat
import sys
import time

from tools import bm_test_app as bm
from tools import bm_profile_isolation as isolation
from tools import bm023a_adapter_support as support
from tools.bm_preservation_acquisition import AcquisitionSession
from tools import bm_public_preservation_witness as witness
from resources.lib.build_library import BuildLibrary
from resources.lib.frozen_install import FrozenInstallStore
from resources.lib.capture_lifecycle import FILENAME as CAPTURE_RECORD

REPO = Path('/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex')
WAIT_SECONDS = 900
HOST_PATHS = ('tools/__init__.py', 'tools/bm_preservation_driver.py', 'tools/bm_preservation_acquisition.py',
              'tools/bm_test_app.py', 'tools/bm_profile_isolation.py',
              'tools/bm_public_preservation_witness.py', 'tools/bm023a_adapter_support.py',
              'resources')
REASONS = frozenset({'arguments_invalid', 'source_unverified', 'evidence_invalid',
    'public_unverified', 'begin_refused', 'finish_refused', 'changed', 'cancelled',
    'timeout', 'eof', 'protocol_invalid', 'quit_unverified', 'interrupted',
    'operation_failed', 'cleanup_failed', 'output_failed'})


class Refused(Exception):
    pass


def need(condition, reason):
    if not condition:
        raise Refused(reason)


def trusted_invocation():
    """Reject a foreign checkout/import origin; not an import-time authenticator.

    Imports have already run. The interpreter, startup environment and any
    already-used bytecode must be trusted; -B only prevents bytecode writes.
    """
    need(Path.cwd() == REPO and Path(__file__).absolute() == REPO / 'tools/bm_preservation_driver.py',
         'source_unverified')
    for name, module in tuple(sys.modules.items()):
        if name not in ('tools', 'resources') and not name.startswith(('tools.', 'resources.')):
            continue
        expected = REPO.joinpath(*name.split('.'))
        filename = getattr(module, '__file__', None)
        if filename is None:
            # resources is the existing namespace package, not a new loader.
            paths = list(getattr(module, '__path__', ()))
            need(name == 'resources' and bool(paths) and all(Path(p) == expected for p in paths),
                 'source_unverified')
            continue
        need(type(filename) is str, 'source_unverified')
        path = Path(filename)
        wanted = expected / '__init__.py' if path.name == '__init__.py' else expected.with_suffix('.py')
        need(path.is_absolute() and path == wanted, 'source_unverified')
        origin = getattr(getattr(module, '__spec__', None), 'origin', None)
        need(origin == str(path), 'source_unverified')
        bm.reject_symlink_components(path)


def host_source(services, commit):
    """Existing Git authority, explicit full commit and no mutable HEAD trust."""
    source = bm.GitSource(REPO, services.git_exe, services.git_runner)
    identity = source.resolve_commit(commit)
    entries = source.list_tree(identity, HOST_PATHS)
    required = {p for p in HOST_PATHS if p != 'resources'} | {
        'resources/lib/build_library.py', 'resources/lib/frozen_install.py',
        'resources/lib/capture_lifecycle.py'}
    need(required <= {e.path for e in entries}, 'source_unverified')
    for entry in entries:
        path = REPO / entry.path
        bm.reject_symlink_components(path.parent)
        raw = bm.read_regular_file(path, bm.MAX_FILE_BYTES).data
        need(bm.git_object_id(b'blob', raw, identity.object_format) == entry.oid, 'source_unverified')


def public_state(services, manifest, manifest_sha):
    """Compose existing read-only public witnesses, without acquiring write locks."""
    target = services.target
    snapshot = bm.run_snapshot(services, manifest=manifest, manifest_sha256=manifest_sha,
                               git_repo=REPO, library_baseline=True)
    need(snapshot.get('ok') is True, 'public_unverified')
    verification = snapshot['stage_verification']
    need(verification['installed_equals_candidate'] is True
         and verification['installed_equals_manifest'] is True
         and verification['git_binding']['checked'] is True
         and verification['git_binding']['ok'] is True, 'public_unverified')
    settings = snapshot['settings']; addons = snapshot['installed_addons']
    need(settings['readable'] is True and settings['active_skin'] == 'skin.estuary'
         and settings['updater_policy'] in ('AUTOMATIC', 'NOTIFY_ONLY', 'NEVER_CHECK'), 'public_unverified')
    need(addons['enabled_state_source'] == 'addons_db' and addons['unreadable_addon_xml'] == 0
         and addons['id_mismatch'] == 0 and addons['skipped_invalid_names'] == 0
         and addons['skipped_non_directories'] == 0
         and all(type(e['enabled']) is bool for e in addons['entries']),
         'public_unverified')
    need(snapshot['build_library']['root_present'] is True
         and snapshot['build_library']['registry']['file_present'] is True
         and snapshot['build_library']['selection']['selected'] is True, 'public_unverified')
    root = target.bm_data_dir
    # Absent install/restart/capture owners prove no associated activation hold.
    # Do not call FrozenInstallStore.inspect(): it acquires a creating write lock.
    with isolation.directory(root) as fd:
        need(all(isolation.exists(fd, name) is None for name in
                 ('frozen_install_transaction.json', 'restart_transaction.json', CAPTURE_RECORD)),
             'public_unverified')
    library = BuildLibrary(root / 'build-library')
    need(library.pending_publication() is None, 'public_unverified')
    association = library.current_applied_association(resolution_store=FrozenInstallStore(root, create=False))
    need(association is not None, 'public_unverified')
    state, selected = library.selection_state()
    need(state == 'selected' and selected is not None, 'public_unverified')
    trees = {name: support._af3_public_tree(root / name)
             for name in ('build-library', 'install_resolutions', 'frozen-artifacts')}
    need(all(value is not None for value in trees.values()), 'public_unverified')
    return {'bundle': snapshot['identity']['bundle'], 'settings': settings,
            'addons': addons, 'library': snapshot['build_library'], 'trees': trees,
            'association': association.to_dict(),
            'selection': (selected.entry_id, selected.device_profile_id), 'owners_absent': True}


class Evidence:
    """Exclusive directory; fixed output names, fd-relative no-overwrite writes."""
    def __init__(self, path, services):
        self.path = path
        need(path.is_absolute() and path.parent == REPO / '.qualification-evidence',
             'evidence_invalid')
        bm.check_cli_path(path, services)
        with isolation.directory(path.parent) as parent:
            os.mkdir(path.name, mode=0o700, dir_fd=parent)
        self.fd = None
        with isolation.directory(path) as fd:
            self.identity = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
            self.fd = os.dup(fd)

    def check(self):
        with isolation.directory(self.path) as fd:
            need((os.fstat(fd).st_dev, os.fstat(fd).st_ino) == self.identity, 'evidence_invalid')

    def write(self, name, value):
        need(name in ('ready.json', 'result.json'), 'evidence_invalid')
        self.check()
        data = (json.dumps(value, sort_keys=True) + '\n').encode('ascii')
        need(len(data) < 8192, 'output_failed')
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            need(os.write(fd, data) == len(data), 'output_failed')
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.fd)
        self.check()

    def quit_receipt(self, bundle, ready_ns):
        self.check()
        path = self.path / 'quit.json'
        read_ns = time.time_ns()
        raw = bm.read_regular_file(path, 16384)
        st = os.stat('quit.json', dir_fd=self.fd, follow_symlinks=False)
        need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid()
             and stat.S_IMODE(st.st_mode) == 0o600 and ready_ns <= st.st_mtime_ns <= read_ns
             and (raw.st_dev,raw.st_ino,raw.st_size,raw.st_mtime_ns) ==
                 (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns), 'quit_unverified')
        value = bm.parse_json_strict(raw.data)
        need(set(value) == {'schema','command','ok','graceful','identity_before','identity_after',
                            'invocation','shutdown','tool'}, 'quit_unverified')
        need(value['schema'] == bm.OUTPUT_SCHEMA and value['command'] == 'quit'
             and value['ok'] is True and value['graceful'] is True
             and value['tool'] == bm.tool_identity(), 'quit_unverified')
        before, after = value['identity_before'], value['identity_after']
        invocation, shutdown = value['invocation'], value['shutdown']
        need(before['bundle'] == after['bundle'] == bundle
             and before['process']['state'] == 'running_portable'
             and before['process']['portable_flag'] is True
             and type(before['process']['pid']) is int and before['process']['pid'] > 0
             and type(before['process']['test_app_process_count']) is int
             and before['process']['test_app_process_count'] == 1
             and after['process']['state'] == 'not_running'
             and type(after['process']['test_app_process_count']) is int
             and after['process']['test_app_process_count'] == 0
             and invocation['authenticated'] is True and invocation['listener_pid_verified'] is True
             and invocation['method'] == 'Application.Quit'
             and type(invocation['test_app_pid']) is int
             and invocation['test_app_pid'] == before['process']['pid']
             and shutdown['accepted'] is True and shutdown['exited'] is True
             and shutdown['forced_termination'] is False, 'quit_unverified')
        again = bm.read_regular_file(path, 16384)
        need(again == raw, 'quit_unverified')
        self.check()

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)


def pending(stream):
    return bool(select.select([stream.fileno()], [], [], 0)[0])


def wait_signal(stream):
    deadline = time.monotonic() + WAIT_SECONDS
    data = b''
    while True:
        remaining = deadline - time.monotonic()
        need(remaining > 0, 'timeout')
        if not select.select([stream.fileno()], [], [], remaining)[0]:
            raise Refused('timeout')
        chunk = os.read(stream.fileno(), 32)
        need(bool(chunk), 'eof')
        data += chunk
        need(len(data) <= 7, 'protocol_invalid')
        if b'\n' in data:
            need(data in (b'FINISH\n', b'CANCEL\n'), 'protocol_invalid')
            if pending(stream):
                need(os.read(stream.fileno(), 1) == b'', 'protocol_invalid')
            return data.decode('ascii').strip()


def announce(stream, text):
    need(stream is not None and not getattr(stream, 'closed', False), 'output_failed')
    payload = text + '\n'
    try:
        fd = stream.fileno()
    except (AttributeError, io.UnsupportedOperation):
        written = stream.write(payload)
        need(type(written) is int and written == len(payload), 'output_failed')
        stream.flush()
    else:
        # As with the accepted witness CLI, avoid buffered shutdown retries.
        need(type(fd) is int and fd >= 0, 'output_failed')
        os.fstat(fd)
        data = payload.encode('ascii')
        need(os.write(fd, data) == len(data), 'output_failed')


def project_acquisition(value, boundary):
    """Do not persist arbitrary bridge dictionaries, even on unexpected faults."""
    expected = {'schema','boundary','acquisition','reason','scope_result','files',
                'complete_preservation','qualification','maintenance_attribution',
                'writer_exclusion','temporary_cleanup'}
    reason = 'begin_refused' if boundary == 'before' else 'finish_refused'
    need(type(value) is dict and set(value) == expected, reason)
    need(value['schema'] == 'bm-a15-acquisition/1' and value['boundary'] == boundary
         and value['reason'] == ('baseline_held_in_memory' if boundary == 'before' else 'scoped_comparison')
         and value['acquisition'] == 'ACQUIRED' and value['temporary_cleanup'] == 'COMPLETE'
         and value['complete_preservation'] == 'UNVERIFIED'
         and value['qualification'] == 'not_qualified'
         and value['maintenance_attribution'] == 'UNKNOWN'
         and value['writer_exclusion'] == 'UNVERIFIED', reason)
    need(type(value['files']) is list and len(value['files']) == 5, reason)
    rows = []
    for row, name, scope in zip(value['files'], witness.FILES, witness.SCOPES):
        need(type(row) is dict and set(row) == {'file','scope','status'}
             and row['file'] == name and row['scope'] == scope, reason)
        allowed = ('UNVERIFIED',) if boundary == 'before' else ('PRESERVED','CHANGED_OR_MISSING')
        need(type(row['status']) is str and row['status'] in allowed, reason)
        rows.append({'file':name,'status':row['status']})
    scope = 'UNVERIFIED' if boundary == 'before' else (
        'PRESERVED' if all(row['status'] == 'PRESERVED' for row in rows) else 'CHANGED_OR_MISSING')
    need(value['scope_result'] == scope, reason)
    return {'acquisition':'ACQUIRED','scope_result':scope,'files':rows}


def run(services, *, manifest_path, evidence_path, host_commit, signals, output):
    evidence = session = None
    result = {'schema':'bm-a15-driver/1', 'state':'BLOCKED', 'reason':'operation_failed',
              'complete_preservation':'UNVERIFIED', 'qualification':'not_qualified',
              'native_run_attribution':'UNVERIFIED', 'external_native_evidence_required':True}
    code = 2
    try:
        trusted_invocation()
        need(services.target.production is True and str(services.target.root) == bm.AUTHORIZED_TEST_APP,
             'arguments_invalid')
        host_source(services, host_commit)
        manifest, manifest_sha = bm.load_manifest(manifest_path, services)
        evidence = Evidence(evidence_path, services)
        need(not pending(signals), 'protocol_invalid')
        public_before = public_state(services, manifest, manifest_sha)
        session = AcquisitionSession(services, manifest=manifest, git_repo=REPO)
        begin = project_acquisition(session.begin(), 'before')
        need(isolation.exists(evidence.fd, 'quit.json') is None, 'quit_unverified')
        ready_ns = time.time_ns()
        need(not pending(signals), 'protocol_invalid')
        evidence.write('ready.json', {'schema':'bm-a15-driver/1','state':'READY',
            'host_commit':host_commit,'manifest_sha256':manifest_sha,
            'staged_candidate':manifest['candidate']['commit'], 'public_baseline_acquired':True,
            'begin':begin, 'native_operation_authorized':False})
        announce(output, 'READY')
        signal = wait_signal(signals)
        need(signal == 'FINISH', 'cancelled')
        evidence.quit_receipt(public_before['bundle'], ready_ns)
        host_source(services, host_commit)
        public_after = public_state(services, manifest, manifest_sha)
        after = project_acquisition(session.finish(), 'after')
        public_comparison = 'PRESERVED' if public_before == public_after else 'CHANGED_OR_MISSING'
        result.update(after=after, public_comparison=public_comparison)
        need(after['scope_result'] == 'PRESERVED' and public_comparison == 'PRESERVED', 'changed')
        session.close(); session = None
        result.update(state='SCOPED_PRESERVED', reason='scoped_comparison',
                      receipt_form_and_file_time_validated=True)
        code = 0
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        reason = (exc.args[0] if type(exc) is Refused and len(exc.args) == 1
                  and type(exc.args[0]) is str and exc.args[0] in REASONS else
                  'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'operation_failed')
        result.update(state='INCONCLUSIVE', reason=reason)
    finally:
        if session is not None:
            try: session.close()
            except Exception: result.update(state='INCONCLUSIVE',reason='cleanup_failed'); code = 2
    if evidence is not None:
        try:
            evidence.write('result.json', result)
            evidence.close()
            announce(output, 'DONE')
        except (Exception, KeyboardInterrupt, SystemExit):
            code = 2
        finally:
            try: evidence.close()
            except Exception: code = 2
    return code


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('arguments_invalid')


def main(argv=None):
    try:
        parser = Parser(description='One foreground A15 observation session; no native control.')
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--evidence-dir', required=True)
        parser.add_argument('--host-commit', required=True)
        args = parser.parse_args(argv)
        trusted_invocation()
        return run(bm.Services.production(), manifest_path=Path(args.manifest),
                   evidence_path=Path(args.evidence_dir), host_commit=args.host_commit,
                   signals=sys.stdin, output=sys.stdout)
    except (Exception, KeyboardInterrupt, SystemExit):
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
