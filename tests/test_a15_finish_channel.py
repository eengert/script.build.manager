"""Non-Kodi PTY rehearsal of the accepted driver's stdin protocol.

The four rehearse_* functions are explicitly selected manual fixtures, never
part of discovery. All ordinary tests below control a disposable child PTY.
No Services, target reader, RPC, credential or acquisition API is invoked.
"""
import errno
import json
import os
import select
import subprocess
import sys
import time
import unittest
from unittest import mock

from tools import bm_preservation_driver as driver


def channel_stub(expected, *, seconds=5, preparing=False):
    """Exercise real pending/announce/wait_signal with only an object baseline."""
    baseline = None
    before_pid = os.getpid()
    begin_count = finish_count = 0
    outcome = 'operation_failed'
    same_baseline = False
    try:
        driver.need(sys.stdin.isatty(), 'protocol_invalid')
        driver.need(not driver.pending(sys.stdin), 'protocol_invalid')
        baseline = object(); original = baseline; begin_count = 1
        if preparing:
            driver.announce(sys.stdout, 'PREPARING')
            time.sleep(0.3)  # synthetic pre-READY acquisition only
        driver.need(not driver.pending(sys.stdin), 'protocol_invalid')
        driver.announce(sys.stdout, 'READY')
        with mock.patch.object(driver, 'WAIT_SECONDS', seconds):
            signal = driver.wait_signal(sys.stdin)
        driver.need(signal == 'FINISH', 'cancelled')
        same_baseline = baseline is original
        finish_count = 1
        outcome = 'finished'
    except driver.Refused as exc:
        outcome = exc.args[0] if exc.args and exc.args[0] in driver.REASONS else 'operation_failed'
    finally:
        baseline = original = None
    result = {'schema': 'bm-a15-channel-stub/1', 'outcome': outcome,
              'begin_count': begin_count, 'finish_count': finish_count,
              'same_private_object': same_baseline, 'disposed': baseline is None and original is None,
              'initial_pid': before_pid, 'final_pid': os.getpid(),
              'native_operations': 0}
    driver.announce(sys.stdout, 'STUB_RESULT ' + json.dumps(result, sort_keys=True))
    if outcome != expected:
        raise AssertionError('unexpected synthetic channel outcome')
    return result


def rehearse_finish():
    return unittest.FunctionTestCase(lambda: channel_stub('finished', seconds=30),
                                     description='explicit non-Kodi tool PTY FINISH rehearsal')


def rehearse_cancel():
    return unittest.FunctionTestCase(lambda: channel_stub('cancelled', seconds=30),
                                     description='explicit non-Kodi tool PTY CANCEL rehearsal')


def rehearse_eof():
    return unittest.FunctionTestCase(lambda: channel_stub('eof', seconds=30),
                                     description='explicit non-Kodi tool PTY EOF rehearsal')


def rehearse_timeout():
    # Test-only short deadline, never a native sub-minute requirement.
    return unittest.FunctionTestCase(lambda: channel_stub('timeout', seconds=0.3),
                                     description='explicit non-Kodi tool PTY timeout rehearsal')


class TerminalChannelTests(unittest.TestCase):
    def start(self, expected, *, seconds=3, preparing=False):
        master, slave = os.openpty()
        code = ('from tests.test_a15_finish_channel import channel_stub; '
                f'channel_stub({expected!r}, seconds={seconds!r}, preparing={preparing!r})')
        child = subprocess.Popen([sys.executable, '-B', '-c', code], stdin=slave,
                                 stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        self.buffer = b''
        def cleanup():
            os.close(master)
            if child.poll() is None:
                child.terminate()  # task-owned harmless stub only
            child.wait(timeout=5)
        self.addCleanup(cleanup)
        return master, child

    def read_until(self, master, needle, timeout=5):
        deadline = time.monotonic() + timeout
        while needle not in self.buffer:
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, 'synthetic PTY observation timed out')
            self.assertTrue(select.select([master], [], [], remaining)[0])
            try: chunk = os.read(master, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO: chunk = b''
                else: raise
            self.assertTrue(chunk, 'synthetic PTY closed before expected output')
            self.buffer += chunk
            self.assertLess(len(self.buffer), 16384)

    def result(self, master, child):
        self.read_until(master, b'STUB_RESULT ')
        self.read_until(master, b'"schema": "bm-a15-channel-stub/1"')
        self.assertEqual(child.wait(timeout=5), 0)
        line = self.buffer.split(b'STUB_RESULT ', 1)[1].splitlines()[0]
        result = json.loads(line)
        self.assertEqual(result['initial_pid'], child.pid)
        self.assertEqual(result['final_pid'], child.pid)
        self.assertTrue(result['disposed'])
        self.assertEqual(result['native_operations'], 0)
        return result

    def test_finish_only_after_observed_ready_preserves_process_and_baseline(self):
        master, child = self.start('finished')
        self.read_until(master, b'READY\r\n')
        self.assertIsNone(child.poll())
        self.assertNotIn(b'STUB_RESULT', self.buffer)
        os.write(master, b'FINISH\n')
        result = self.result(master, child)
        self.assertEqual((result['begin_count'], result['finish_count']), (1, 1))
        self.assertTrue(result['same_private_object'])

    def test_cancel_after_ready_disposes_without_finish(self):
        master, child = self.start('cancelled')
        self.read_until(master, b'READY\r\n'); os.write(master, b'CANCEL\n')
        self.assertEqual(self.result(master, child)['finish_count'], 0)

    def test_eof_after_ready_is_not_a_finish(self):
        master, child = self.start('eof')
        self.read_until(master, b'READY\r\n'); os.write(master, b'\x04')
        self.assertEqual(self.result(master, child)['finish_count'], 0)

    def test_timeout_leaves_no_baseline_and_does_not_finish(self):
        master, child = self.start('timeout', seconds=0.1)
        self.assertEqual(self.result(master, child)['finish_count'], 0)

    def test_input_queued_during_preparation_refuses_before_ready(self):
        master, child = self.start('protocol_invalid', preparing=True)
        self.read_until(master, b'PREPARING\r\n'); os.write(master, b'FINISH\n')
        self.assertEqual(self.result(master, child)['finish_count'], 0)
        self.assertNotIn(b'READY\r\n', self.buffer)

    def test_duplicate_finish_refuses_without_consuming_baseline(self):
        master, child = self.start('protocol_invalid')
        self.read_until(master, b'READY\r\n'); os.write(master, b'FINISH\nFINISH\n')
        self.assertEqual(self.result(master, child)['finish_count'], 0)

    def test_unexpected_line_refuses_without_finish(self):
        master, child = self.start('protocol_invalid')
        self.read_until(master, b'READY\r\n'); os.write(master, b'OTHER\n')
        self.assertEqual(self.result(master, child)['finish_count'], 0)
