"""macOS-only native feasibility evidence; no production imports or authority.

The matcher below is a prospective, test-controlled policy experiment. It is
not a durable receipt verifier. Only Swift's event/socket observations originate
in the kernel; operation, fingerprint, profile and session strings are assertions.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
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

    def line(self, proc):
        self.assertTrue(select.select([proc.stdout], [], [], 9)[0], 'probe output missing')
        line = proc.stdout.readline()
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
