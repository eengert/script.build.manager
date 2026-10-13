"""macOS-only native feasibility evidence; no production imports or authority.

The matcher below is a prospective, test-controlled policy experiment. It is
not a durable receipt verifier. Only Swift's event/socket observations originate
in the kernel; operation, fingerprint, profile and session strings are assertions.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
CLIENT = r'''
import json, os, select, socket, sys
s = socket.socket(socket.AF_UNIX)
s.settimeout(3)
s.connect(sys.argv[1])
s.sendall((sys.argv[2] + '\n').encode())
# Every synthetic process finishes naturally, including failure paths.
if select.select([sys.stdin], [], [], 7)[0]:
    command = sys.stdin.readline().strip()
    if command == 'exec':
        os.execv(sys.executable, [sys.executable, '-c', 'import time; time.sleep(.15)'])
'''

# This process, not the unittest runner, is the witness's actual launcher and
# socket connector. Native stdout is inherited directly by the witness: the
# parent never reads or constructs native witness output. It does validate a
# harness-relayed copy of readiness for PID consistency. The harness keeps
# the pipe reader open after reaping the parent. No session detachment,
# signal, daemon installation, or production process is involved.
PARENT = r'''
import json, os, select, socket, subprocess, sys
def command():
    if not select.select([sys.stdin], [], [], 9)[0]:
        raise RuntimeError('synthetic_parent_command_timeout')
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError('synthetic_parent_command_missing')
    return json.loads(line)
def report(value):
    print(json.dumps(value), file=sys.stderr, flush=True)
witness = subprocess.Popen([sys.argv[1], 'witness', sys.argv[2]],
    stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
# Redirect the parent's stdout writer to /dev/null without leaving fd 1
# available for socket reuse. Only the witness retains the harness pipe's
# writer, so EOF tracks its completion even while the parent is alive.
with open(os.devnull, 'w') as sink:
    os.dup2(sink.fileno(), sys.stdout.fileno())
report(dict(kind='spawned', parent_pid=os.getpid(), witness_pid=witness.pid,
            harness_pid=os.getppid()))
if command() != 'connect':
    raise RuntimeError('synthetic_parent_connect_missing')
s = socket.socket(socket.AF_UNIX)
s.settimeout(3)
s.connect(sys.argv[2])
payload = sys.argv[3]
if sys.argv[4] == 'incomplete':
    s.sendall(payload.encode())
    s.shutdown(socket.SHUT_WR)
else:
    s.sendall((payload + '\n').encode())
    ready = command()
    if (ready.get('kind') != 'ready' or ready.get('witness_pid') != witness.pid
            or ready.get('old', {}).get('pid') != os.getpid()
            or ready.get('authenticated', {}).get('incarnation') != ready['old']):
        raise RuntimeError('synthetic_parent_readiness_missing')
    report(dict(kind='ready_ack', parent_pid=os.getpid(), witness_pid=witness.pid))
if command() != 'exit':
    raise RuntimeError('synthetic_parent_exit_missing')
# Ordinary interpreter exit, with the socket closed naturally. Do not wait for
# the witness here: its NOTE_EXIT requires this process to finish first.
'''


def process_time(identity):
    return identity['start_seconds'] * 1_000_000 + identity['start_micros']


@dataclass(frozen=True)
class SyntheticTuple:
    operation: str
    fingerprint: str
    profile: str
    origin_session: str
    old: tuple
    replacement: tuple
    replacement_session: str


def incarnation_tuple(identity):
    return tuple(identity[key] for key in ('pid', 'start_seconds', 'start_micros'))


class ProspectiveBinding:
    """Pinned in-memory test policy only. Caller dictionaries are NOT receipts."""
    def __init__(self, candidate, ready, exited, peer):
        self.verified = None
        if not all(isinstance(value, dict) for value in (ready, exited, peer)):
            return
        try:
            if (ready['kind'] != 'ready' or exited['kind'] != 'exit'
                    or peer['kind'] != 'peer' or exited['kernel_note_exit'] is not True
                    or ready['witness_pid'] != exited['witness_pid']
                    or ready['old'] != exited['old']
                    or ready['old'] != ready['authenticated']['incarnation']):
                return
            old_auth = ready['authenticated']
            new_auth = peer['authenticated']
            old = old_auth['incarnation']
            new = new_auth['incarnation']
            if (candidate.old != incarnation_tuple(old)
                    or candidate.replacement != incarnation_tuple(new)
                    or old == new
                    or (old['pid'], old_auth['audit_pidversion']) ==
                       (new['pid'], new_auth['audit_pidversion'])
                    or candidate.origin_session == candidate.replacement_session):
                return
            # Conservative synthetic overlap gate: start must be AFTER callback
            # observation, not merely after actual exit. Wall-clock adjustment is
            # a production gap; this does not establish a general temporal proof.
            observed = exited['observed_seconds'] * 1_000_000 + exited['observed_micros']
            if process_time(new) <= observed:
                return
            if str(uuid.UUID(candidate.operation)) != candidate.operation:
                return
            if (not candidate.profile or not candidate.fingerprint.startswith('sha256:')
                    or len(candidate.fingerprint) != 71
                    or not candidate.origin_session or not candidate.replacement_session):
                return
            for evidence, session in ((ready, candidate.origin_session),
                                      (peer, candidate.replacement_session)):
                asserted = evidence['asserted']
                if any(asserted[key] != value for key, value in (
                    ('operation', candidate.operation), ('fingerprint', candidate.fingerprint),
                    ('profile', candidate.profile), ('session', session))):
                    return
            self.verified = candidate
        except (KeyError, TypeError, ValueError):
            return

    def check(self, candidate):
        return self.verified is not None and candidate == self.verified


@unittest.skipUnless(sys.platform == 'darwin', 'requires real macOS kernel APIs')
class RestartWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix='bm-witness-', dir='/private/tmp')
        cls.directory = Path(cls.scratch.name)
        cls.binary = cls.directory / 'witness'
        result = subprocess.run([
            'xcrun', 'swiftc', '-warnings-as-errors', '-lbsm', '-module-cache-path',
            str(cls.directory / 'cache'), str(ROOT / 'tools/create_restart_witness.swift'),
            '-o', str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            cls.scratch.cleanup()
            raise RuntimeError(result.stderr)
        cls.operation = str(uuid.uuid4())
        cls.fingerprint = 'sha256:' + 'a' * 64

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def claim(self, session):
        return dict(operation=self.operation, fingerprint=self.fingerprint,
                    profile='synthetic-canonical-profile', session=session,
                    pid=999999, application='ASSERTED-ONLY')

    def line(self, proc, stream=None):
        stream = proc.stdout if stream is None else stream
        self.assertTrue(select.select([stream], [], [], 9)[0], 'probe output missing')
        line = stream.readline()
        self.assertTrue(line, 'probe unexpectedly closed output')
        return json.loads(line)

    @contextmanager
    def probe(self, *args):
        proc = subprocess.Popen([str(self.binary), *map(str, args)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            yield proc
        finally:
            # The Swift probe is bounded to five seconds; never kill/terminate.
            proc.wait(timeout=12)
            proc.stdout.close()
            proc.stderr.close()

    @contextmanager
    def client(self, path, claim):
        proc = subprocess.Popen([sys.executable, '-c', CLIENT, str(path), json.dumps(claim)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            yield proc
        finally:
            if not proc.stdin.closed:
                proc.stdin.close()  # EOF lets this task-owned synthetic client exit.
            proc.wait(timeout=12)
            proc.stdout.close()
            proc.stderr.close()

    def release(self, proc, command='exit'):
        proc.stdin.write(command + '\n')
        proc.stdin.flush()
        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=10), 0)

    def path(self):
        return self.directory / (uuid.uuid4().hex[:12] + '.sock')

    @contextmanager
    def witness_parent(self, mode='complete'):
        path = self.path()
        claim = self.claim('old-parent')
        # Even an asserted exit must not replace an actual kernel event.
        claim['kernel_note_exit'] = True
        parent = subprocess.Popen([sys.executable, '-c', PARENT,
            str(self.binary), str(path), json.dumps(claim), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        try:
            launched = self.line(parent, parent.stderr)
            self.assertEqual(launched['kind'], 'spawned', launched)
            self.assertEqual(launched['parent_pid'], parent.pid)
            self.assertEqual(launched['harness_pid'], os.getpid())
            listening = self.line(parent)
            self.assertEqual(listening['kind'], 'listening', listening)
            self.assertEqual(listening['witness_pid'], launched['witness_pid'])
            self.parent_command(parent, 'connect')
            yield parent, launched
        finally:
            if not parent.stdin.closed:
                try:
                    parent.stdin.close()  # bounded failure path: parent sees EOF
                except BrokenPipeError:
                    pass  # parent already exited; still collect it and pipe EOF
            parent.stdin = None
            # communicate waits for parent AND inherited witness-pipe EOF.
            # Neither process receives signals, even on assertion failures.
            parent.communicate(timeout=15)
            self.assertFalse(path.exists(), 'witness socket must be removed')

    def parent_command(self, parent, value):
        parent.stdin.write(json.dumps(value) + '\n')
        parent.stdin.flush()

    def parent_ready(self, parent, launched):
        ready = self.line(parent)
        self.assertEqual(ready['kind'], 'ready', ready)
        self.assertEqual(ready['witness_pid'], launched['witness_pid'])
        self.assertEqual(ready['old']['pid'], parent.pid)
        self.assertEqual(ready['old'], ready['authenticated']['incarnation'])
        self.assertGreater(ready['authenticated']['audit_pidversion'], 0)
        self.assertNotEqual(ready['old']['pid'], ready['asserted']['pid'])
        self.assertIsNone(parent.poll(), 'parent must remain alive until ready acknowledgement')
        self.parent_command(parent, ready)
        acknowledged = self.line(parent, parent.stderr)
        self.assertEqual(acknowledged, dict(kind='ready_ack', parent_pid=parent.pid,
                                          witness_pid=launched['witness_pid']))
        self.assertIsNone(parent.poll(), 'parent must acknowledge before exiting')
        return ready, acknowledged

    def test_actual_parent_exit_survival_with_direct_native_evidence(self):
        with self.witness_parent() as (parent, launched):
            ready, acknowledged = self.parent_ready(parent, launched)
            self.parent_command(parent, 'exit')
            self.assertEqual(parent.wait(timeout=10), 0)
            exited = self.line(parent)
            self.assertEqual(exited['kind'], 'exit', exited)
            self.assertIs(exited['kernel_note_exit'], True)
            self.assertEqual(exited['old'], ready['old'])
            self.assertEqual(exited['witness_pid'], launched['witness_pid'])
            # Native NOTE_EXIT can only be emitted by a witness executing after
            # its registered parent has exited. EOF proves its own bounded exit;
            # it need not still be running when Python finishes reaping parent.
            self.assertTrue(select.select([parent.stdout], [], [], 9)[0])
            self.assertEqual(parent.stdout.read(), '')
            print('PARENT_EXIT_EVIDENCE ' + json.dumps(dict(launched=launched,
                ready=ready, acknowledged=acknowledged, exited=exited,
                parent_returncode=parent.returncode, witness_stdout_eof=True), sort_keys=True))

    def test_actual_parent_incomplete_claim_refuses_readiness_and_exit_proof(self):
        with self.witness_parent('incomplete') as (parent, launched):
            refused = self.line(parent)
            self.assertEqual(refused, dict(kind='refused', code='claim_incomplete'))
            self.assertIsNone(parent.poll())
            self.parent_command(parent, 'exit')
            self.assertEqual(parent.wait(timeout=10), 0)
            self.assertTrue(select.select([parent.stdout], [], [], 9)[0])
            self.assertEqual(parent.stdout.read(), '', 'no native ready or exit proof')

    def test_actual_parent_missing_exit_event_refuses_asserted_exit(self):
        with self.witness_parent() as (parent, launched):
            ready, acknowledged = self.parent_ready(parent, launched)
            self.assertIs(ready['asserted']['kernel_note_exit'], True)
            self.assertEqual(self.line(parent), dict(kind='refused', code='exit_evidence_missing'))
            self.assertIsNone(parent.poll(), 'parent stays alive through native timeout')
            self.assertTrue(select.select([parent.stdout], [], [], 9)[0])
            self.assertEqual(parent.stdout.read(), '', 'assertions cannot produce native exit proof')
            self.parent_command(parent, 'exit')
            self.assertEqual(parent.wait(timeout=10), 0)

    def observed_peer(self, claim=None):
        path = self.path()
        with self.probe('peer', path) as probe:
            self.assertEqual(self.line(probe)['kind'], 'listening')
            with self.client(path, claim or self.claim('new')) as client:
                value = self.line(probe)
                self.assertEqual(value['kind'], 'peer', value)
                self.assertEqual(value['authenticated']['incarnation']['pid'], client.pid)
                self.assertEqual(probe.wait(timeout=10), 0)
                return value

    def evidence(self):
        path = self.path()
        with self.probe('witness', path) as probe:
            self.assertEqual(self.line(probe)['kind'], 'listening')
            with self.client(path, self.claim('old')) as client:
                ready = self.line(probe)
                self.assertEqual(ready['kind'], 'ready', ready)
                self.assertIsNone(client.poll(), 'old must remain alive at readiness')
                self.assertEqual(ready['old']['pid'], client.pid)
                self.release(client)
                exited = self.line(probe)
                self.assertEqual(exited['kind'], 'exit', exited)
                self.assertTrue(exited['kernel_note_exit'])
                self.assertEqual(probe.wait(timeout=10), 0)
        peer = self.observed_peer()
        candidate = SyntheticTuple(self.operation, self.fingerprint,
            'synthetic-canonical-profile', 'old', incarnation_tuple(ready['old']),
            incarnation_tuple(peer['authenticated']['incarnation']), 'new')
        return candidate, ready, exited, peer

    def test_genuine_exit_authenticated_connector_and_repeated_exact_binding(self):
        candidate, ready, exited, peer = self.evidence()
        self.assertNotEqual(ready['old']['pid'], ready['asserted']['pid'])
        self.assertNotEqual(peer['authenticated']['incarnation']['pid'], peer['asserted']['pid'])
        self.assertGreater(ready['authenticated']['audit_pidversion'], 0)
        self.assertNotEqual(ready['witness_pid'], ready['old']['pid'])
        self.assertEqual(ready['witness_pid'], exited['witness_pid'])
        binding = ProspectiveBinding(candidate, ready, exited, peer)
        for _ in range(3):
            self.assertTrue(binding.check(candidate))
        print('NATIVE_EVIDENCE ' + json.dumps(dict(ready=ready, exited=exited, replacement=peer), sort_keys=True))

    def test_wrong_tuple_fields_and_replay_are_rejected(self):
        candidate, ready, exited, peer = self.evidence()
        binding = ProspectiveBinding(candidate, ready, exited, peer)
        self.assertTrue(binding.check(candidate))
        for field, value in dict(operation=str(uuid.uuid4()), fingerprint='sha256:'+'b'*64,
                profile='another-profile', origin_session='another-origin',
                replacement_session='another-replacement', old=(123, 1, 1),
                replacement=(456, 2, 2)).items():
            with self.subTest(field=field):
                wrong = replace(candidate, **{field: value})
                self.assertFalse(binding.check(wrong))
                self.assertFalse(ProspectiveBinding(wrong, ready, exited, peer).check(wrong))

    def test_unrelated_replacement_endpoint_rejected(self):
        candidate, ready, exited, peer = self.evidence()
        unrelated = self.observed_peer()  # supplies identical operation/session claims
        self.assertFalse(ProspectiveBinding(candidate, ready, exited, unrelated).check(candidate))

    def test_same_process_new_session_cannot_replace_process(self):
        path = self.path()
        with self.probe('peer', path) as probe:
            self.line(probe)
            with self.client(path, self.claim('new')):
                peer = self.line(probe)
                identity = peer['authenticated']['incarnation']
                ready = dict(kind='ready', old=identity, authenticated=peer['authenticated'],
                             asserted=self.claim('old'), witness_pid=321)
                exited = dict(kind='exit', old=identity, witness_pid=321, kernel_note_exit=True,
                              observed_seconds=identity['start_seconds'], observed_micros=0)
                candidate = SyntheticTuple(self.operation, self.fingerprint,
                    'synthetic-canonical-profile', 'old', incarnation_tuple(identity),
                    incarnation_tuple(identity), 'new')
                # Even an asserted exit dictionary cannot make this legitimate.
                self.assertFalse(ProspectiveBinding(candidate, ready, exited, peer).check(candidate))

    def test_missing_lost_incomplete_or_corrupt_witness_evidence_rejected(self):
        candidate, ready, exited, peer = self.evidence()
        for slot in range(3):
            evidence = [ready, exited, peer]
            evidence[slot] = None
            self.assertFalse(ProspectiveBinding(candidate, *evidence).check(candidate))
        for bad_exit in (None, {}, {**exited, 'kernel_note_exit': False},
                         {**exited, 'kernel_note_exit': 1}, {**exited, 'kind': 'refused'},
                         {**exited, 'witness_pid': -1}, {**exited, 'old': {}}):
            with self.subTest(evidence=bad_exit):
                self.assertFalse(ProspectiveBinding(candidate, ready, bad_exit, peer).check(candidate))

    def test_overlap_with_real_replacement_process_rejected(self):
        path = self.path()
        with self.probe('witness', path) as probe:
            self.line(probe)
            with self.client(path, self.claim('old')) as old:
                ready = self.line(probe)
                new_path = self.path()
                with self.probe('peer', new_path) as second:
                    self.line(second)
                    with self.client(new_path, self.claim('new')) as new:
                        peer = self.line(second)
                        self.assertIsNone(old.poll())
                        self.assertIsNone(new.poll())
                        self.release(old)
                        exited = self.line(probe)
                        candidate = SyntheticTuple(self.operation, self.fingerprint,
                            'synthetic-canonical-profile', 'old', incarnation_tuple(ready['old']),
                            incarnation_tuple(peer['authenticated']['incarnation']), 'new')
                        self.assertFalse(ProspectiveBinding(candidate, ready, exited, peer).check(candidate))

    def test_exec_is_distinct_and_refuses_exit_proof(self):
        path = self.path()
        with self.probe('witness', path) as probe:
            self.line(probe)
            with self.client(path, self.claim('old')) as client:
                self.assertEqual(self.line(probe)['kind'], 'ready')
                self.release(client, 'exec')
                self.assertEqual(self.line(probe), dict(kind='refused', code='exec_is_not_exit'))
                self.assertEqual(probe.wait(timeout=10), 2)

    def test_stale_start_identity_and_missed_exit_refuse(self):
        path = self.path()
        with self.probe('peer', path) as peer_probe:
            self.line(peer_probe)
            with self.client(path, self.claim('old')) as client:
                peer = self.line(peer_probe)
                identity = peer['authenticated']['incarnation']
                with self.probe('observe', client.pid, identity['start_seconds'],
                                (identity['start_micros'] + 1) % 1_000_000, 1) as probe:
                    self.assertEqual(self.line(probe), dict(kind='refused', code='stale_incarnation'))
                self.release(client)
                with self.probe('observe', client.pid, identity['start_seconds'],
                                identity['start_micros'], 1) as probe:
                    self.assertEqual(self.line(probe), dict(kind='refused', code='incarnation_unavailable'))

    def test_no_event_times_out_then_old_exits_naturally(self):
        path = self.path()
        with self.probe('peer', path) as peer_probe:
            self.line(peer_probe)
            with self.client(path, self.claim('old')) as client:
                identity = self.line(peer_probe)['authenticated']['incarnation']
                with self.probe('observe', client.pid, identity['start_seconds'],
                                identity['start_micros'], 1) as probe:
                    self.assertEqual(self.line(probe)['kind'], 'ready')
                    self.assertEqual(self.line(probe), dict(kind='refused', code='exit_evidence_missing'))
                    self.assertIsNone(client.poll())
                    self.assertEqual(probe.wait(timeout=10), 2)
                self.release(client)

    def test_witness_exit_leaves_synthetic_unresolved_reservation_unchanged(self):
        path = self.directory / 'synthetic-reservation.json'
        before = json.dumps(dict(operation=self.operation, state='unresolved', owner='synthetic'))
        path.write_text(before)
        try:
            candidate, ready, exited, peer = self.evidence()
            self.assertTrue(ProspectiveBinding(candidate, ready, exited, peer).check(candidate))
            self.assertEqual(path.read_text(), before)
            self.assertEqual(json.loads(path.read_text())['state'], 'unresolved')
        finally:
            path.unlink()

    def test_peer_claim_is_asserted_not_profile_or_application_authentication(self):
        claim = self.claim('new')
        claim.update(pid=1, application='Kodi', profile='arbitrary-asserted-profile')
        peer = self.observed_peer(claim)
        self.assertNotEqual(peer['authenticated']['incarnation']['pid'], 1)
        self.assertEqual(peer['asserted'], claim)
        self.assertNotIn('profile', peer['authenticated'])
        self.assertNotIn('application', peer['authenticated'])

    def test_missing_connector_refuses_instead_of_asserting_peer_identity(self):
        with self.probe('peer', self.path()) as probe:
            self.assertEqual(self.line(probe)['kind'], 'listening')
            self.assertEqual(self.line(probe), dict(kind='refused', code='peer_timeout'))
            self.assertEqual(probe.wait(timeout=10), 2)

    def test_invalid_process_identity_refuses(self):
        with self.probe('identity', -1) as probe:
            self.assertEqual(self.line(probe), dict(kind='refused', code='invalid_pid'))
            self.assertEqual(probe.wait(timeout=10), 2)

    def test_existing_socket_path_refuses_without_removing_it(self):
        path = self.path()
        path.write_text('retained sentinel')
        try:
            with self.probe('peer', path) as probe:
                self.assertEqual(self.line(probe), dict(kind='refused', code='socket_bind_refused'))
            self.assertEqual(path.read_text(), 'retained sentinel')
        finally:
            path.unlink()


if __name__ == '__main__':
    unittest.main()
