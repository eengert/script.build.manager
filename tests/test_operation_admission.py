"""Synthetic filesystem/process probes only. No Kodi, services or process signals."""
from dataclasses import replace
import json
import hashlib
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
import traceback
import unittest
from unittest.mock import patch

from resources.lib import operation_admission as admission
from resources.lib.operation_admission import AdmissionError, CompletionUncertain, Reservation, provision_new


# Spawn (not fork) ensures tests exercise independent flock descriptions.
def _attempt(pin, output):
    started = time.monotonic()
    try:
        with Reservation(pin) as reservation:
            cap = reservation.acquire("contender")
            reservation.complete(cap, lambda: True)
        output.put(("admitted", time.monotonic() - started))
    except AdmissionError as exc:
        output.put((exc.code, time.monotonic() - started))


def _exit_unresolved(pin, output):
    reservation = Reservation(pin)
    cap = reservation.acquire("create")
    reservation.require(cap)
    output.put("unresolved-written")
    # Natural process exit; deliberately no close or complete.


def _race_owner(pin, start, release, output):
    start.wait(5)
    try:
        with Reservation(pin) as reservation:
            cap = reservation.acquire("create")
            output.put("owned")
            release.wait(5)
            reservation.complete(cap, lambda: True)
    except AdmissionError as exc:
        output.put(exc.code)


def _provision_racer(path, start, output):
    start.wait(5)
    try:
        output.put(provision_new(path))
    except AdmissionError as exc:
        output.put(exc.code)


class OperationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bm-admission-")
        self.addCleanup(self.temp.cleanup)
        # tempfile can use a macOS alias; the primitive itself never resolves it.
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "reservation"
        self.pin = provision_new(self.root)
        self.lock = self.root / "reservation.lock"
        self.ctx = multiprocessing.get_context("spawn")

    def reservation(self, pin=None):
        owner = Reservation(pin or self.pin)
        self.addCleanup(owner.close)
        return owner

    def child(self, target, *args):
        output = self.ctx.Queue()
        process = self.ctx.Process(target=target, args=(*args, output))
        process.start()
        result = output.get(timeout=10)
        process.join(10)
        self.assertFalse(process.is_alive(), "synthetic child failed to exit naturally")
        self.assertEqual(process.exitcode, 0)
        output.close()
        output.join_thread()
        process.close()
        return result

    def assert_refused(self, code=None):
        with self.assertRaises(AdmissionError) as caught:
            owner = self.reservation()
            owner.acquire("install")
        if code:
            self.assertEqual(caught.exception.code, code)

    def test_cross_process_nonblocking_exclusion_through_effects_and_verification(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        before = self.lock.read_bytes()
        self.assertIn(b'"phase":"unresolved"', before)
        for _effect in ("capture", "frozen", "restart", "restore"):
            owner.require(cap)
            result, seconds = self.child(_attempt, self.pin)
            self.assertEqual(result, "BM_RESERVATION_BUSY")
            self.assertLess(seconds, 2)
            self.assertEqual(self.lock.read_bytes(), before)
        def verify():
            self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_BUSY")
            owner.require(cap)
            return True
        inode = self.lock.stat().st_ino
        owner.complete(cap, verify)
        self.assertEqual(self.lock.stat().st_ino, inode)
        self.assertEqual(self.child(_attempt, self.pin)[0], "admitted")

    def test_capability_reuse_takes_no_flock_or_store_lock(self):
        owner = self.reservation()
        cap = owner.acquire("install")
        with patch.object(admission.fcntl, "flock", side_effect=AssertionError("relock")):
            # Simulates nested frozen/restart helpers with opposite store orders.
            for _store in ("capture", "frozen", "restart", "restart", "frozen"):
                owner.require(cap)
            owner.complete(cap, lambda: True)

    def test_nested_thread_reuse_never_waits_behind_verifier_store_lock(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        entered, release = threading.Event(), threading.Event()
        errors = []
        def verify():
            entered.set()
            return release.wait(5)
        def finish():
            try:
                owner.complete(cap, verify)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=finish)
        thread.start()
        self.assertTrue(entered.wait(5))
        try:
            # This caller may already hold a store lock needed by the verifier.
            started = time.monotonic()
            with self.assertRaises(AdmissionError) as caught:
                owner.require(cap)
            self.assertEqual(caught.exception.code, "BM_RESERVATION_BUSY")
            self.assertLess(time.monotonic() - started, 1)
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_invalid_wrong_reservation_and_expired_generation_capabilities(self):
        first = self.reservation()
        cap = first.acquire("create")
        other = self.reservation()
        for invalid in (None, object(), replace(cap), replace(cap, _pid=cap._pid + 1)):
            with self.assertRaises(AdmissionError):
                first.require(invalid)
            with self.assertRaises(AdmissionError):
                first.complete(invalid, lambda: self.fail("invalid verifier invoked"))
        with self.assertRaises(AdmissionError):
            other.require(cap)
        with self.assertRaises(AdmissionError):
            first.acquire("nested")
        first.require(cap)
        first.complete(cap, lambda: True)
        new_cap = other.acquire("install")
        self.assertEqual(new_cap._generation, cap._generation + 1)
        with self.assertRaises(AdmissionError):
            other.complete(cap, lambda: self.fail("old verifier invoked"))
        other.complete(new_cap, lambda: True)
        with self.assertRaises(AdmissionError):
            first.require(cap)

    def test_forked_capability_refused_and_child_close_does_not_unlock_parent(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                owner.complete(cap, lambda: True)
                result = b"incorrect"
            except AdmissionError:
                owner.close()
                result = b"refused"
            os.write(write_fd, result)
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        self.assertEqual(os.read(read_fd, 32), b"refused")
        os.close(read_fd)
        self.assertEqual(os.waitpid(pid, 0)[1], 0)
        self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_BUSY")
        owner.complete(cap, lambda: True)

    def test_natural_exit_retains_unresolved_evidence_without_stale_clearing(self):
        self.assertEqual(self.child(_exit_unresolved, self.pin), "unresolved-written")
        before = self.lock.read_bytes()
        for _ in range(2):
            self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_UNRESOLVED")
            self.assertEqual(self.lock.read_bytes(), before)
        self.assert_refused("BM_RESERVATION_UNRESOLVED")

    def test_close_and_exception_never_complete(self):
        with self.assertRaisesRegex(RuntimeError, "effect failed"):
            with Reservation(self.pin) as owner:
                owner.acquire("install")
                raise RuntimeError("effect failed")
        self.assert_refused("BM_RESERVATION_UNRESOLVED")

    def test_mocked_restart_handoff_stays_blocked_until_owner_verifies(self):
        owner = self.reservation()
        cap = owner.acquire("restart")
        for verdict in (False, None, 1, "true"):
            with self.assertRaises(AdmissionError):
                owner.complete(cap, lambda: verdict)
            owner.require(cap)
            self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_BUSY")
        with self.assertRaises(RuntimeError):
            owner.complete(cap, lambda: (_ for _ in ()).throw(RuntimeError()))
        owner.require(cap)
        owner.complete(cap, lambda: True)
        self.assertEqual(self.child(_attempt, self.pin)[0], "admitted")

    def test_recursive_completion_cannot_release_during_verification(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        def verify():
            with self.assertRaises(AdmissionError):
                owner.complete(cap, lambda: True)
            self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_BUSY")
            return True
        owner.complete(cap, verify)

    def test_missing_empty_malformed_and_ambiguous_evidence(self):
        initial = self.lock.read_bytes()
        for bad in (b"", b"{}\n", b"not json\n", initial[:-1], initial + b"{}\n",
                    initial + b"{\"phase\":\"unresolved\",\"phase\":\"completed\"}\n",
                    initial + b"null\n", initial + b"[]\n", initial + b"\n"):
            with self.subTest(bad=bad):
                self.lock.write_bytes(bad)
                self.assert_refused()
                self.assertEqual(self.lock.read_bytes(), bad)
        self.lock.unlink()  # adversarial deletion in a synthetic namespace
        self.assert_refused()
        self.assertFalse(self.lock.exists())
        with self.assertRaises(AdmissionError):
            provision_new(self.root)

    def test_journal_chain_generation_and_owner_corruption_refused(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        owner.complete(cap, lambda: True)
        initial = self.lock.read_bytes()
        rows = [json.loads(line) for line in initial.splitlines()]
        for key, value in (("generation", 9), ("pid", True), ("pid", 0),
                           ("token", "x"), ("operation", "../secret"),
                           ("phase", "idle"), ("previous", "0" * 64)):
            altered = [dict(row) for row in rows]
            altered[-1][key] = value
            self.lock.write_bytes(b"".join(admission._encoded(row) for row in altered))
            self.assert_refused()
        self.lock.write_bytes(initial)
        self.assertEqual(self.child(_attempt, self.pin)[0], "admitted")

    def test_root_lock_and_ancestor_symlinks_refused(self):
        self.root.rename(self.base / "saved")
        self.root.symlink_to(self.base / "saved", target_is_directory=True)
        self.assert_refused()
        alias = self.base / "alias"
        alias.symlink_to(self.base / "saved", target_is_directory=True)
        with self.assertRaises(AdmissionError):
            provision_new(alias / "new")
        self.assertFalse((self.base / "saved" / "new").exists())
        self.root.unlink()
        (self.base / "saved").rename(self.root)
        self.lock.rename(self.root / "saved-lock")
        self.lock.symlink_to(self.root / "saved-lock")
        self.assert_refused()
        self.assertEqual((self.root / "saved-lock").stat().st_ino, self.pin.lock[1])

    def test_pinned_lock_replacement_blocks_old_and_new_openers_split_lock(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        before = self.lock.read_bytes()
        saved = self.root / "original-lock"
        self.lock.rename(saved)
        self.lock.write_bytes(before)  # even byte-identical data has wrong inode
        with self.assertRaises(AdmissionError):
            owner.require(cap)
        with self.assertRaises(AdmissionError):
            owner.complete(cap, lambda: self.fail("replacement verifier invoked"))
        self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_EVIDENCE_INVALID")
        self.assertEqual(saved.read_bytes(), before)
        self.assert_refused()
        self.assertTrue(saved.exists())

    def test_root_replacement_blocks_existing_owner_and_new_open(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        self.root.rename(self.base / "old")
        self.root.mkdir()
        self.lock.write_bytes((self.base / "old" / "reservation.lock").read_bytes())
        with self.assertRaises(AdmissionError):
            owner.require(cap)
        self.assert_refused()

    def test_hardlink_alias_and_nonregular_lock_refused(self):
        os.link(self.lock, self.root / "alias-lock")
        self.assert_refused()
        (self.root / "alias-lock").unlink()
        self.lock.rename(self.root / "saved")
        os.mkfifo(self.lock)
        self.assert_refused()

    def test_replacement_between_open_and_flock_is_refused(self):
        owner = self.reservation()
        original_flock = admission.fcntl.flock
        def replace_during_lock(fd, flags):
            self.lock.rename(self.root / "original-lock")
            self.lock.write_bytes((self.root / "original-lock").read_bytes())
            return original_flock(fd, flags)
        with patch.object(admission.fcntl, "flock", side_effect=replace_during_lock):
            with self.assertRaises(AdmissionError):
                owner.acquire("create")
        self.assert_refused()

    def test_replacement_after_durable_begin_never_grants_capability(self):
        owner = self.reservation()
        original_append = admission._append
        def replace_after_write(fd, row):
            original_append(fd, row)
            self.lock.rename(self.root / "original-lock")
            self.lock.write_bytes((self.root / "original-lock").read_bytes())
        with patch.object(admission, "_append", side_effect=replace_after_write):
            with self.assertRaises(AdmissionError):
                owner.acquire("create")
        self.assertIsNone(owner._capability)
        self.assertIn(b'"phase":"unresolved"', (self.root / "original-lock").read_bytes())
        self.assert_refused()

    def test_durable_write_and_fsync_precede_grant(self):
        owner = self.reservation()
        calls = []
        original_sync = admission._sync
        def sync(fd):
            self.assertIsNone(owner._capability)
            calls.append(fd)
            original_sync(fd)
        with patch.object(admission, "_sync", side_effect=sync):
            cap = owner.acquire("create")
        self.assertIn(owner._fd, calls)
        self.assertIn(owner._root_fd, calls)
        owner.complete(cap, lambda: True)

    def test_short_write_and_sync_failure_do_not_grant_or_repair(self):
        owner = self.reservation()
        original_write = os.write
        def short(fd, data):
            return original_write(fd, data[:len(data) // 2])
        with patch.object(admission.os, "write", side_effect=short):
            with self.assertRaises(AdmissionError):
                owner.acquire("create")
        self.assertIsNone(owner._capability)
        partial = self.lock.read_bytes()
        self.assert_refused()
        self.assertEqual(self.lock.read_bytes(), partial)
        # A separate fresh synthetic namespace tests failed fsync after full begin.
        pin = provision_new(self.base / "sync-failure")
        second = self.reservation(pin)
        with patch.object(admission, "_sync", side_effect=OSError()):
            with self.assertRaises(AdmissionError):
                second.acquire("create")
        self.assertIsNone(second._capability)
        self.assertEqual(self.child(_attempt, pin)[0], "BM_RESERVATION_UNRESOLVED")

    def test_completion_write_failure_leaves_partial_evidence_blocked(self):
        owner = self.reservation()
        cap = owner.acquire("install")
        original_write = os.write
        with patch.object(admission.os, "write", side_effect=lambda fd, data: original_write(fd, data[:10])):
            with self.assertRaises(AdmissionError):
                owner.complete(cap, lambda: True)
        self.assert_refused()
        with self.assertRaises(AdmissionError):
            owner.require(cap)

    def test_journal_limit_fails_closed(self):
        owner = self.reservation()
        with patch.object(admission, "_LIMIT", len(self.lock.read_bytes()) + 10):
            with self.assertRaises(AdmissionError):
                owner.acquire("install")
        self.assertIsNone(owner._capability)

    def test_simultaneous_admission_has_exactly_one_owner(self):
        start, release = self.ctx.Event(), self.ctx.Event()
        output = self.ctx.Queue()
        processes = [self.ctx.Process(target=_race_owner,
                     args=(self.pin, start, release, output)) for _ in range(4)]
        for process in processes:
            process.start()
        start.set()
        try:
            results = [output.get(timeout=10) for _ in processes]
            self.assertEqual(results.count("owned"), 1)
            self.assertEqual(results.count("BM_RESERVATION_BUSY"), 3)
        finally:
            release.set()
            for process in processes:
                process.join(10)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 0)
                process.close()
            output.close()
            output.join_thread()
        self.assertEqual(self.child(_attempt, self.pin)[0], "admitted")

    def test_simultaneous_provision_cannot_create_two_authoritative_locks(self):
        path = str(self.base / "new-race")
        start, output = self.ctx.Event(), self.ctx.Queue()
        processes = [self.ctx.Process(target=_provision_racer, args=(path, start, output)) for _ in range(2)]
        for process in processes:
            process.start()
        start.set()
        rows = [output.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(10)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
            process.close()
        output.close()
        output.join_thread()
        pins = [row for row in rows if isinstance(row, admission.Pin)]
        self.assertEqual(len(pins), 1)
        self.assertEqual(rows.count("BM_RESERVATION_IO_FAILED"), 1)
        self.assertEqual(self.child(_attempt, pins[0])[0], "admitted")

    def test_no_false_global_idle_claim_or_external_observation(self):
        self.assertFalse(hasattr(admission, "competing_operation"))
        self.assertFalse(hasattr(admission, "kodi_is_idle"))
        header = json.loads(self.lock.read_bytes())
        self.assertEqual(header["scope"], "cooperating-bm-only")
        owner = self.reservation()
        # External activity has no representation/authority in this BM-only API.
        external_kodi_active = True
        cap = owner.acquire("create")
        self.assertTrue(external_kodi_active)
        self.assertIsNone(owner.require(cap))
        owner.complete(cap, lambda: True)
        self.assertNotIn(b'"idle"', self.lock.read_bytes())
        self.assertNotIn(b'"quiescent"', self.lock.read_bytes())

    def test_completion_check_read_race_is_sanitized_and_never_completes(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        before = self.lock.read_bytes()
        original_read = owner._read
        reads = []
        saved = self.root / "raced-lock"
        def race():
            reads.append(True)
            # Initial require, post-verifier require, then completion's own read.
            if len(reads) == 3:
                self.lock.rename(saved)
            return original_read()
        with patch.object(owner, "_read", side_effect=race):
            with self.assertRaises(AdmissionError) as caught:
                owner.complete(cap, lambda: True)
        self.assertEqual(len(reads), 3)
        self.assertEqual(str(caught.exception), "BM_RESERVATION_IO_FAILED")
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(saved.read_bytes(), before)
        self.assertFalse(self.lock.exists())
        with self.assertRaises(AdmissionError):
            owner.require(cap)
        self.assert_refused()
        # Synthetic attacker restores the SAME inode, without touching its bytes.
        saved.rename(self.lock)
        self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_UNRESOLVED")

    def test_verifier_oserror_is_not_converted_to_internal_filesystem_refusal(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        before = self.lock.read_bytes()
        failure = FileNotFoundError("synthetic verifier failure")
        def verify():
            raise failure
        with self.assertRaises(FileNotFoundError) as caught:
            owner.complete(cap, verify)
        self.assertIs(caught.exception, failure)
        owner.require(cap)
        self.assertEqual(self.lock.read_bytes(), before)
        owner.complete(cap, lambda: True)

    def test_nul_paths_in_public_provisioning_and_construction_are_sanitized(self):
        for value in (str(self.base / "nul") + "\x00", str(self.base) + "\x00/new"):
            with patch.object(admission.os, "open", side_effect=AssertionError("must reject before open")):
                with self.assertRaises(AdmissionError) as caught:
                    provision_new(value)
                self.assertEqual(str(caught.exception), "BM_RESERVATION_EVIDENCE_INVALID")
                with self.assertRaises(AdmissionError) as caught:
                    Reservation(replace(self.pin, path=value))
                self.assertEqual(str(caught.exception), "BM_RESERVATION_EVIDENCE_INVALID")
        self.assertFalse((self.base / "nul").exists())

    @staticmethod
    def exact_pair(data, generation, operation, token):
        # Independent expected encoding, not the production completion helper.
        row = {"generation": generation, "token": token, "pid": os.getpid(),
               "operation": operation, "phase": "unresolved",
               "previous": hashlib.sha256(data).hexdigest()}
        encode = lambda r: json.dumps(r, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        begin = encode(row)
        end = encode(dict(row, phase="completed", previous=hashlib.sha256(data + begin).hexdigest()))
        return begin, end

    def test_capacity_reserves_both_exact_rows_at_final_boundary(self):
        initial = self.lock.read_bytes()
        token = "a" * 32
        operation = "a" * 64
        begin, end = self.exact_pair(initial, 1, operation, token)
        required = len(initial) + len(begin) + len(end)
        # All these bounds fit the unresolved row, but not its completion.
        for limit in (len(initial) + len(begin), required - 1):
            with patch.object(admission, "_LIMIT", limit), patch.object(admission.uuid, "uuid4") as uid:
                uid.return_value.hex = token
                self.assert_refused_operation(operation, "BM_RESERVATION_JOURNAL_FULL")
            self.assertEqual(self.lock.read_bytes(), initial)
        # At the exact boundary the operation AND verified completion both fit.
        owner = self.reservation()
        with patch.object(admission, "_LIMIT", required), patch.object(admission.uuid, "uuid4") as uid:
            uid.return_value.hex = token
            cap = owner.acquire(operation)
            self.assertEqual(self.lock.read_bytes(), initial + begin)
            owner.complete(cap, lambda: True)
            self.assertEqual(self.lock.read_bytes(), initial + begin + end)
            completed = self.lock.read_bytes()
            self.assert_refused_operation("create", "BM_RESERVATION_JOURNAL_FULL")
            self.assertEqual(self.lock.read_bytes(), completed)

    def assert_refused_operation(self, operation, code):
        owner = self.reservation()
        with self.assertRaises(AdmissionError) as caught:
            owner.acquire(operation)
        self.assertEqual(caught.exception.code, code)
        self.assertIsNone(owner._capability)

    def test_actual_one_mib_boundary_preserves_last_valid_journal(self):
        data = self.lock.read_bytes()
        token = "b" * 32
        generation = 1
        operation = "create"
        # Build only synthetic valid completed history, retaining the pinned inode.
        while True:
            begin, end = self.exact_pair(data, generation, operation, token)
            if len(data) + len(begin) + len(end) > admission._LIMIT:
                break
            next_data = data + begin + end
            next_begin, next_end = self.exact_pair(next_data, generation + 1, operation, token)
            if len(next_data) + len(next_begin) + len(next_end) > admission._LIMIT:
                break
            data = next_data
            generation += 1
        self.lock.write_bytes(data)
        owner = self.reservation()
        with patch.object(admission.uuid, "uuid4") as uid:
            uid.return_value.hex = token
            cap = owner.acquire(operation)
            owner.complete(cap, lambda: True)
        self.assertEqual(self.lock.read_bytes(), next_data)
        self.assertLessEqual(len(next_data), 1024 * 1024)
        self.assert_refused_operation(operation, "BM_RESERVATION_JOURNAL_FULL")
        self.assertEqual(self.lock.read_bytes(), next_data)

    def test_macos_fullsync_write_namespace_order_precedes_capability(self):
        owner = self.reservation()
        journal_fd, root_fd = owner._fd, owner._root_fd
        calls = []
        original_write = os.write
        def write(fd, data):
            self.assertIsNone(owner._capability)
            calls.append(("write", fd))
            return original_write(fd, data)
        def fullsync(fd, command):
            self.assertIsNone(owner._capability)
            self.assertEqual(command, 51)
            calls.append(("fullsync", fd))
            return 0
        with patch.object(admission.sys, "platform", "darwin"), \
                patch.object(admission.fcntl, "F_FULLFSYNC", 51, create=True), \
                patch.object(admission.fcntl, "fcntl", side_effect=fullsync), \
                patch.object(admission.os, "write", side_effect=write), \
                patch.object(admission.os, "fsync", side_effect=AssertionError("weaker fallback")):
            cap = owner.acquire("create")
        self.assertEqual(calls, [("write", journal_fd), ("fullsync", journal_fd), ("fullsync", root_fd)])
        owner.complete(cap, lambda: True)

    def test_macos_fullsync_namespace_provisioning_and_completion(self):
        calls = []
        def fullsync(fd, command):
            self.assertEqual(command, 51)
            calls.append((fd, os.fstat(fd).st_mode))
            return 0
        with patch.object(admission.sys, "platform", "darwin"), \
                patch.object(admission.fcntl, "F_FULLFSYNC", 51, create=True), \
                patch.object(admission.fcntl, "fcntl", side_effect=fullsync), \
                patch.object(admission.os, "fsync", side_effect=AssertionError("weaker fallback")):
            pin = provision_new(self.base / "fullsync-provision")
            import stat
            self.assertEqual([stat.S_ISDIR(mode) for _, mode in calls], [False, True, True])
            self.assertEqual([stat.S_ISREG(mode) for _, mode in calls], [True, False, False])
            owner = self.reservation(pin)
            cap = owner.acquire("create")
            calls.clear()
            lock_fd, root_fd = owner._fd, owner._root_fd
            owner.complete(cap, lambda: True)
            self.assertEqual([fd for fd, _ in calls], [lock_fd, root_fd])

    def test_macos_sync_failure_at_each_admission_step_never_grants(self):
        for failed_step in (1, 2):
            pin = provision_new(self.base / ("failure-" + str(failed_step)))
            owner = self.reservation(pin)
            calls = []
            def fail(fd, command):
                calls.append(fd)
                if len(calls) == failed_step:
                    raise OSError("synthetic private error")
                return 0
            with patch.object(admission.sys, "platform", "darwin"), \
                    patch.object(admission.fcntl, "F_FULLFSYNC", 51, create=True), \
                    patch.object(admission.fcntl, "fcntl", side_effect=fail), \
                    patch.object(admission.os, "fsync", side_effect=AssertionError("fallback")):
                with self.assertRaises(AdmissionError) as caught:
                    owner.acquire("create")
            self.assertEqual(str(caught.exception), "BM_RESERVATION_DURABILITY_FAILED")
            self.assertEqual(len(calls), failed_step)
            self.assertIsNone(owner._capability)
            self.assertIsNone(owner._fd)
            self.assertEqual(self.child(_attempt, pin)[0], "BM_RESERVATION_UNRESOLVED")

    def test_macos_missing_fullsync_refuses_provisioning_and_admission(self):
        owner = self.reservation()
        with patch.object(admission.sys, "platform", "darwin"), \
                patch.object(admission.fcntl, "F_FULLFSYNC", None, create=True), \
                patch.object(admission.os, "fsync", side_effect=AssertionError("fallback")):
            with self.assertRaises(AdmissionError) as caught:
                owner.acquire("create")
            self.assertEqual(caught.exception.code, "BM_RESERVATION_DURABILITY_UNAVAILABLE")
            self.assertIsNone(owner._capability)
            with self.assertRaises(AdmissionError) as caught:
                provision_new(self.base / "unavailable")
            self.assertEqual(caught.exception.code, "BM_RESERVATION_DURABILITY_UNAVAILABLE")
        self.assert_refused("BM_RESERVATION_UNRESOLVED")
        with self.assertRaises(AdmissionError):
            provision_new(self.base / "unavailable")

    def test_macos_provision_sync_failure_at_each_step_returns_no_pin(self):
        for failed_step in (1, 2, 3):
            calls = []
            def fail(fd, command):
                calls.append(fd)
                if len(calls) == failed_step:
                    raise OSError()
                return 0
            path = self.base / ("provision-failure-" + str(failed_step))
            with patch.object(admission.sys, "platform", "darwin"), \
                    patch.object(admission.fcntl, "F_FULLFSYNC", 51, create=True), \
                    patch.object(admission.fcntl, "fcntl", side_effect=fail), \
                    patch.object(admission.os, "fsync", side_effect=AssertionError("fallback")):
                with self.assertRaises(AdmissionError) as caught:
                    provision_new(path)
                self.assertEqual(caught.exception.code, "BM_RESERVATION_DURABILITY_FAILED")
            self.assertEqual(len(calls), failed_step)
            self.assertTrue((path / "reservation.lock").exists())
            with self.assertRaises(AdmissionError):
                provision_new(path)

    def test_other_platform_fsync_has_no_fullsync_claim_or_call(self):
        owner = self.reservation()
        calls = []
        original_sync = os.fsync
        def sync(fd):
            self.assertIsNone(owner._capability)
            calls.append(fd)
            original_sync(fd)
        with patch.object(admission.sys, "platform", "linux"), \
                patch.object(admission.fcntl, "fcntl", side_effect=AssertionError("mac-only")), \
                patch.object(admission.os, "fsync", side_effect=sync):
            cap = owner.acquire("create")
        self.assertEqual(calls, [owner._fd, owner._root_fd])
        owner.complete(cap, lambda: True)

    def test_close_attempts_both_descriptors_once_and_sanitizes(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        descriptors = (owner._fd, owner._root_fd)
        original = os.close
        calls = []
        def close(fd):
            calls.append(fd)
            original(fd)  # simulate freed descriptor despite a reported failure
            if fd == descriptors[0]:
                raise OSError("SECRET/private/close")
        with patch.object(admission.os, "close", side_effect=close):
            with self.assertRaises(AdmissionError) as caught:
                owner.close()
            owner.close()  # no blind retry of an uncertain descriptor number
        self.assertEqual(caught.exception.code, "BM_RESERVATION_CLOSE_FAILED")
        self.assertEqual(calls, list(descriptors))
        self.assertIsNone(owner._fd)
        self.assertIsNone(owner._root_fd)
        with self.assertRaises(AdmissionError):
            owner.require(cap)
        self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_UNRESOLVED")

    def test_constructor_cleanup_preserves_identity_failure_and_closes_all(self):
        original_close = os.close
        closed = []
        def close(fd):
            original_close(fd)
            closed.append(fd)
            raise OSError("synthetic close")
        # Deterministic failure after both owned descriptors have been opened.
        failure = AdmissionError("BM_RESERVATION_CAPABILITY_INVALID")
        with patch.object(Reservation, "_check_identity", side_effect=failure), \
                patch.object(admission.os, "close", side_effect=close), \
                patch.object(admission, "_walk", return_value=(os.open(self.root, os.O_RDONLY | os.O_DIRECTORY), self.pin.directories)):
            with self.assertRaises(AdmissionError) as caught:
                Reservation(self.pin)
        self.assertIs(caught.exception, failure)
        self.assertEqual(caught.exception.cleanup_reason, "BM_RESERVATION_CLOSE_FAILED")
        self.assertEqual(len(closed), 2)
        self.assertEqual(len(set(closed)), 2)

    def test_provision_final_cleanup_attempts_all_and_preserves_durability_error(self):
        for failed_barrier in (False, True):
            path = self.base / ("cleanup-provision-" + str(failed_barrier))
            original = os.close
            closes = []
            def close(fd):
                # Fail only final provisioning cleanup: lock, root, parent.
                original(fd)
                closes.append(fd)
                raise OSError("synthetic close")
            parent = os.open(self.base, os.O_RDONLY | os.O_DIRECTORY)
            # Close that independent inventory descriptor normally.
            inventory, ids = admission._walk(str(self.base))
            os.close(inventory)
            failure = AdmissionError("BM_RESERVATION_DURABILITY_FAILED")
            # Avoid unrelated path-walk closes to target the finalizer exactly.
            with patch.object(admission, "_walk", return_value=(parent, ids)), \
                    patch.object(admission.os, "close", side_effect=close), \
                    patch.object(admission, "_sync", side_effect=failure):
                with self.assertRaises(AdmissionError) as caught:
                    provision_new(path)
            self.assertIs(caught.exception, failure)
            self.assertEqual(caught.exception.cleanup_reason, "BM_RESERVATION_CLOSE_FAILED")
            self.assertEqual(len(closes), 3)
            self.assertEqual(len(set(closes)), 3)
            self.assertTrue((path / "reservation.lock").exists())

    def test_provision_success_final_cleanup_failure_is_typed(self):
        original = os.close
        calls = []
        def close(fd):
            original(fd)
            calls.append(fd)
            if len(calls) >= 1:
                raise OSError("synthetic final close")
        # A scratch root directly under /private/tmp uses a walked parent. Patch
        # only the finalizer helper so path traversal remains real and supported.
        helper = admission._close_descriptors
        def final(descriptors, primary=None):
            if len(descriptors) == 3:
                with patch.object(admission.os, "close", side_effect=close):
                    return helper(descriptors, primary)
            return helper(descriptors, primary)
        with patch.object(admission, "_close_descriptors", side_effect=final):
            with self.assertRaises(AdmissionError) as caught:
                provision_new(self.base / "cleanup-success")
        self.assertEqual(caught.exception.code, "BM_RESERVATION_CLOSE_FAILED")
        self.assertEqual(len(calls), 3)

    def test_context_cleanup_cannot_mask_verifier_or_effect_exception(self):
        owner = self.reservation()
        owner.acquire("create")
        original = os.close
        failure = RuntimeError("synthetic effect")
        def close(fd):
            original(fd)
            raise OSError("synthetic close")
        with patch.object(admission.os, "close", side_effect=close):
            with self.assertRaises(RuntimeError) as caught:
                with owner:
                    raise failure
        self.assertIs(caught.exception, failure)
        self.assertEqual(caught.exception.cleanup_reason, "BM_RESERVATION_CLOSE_FAILED")

    def test_prewrite_codes_preserved_without_uncertainty(self):
        for code in ("BM_RESERVATION_CAPABILITY_INVALID", "BM_RESERVATION_DURABILITY_FAILED",
                     "BM_RESERVATION_DURABILITY_UNAVAILABLE", "BM_RESERVATION_JOURNAL_FULL"):
            pin = provision_new(self.base / code.lower())
            owner = self.reservation(pin)
            cap = owner.acquire("create")
            lock = Path(pin.path) / "reservation.lock"
            before = lock.read_bytes()
            failure = AdmissionError(code)
            with patch.object(admission, "_completion", side_effect=failure):
                with self.assertRaises(AdmissionError) as caught:
                    owner.complete(cap, lambda: True)
            self.assertIs(caught.exception, failure)
            self.assertNotIsInstance(caught.exception, CompletionUncertain)
            self.assertEqual(lock.read_bytes(), before)
            self.assertEqual(self.child(_attempt, pin)[0], "BM_RESERVATION_UNRESOLVED")
        owner = self.reservation()
        cap = owner.acquire("create")
        def verify():
            owner.close()
            return True
        with self.assertRaises(AdmissionError) as caught:
            owner.complete(cap, verify)
        self.assertEqual(caught.exception.code, "BM_RESERVATION_CAPABILITY_INVALID")
        self.assertNotIsInstance(caught.exception, CompletionUncertain)

    def test_prewrite_capacity_and_cleanup_code_precedence(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        before = self.lock.read_bytes()
        helper = admission._close_descriptors
        def faulty(descriptors, primary=None):
            if len(descriptors) == 2:
                helper(descriptors)
                if primary is not None:
                    primary.cleanup_reason = "BM_RESERVATION_CLOSE_FAILED"
                    return
                raise AdmissionError("BM_RESERVATION_CLOSE_FAILED")
            return helper(descriptors, primary)
        with patch.object(admission, "_LIMIT", len(before)), \
                patch.object(admission, "_close_descriptors", side_effect=faulty):
            with self.assertRaises(AdmissionError) as caught:
                owner.complete(cap, lambda: True)
        self.assertEqual(caught.exception.code, "BM_RESERVATION_JOURNAL_FULL")
        self.assertEqual(caught.exception.cleanup_reason, "BM_RESERVATION_CLOSE_FAILED")
        self.assertEqual(self.lock.read_bytes(), before)

    def test_completion_fault_boundaries_and_actual_next_admission(self):
        for point in ("write-failed", "write-partial", "journal-barrier", "namespace-barrier",
                      "identity", "read", "close"):
            with self.subTest(point=point):
                pin = provision_new(self.base / ("boundary-" + point))
                owner = self.reservation(pin)
                cap = owner.acquire("create")
                lock = Path(pin.path) / "reservation.lock"
                original_write = os.write
                original_fcntl = admission.fcntl.fcntl
                original_identity = owner._check_identity
                original_read = owner._read
                original_close = os.close
                descriptors = (owner._fd, owner._root_fd)
                def write(fd, data):
                    if point == "write-failed":
                        raise OSError("synthetic write")
                    if point == "write-partial":
                        return original_write(fd, data[:10])
                    return original_write(fd, data)
                def sync(fd, command):
                    if ((point == "journal-barrier" and fd == descriptors[0]) or
                            (point == "namespace-barrier" and fd == descriptors[1])):
                        raise OSError("synthetic flush")
                    return original_fcntl(fd, command)
                def completed_visible():
                    return b'"phase":"completed"' in lock.read_bytes()
                def identity():
                    if point == "identity" and completed_visible():
                        raise OSError("synthetic identity")
                    return original_identity()
                def read():
                    if point == "read" and completed_visible():
                        raise OSError("synthetic read")
                    return original_read()
                def close(fd):
                    original_close(fd)
                    if point == "close" and fd == descriptors[0]:
                        raise OSError("synthetic close")
                with patch.object(admission.os, "write", side_effect=write), \
                        patch.object(admission.fcntl, "fcntl", side_effect=sync), \
                        patch.object(owner, "_check_identity", side_effect=identity), \
                        patch.object(owner, "_read", side_effect=read), \
                        patch.object(admission.os, "close", side_effect=close):
                    with self.assertRaises(CompletionUncertain) as caught:
                        owner.complete(cap, lambda: True)
                error = caught.exception
                self.assertEqual(str(error), "BM_RESERVATION_COMPLETION_UNCERTAIN")
                expected_reason = ("BM_RESERVATION_DURABILITY_FAILED" if "barrier" in point else
                                   "BM_RESERVATION_CLOSE_FAILED" if point == "close" else
                                   "BM_RESERVATION_EVIDENCE_INVALID" if point == "write-partial" else
                                   "BM_RESERVATION_IO_FAILED")
                self.assertEqual(error.reason, expected_reason)
                self.assertEqual(error.durability_confirmed, point in ("identity", "read", "close"))
                visible = lock.read_bytes()
                try:
                    journal_state = json.loads(visible.splitlines()[-1])["phase"]
                except ValueError:
                    journal_state = "malformed"
                self.assertEqual(journal_state, "unresolved" if point == "write-failed" else
                                 "malformed" if point == "write-partial" else "completed")
                next_result = self.child(_attempt, pin)[0]
                expected_next = ("BM_RESERVATION_UNRESOLVED" if point == "write-failed" else
                                 "BM_RESERVATION_EVIDENCE_INVALID" if point == "write-partial" else "admitted")
                self.assertEqual(next_result, expected_next)
                print("R3 boundary:", point, "code=", error.code, "reason=", error.reason,
                      "barriers_confirmed=", error.durability_confirmed,
                      "journal=", journal_state, "next=", next_result)

    def test_failed_completion_barrier_requires_fresh_durability_before_next_begin(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        with patch.object(admission.fcntl, "fcntl", side_effect=OSError("synthetic barrier")):
            with self.assertRaises(CompletionUncertain) as caught:
                owner.complete(cap, lambda: True)
        self.assertEqual(caught.exception.reason, "BM_RESERVATION_DURABILITY_FAILED")
        self.assertFalse(caught.exception.durability_confirmed)
        before = self.lock.read_bytes()
        self.assertEqual(json.loads(before.splitlines()[-1])["phase"], "completed")
        for fail_step in (1, 2):
            next_owner = self.reservation()
            original_sync = admission._sync
            steps = []
            def sync(fd):
                steps.append(fd)
                if len(steps) == fail_step:
                    raise AdmissionError("BM_RESERVATION_DURABILITY_FAILED")
                original_sync(fd)
            with patch.object(admission, "_sync", side_effect=sync):
                with self.assertRaises(AdmissionError) as failure:
                    next_owner.acquire("install")
            self.assertEqual(failure.exception.code, "BM_RESERVATION_DURABILITY_FAILED")
            self.assertIsNone(next_owner._capability)
            self.assertEqual(self.lock.read_bytes(), before)
        self.assertEqual(self.child(_attempt, self.pin)[0], "admitted")

    def test_require_ambient_exception_does_not_hide_cleanup_failure(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        walk, close = admission._walk, os.close
        targets, calls = set(), []
        def tracked_walk(path):
            result = walk(path)
            targets.add(result[0])
            return result
        def faulty_close(fd):
            close(fd)
            if fd in targets:
                targets.remove(fd)
                calls.append(fd)
                raise OSError("SECRET/private/close")
        try:
            raise RuntimeError("ambient")
        except RuntimeError as ambient:
            with patch.object(admission, "_walk", side_effect=tracked_walk), \
                    patch.object(admission.os, "close", side_effect=faulty_close):
                with self.assertRaises(AdmissionError) as caught:
                    owner.require(cap)
            self.assertFalse(hasattr(ambient, "cleanup_reason"))
        self.assertEqual(caught.exception.code, "BM_RESERVATION_CLOSE_FAILED")
        self.assertEqual(len(calls), 1)

    def test_provision_ambient_exception_does_not_hide_either_cleanup_failure(self):
        for boundary in ("identity", "final"):
            helper, close, walk = admission._close_descriptors, os.close, admission._walk
            targets, calls = set(), []
            path = self.base / ("ambient-" + boundary)
            def tracked_walk(value):
                result = walk(value)
                if value == str(path):
                    targets.add(result[0])
                return result
            def faulty_close(fd):
                calls.append(fd)
                close(fd)
                raise OSError("SECRET/private/close")
            def cleanup(descriptors, primary=None):
                if ((boundary == "final" and len(descriptors) == 3) or
                        (boundary == "identity" and len(descriptors) == 1 and
                         descriptors[0] in targets)):
                    with patch.object(admission.os, "close", side_effect=faulty_close):
                        return helper(descriptors, primary)
                return helper(descriptors, primary)
            try:
                raise RuntimeError("ambient")
            except RuntimeError as ambient:
                with patch.object(admission, "_walk", side_effect=tracked_walk), \
                        patch.object(admission, "_close_descriptors", side_effect=cleanup):
                    with self.assertRaises(AdmissionError) as caught:
                        provision_new(path)
                self.assertFalse(hasattr(ambient, "cleanup_reason"))
            self.assertEqual(caught.exception.code, "BM_RESERVATION_CLOSE_FAILED")
            self.assertEqual(len(calls), 3 if boundary == "final" else 1)
            self.assertEqual(len(calls), len(set(calls)))

    def test_identity_primary_failure_with_cleanup_preserves_actual_exception(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        walk, close = admission._walk, os.close
        fd, identities = walk(self.pin.path)
        failure = AdmissionError("BM_RESERVATION_CAPABILITY_INVALID")
        def faulty_close(value):
            close(value)
            raise OSError("SECRET/private/close")
        try:
            raise RuntimeError("ambient")
        except RuntimeError as ambient:
            with patch.object(admission, "_walk", return_value=(fd, identities)), \
                    patch.object(admission.os, "stat", side_effect=failure), \
                    patch.object(admission.os, "close", side_effect=faulty_close):
                with self.assertRaises(AdmissionError) as caught:
                    owner.require(cap)
            self.assertFalse(hasattr(ambient, "cleanup_reason"))
        self.assertIs(caught.exception, failure)
        self.assertEqual(failure.cleanup_reason, "BM_RESERVATION_CLOSE_FAILED")

    def test_completion_io_and_corruption_reasons_before_and_after_write(self):
        for point in ("fstat", "open", "corrupt", "post-open", "post-corrupt"):
            with self.subTest(point=point):
                pin = provision_new(self.base / ("io-" + point))
                owner = self.reservation(pin)
                cap = owner.acquire("create")
                lock = Path(pin.path) / "reservation.lock"
                original_read, original_open = owner._read, os.open
                def visible():
                    return b'"phase":"completed"' in lock.read_bytes()
                def read():
                    if point == "corrupt" or (point == "post-corrupt" and visible()):
                        os.write(owner._fd, b"invalid evidence\n")
                    if point == "fstat":
                        with patch.object(admission.os, "fstat", side_effect=OSError("SECRET/fstat")):
                            return original_read()
                    return original_read()
                def open_fd(*args, **kwargs):
                    if point == "open" or (point == "post-open" and visible()):
                        raise OSError("SECRET/open")
                    return original_open(*args, **kwargs)
                def verify():
                    # Enter faults only after the verifier, inside the window.
                    stack.enter_context(patch.object(owner, "_read", side_effect=read))
                    stack.enter_context(patch.object(admission.os, "open", side_effect=open_fd))
                    return True
                from contextlib import ExitStack
                with ExitStack() as stack:
                    with self.assertRaises(AdmissionError) as caught:
                        owner.complete(cap, verify)
                error = caught.exception
                reason = "BM_RESERVATION_EVIDENCE_INVALID" if "corrupt" in point else "BM_RESERVATION_IO_FAILED"
                if point.startswith("post-"):
                    self.assertIsInstance(error, CompletionUncertain)
                    self.assertEqual(error.reason, reason)
                else:
                    self.assertEqual(error.code, reason)
                    self.assertNotIsInstance(error, CompletionUncertain)
                self.assertIsNone(owner._capability)
                self.assertIsNone(owner._fd)
                self.assertNotIn("SECRET", str(error))
                expected = ("BM_RESERVATION_EVIDENCE_INVALID" if "corrupt" in point else
                            "admitted" if point == "post-open" else "BM_RESERVATION_UNRESOLVED")
                self.assertEqual(self.child(_attempt, pin)[0], expected)

    def test_completion_interrupt_boundaries_revoke_and_classify(self):
        for point in ("before-write", "during-write", "row-visible", "close"):
            with self.subTest(point=point):
                pin = provision_new(self.base / ("interrupt-" + point))
                owner = self.reservation(pin)
                cap = owner.acquire("create")
                lock = Path(pin.path) / "reservation.lock"
                failure = KeyboardInterrupt("SECRET/interrupt")
                write, sync, close = os.write, admission._sync, os.close
                descriptors, calls = (owner._fd, owner._root_fd), []
                def completion(row, evidence):
                    if point == "before-write":
                        raise failure
                    return dict(row, phase="completed", previous=hashlib.sha256(evidence).hexdigest())
                def append(fd, data):
                    if point == "during-write":
                        raise failure
                    return write(fd, data)
                def barrier(fd):
                    if point == "row-visible":
                        raise failure
                    return sync(fd)
                def cleanup(fd):
                    close(fd)
                    if fd in descriptors:
                        calls.append(fd)
                        if point == "close" and fd == descriptors[0]:
                            raise failure
                        if point != "close":
                            raise OSError("SECRET/cleanup")
                with patch.object(admission, "_completion", side_effect=completion), \
                        patch.object(admission.os, "write", side_effect=append), \
                        patch.object(admission, "_sync", side_effect=barrier), \
                        patch.object(admission.os, "close", side_effect=cleanup):
                    with self.assertRaises(BaseException) as caught:
                        owner.complete(cap, lambda: True)
                error = caught.exception
                if point == "before-write":
                    self.assertIs(error, failure)
                else:
                    self.assertIsInstance(error, CompletionUncertain)
                    self.assertEqual(error.code, "BM_RESERVATION_COMPLETION_UNCERTAIN")
                    self.assertEqual(error.reason, "BM_RESERVATION_INTERRUPTED")
                    self.assertEqual(error.durability_confirmed, point == "close")
                    self.assertNotIn("SECRET", str(error))
                if point != "close":
                    self.assertEqual(error.cleanup_reason, "BM_RESERVATION_CLOSE_FAILED")
                self.assertEqual(calls, list(descriptors))
                self.assertIsNone(owner._capability)
                self.assertIsNone(owner._fd)
                self.assertIsNone(owner._root_fd)
                phase = json.loads(lock.read_bytes().splitlines()[-1])["phase"]
                self.assertEqual(phase, "unresolved" if point in ("before-write", "during-write") else "completed")
                next_result = self.child(_attempt, pin)[0]
                self.assertEqual(next_result, "BM_RESERVATION_UNRESOLVED" if phase == "unresolved" else "admitted")
                print("B3 boundary:", point, "class=", type(error).__name__,
                      "code=", getattr(error, "code", None), "phase=", phase,
                      "capability=revoked next=", next_result)

    def test_verifier_interrupt_preserved_outside_completion_window(self):
        owner = self.reservation()
        cap = owner.acquire("create")
        before = self.lock.read_bytes()
        failure = KeyboardInterrupt("verifier")
        with self.assertRaises(KeyboardInterrupt) as caught:
            owner.complete(cap, lambda: (_ for _ in ()).throw(failure))
        self.assertIs(caught.exception, failure)
        self.assertIs(owner._capability, cap)
        self.assertFalse(owner._verifying)
        self.assertEqual(self.lock.read_bytes(), before)
        owner.close()
        self.assertEqual(self.child(_attempt, self.pin)[0], "BM_RESERVATION_UNRESOLVED")

    def assert_sanitized_failure(self, call, raw, code, ambient=False):
        marker = "INTERNAL_" + "PRIVATE_MARKER"
        def capture():
            with self.assertRaises(AdmissionError) as caught:
                call()
            return caught.exception
        if ambient:
            caller_error = RuntimeError("caller-owned")
            try:
                raise caller_error
            except RuntimeError:
                error = capture()
            self.assertIs(error.__context__, caller_error)
            self.assertFalse(hasattr(caller_error, "cleanup_reason"))
        else:
            error = capture()
            self.assertIsNone(error.__context__)
        self.assertEqual(error.code, code)
        self.assertEqual(str(error), code)
        self.assertIsNone(error.__cause__)
        pending, seen = [error], set()
        while pending:
            current = pending.pop()
            if current is None or id(current) in seen:
                continue
            seen.add(id(current))
            self.assertIsNot(current, raw)
            self.assertNotIsInstance(current, OSError)
            self.assertNotIn(marker, str(current))
            pending.extend((current.__context__, current.__cause__))
        self.assertNotIn(marker, "".join(traceback.format_exception(
            type(error), error, error.__traceback__)))
        return error

    def test_b2_public_io_classification_and_context(self):
        for ambient in (False, True):
            for point in ("mkdir", "provision-open", "constructor-open",
                          "acquire-fstat", "acquire-open", "acquire-write",
                          "require-fstat", "complete-prewrite", "complete-write"):
                with self.subTest(point=point, ambient=ambient):
                    pin = provision_new(self.base / (point + str(ambient)))
                    raw = OSError("INTERNAL_" + "PRIVATE_MARKER")
                    raw.cleanup_reason = "BM_RESERVATION_CLOSE_FAILED"
                    owner = None
                    if point in ("mkdir", "provision-open"):
                        call = lambda: provision_new(self.base / ("new-" + point + str(ambient)))
                    elif point == "constructor-open":
                        call = lambda: Reservation(pin)
                    else:
                        owner = self.reservation(pin)
                        if point.startswith(("require-", "complete-")):
                            cap = owner.acquire("create")
                            call = (lambda: owner.require(cap)) if point.startswith("require-") else (
                                lambda: owner.complete(cap, lambda: True))
                        else:
                            call = lambda: owner.acquire("create")
                    target = point.split("-")[-1]
                    original_open = os.open
                    original_fstat = os.fstat
                    def open_fd(*args, **kwargs):
                        if point == "acquire-open" or args[0] == "reservation.lock":
                            raise raw
                        return original_open(*args, **kwargs)
                    def fstat(fd):
                        if fd == owner._fd:
                            raise raw
                        return original_fstat(fd)
                    fault = (open_fd if target == "open" else fstat if target == "fstat" else raw)
                    module = admission if target == "prewrite" else admission.os
                    method = "_completion" if target == "prewrite" else target
                    with patch.object(module, method, side_effect=fault):
                        code = ("BM_RESERVATION_COMPLETION_UNCERTAIN" if point == "complete-write"
                                else "BM_RESERVATION_IO_FAILED")
                        error = self.assert_sanitized_failure(call, raw, code, ambient)
                    self.assertEqual(error.cleanup_reason, "BM_RESERVATION_CLOSE_FAILED")
                    if point == "complete-write":
                        self.assertEqual(error.reason, "BM_RESERVATION_IO_FAILED")
                        self.assertFalse(error.durability_confirmed)
                    if owner is not None:
                        if point != "require-fstat":
                            self.assertIsNone(owner._capability)
                            self.assertIsNone(owner._fd)
                            self.assertIsNone(owner._root_fd)
                        # require() validates existing authority; caller owns cleanup.
                        owner.close()
                    print("B2 IO:", point, "ambient=", ambient, "code=", error.code,
                          "internal_raw_reachable=False")

    def test_b2_missing_lock_is_io_failed_without_reconstruction(self):
        self.lock.unlink()  # disposable synthetic namespace only
        for ambient in (False, True):
            error = self.assert_sanitized_failure(lambda: Reservation(self.pin), None,
                                                 "BM_RESERVATION_IO_FAILED", ambient)
            self.assertFalse(self.lock.exists())
            self.assertIsNone(error.cleanup_reason)

    def test_b2_sync_and_parse_errors_have_no_internal_context(self):
        owner = self.reservation()
        for ambient in (False, True):
            raw = OSError("INTERNAL_" + "PRIVATE_MARKER")
            with patch.object(admission.sys, "platform", "linux"), \
                    patch.object(admission.os, "fsync", side_effect=raw):
                self.assert_sanitized_failure(lambda: admission._sync(owner._fd), raw,
                                             "BM_RESERVATION_DURABILITY_FAILED", ambient)
            self.lock.write_bytes(b"INTERNAL_PRIVATE_MARKER\n")
            error = self.assert_sanitized_failure(owner._read, None,
                                                 "BM_RESERVATION_EVIDENCE_INVALID", ambient)
            self.assertNotIsInstance(error.__context__, ValueError)

    def test_b2_typed_refusals_preserve_identity_and_cleanup(self):
        for entry in ("provision", "constructor", "acquire", "require", "complete", "sync"):
            failure = AdmissionError("BM_RESERVATION_DURABILITY_UNAVAILABLE")
            failure.cleanup_reason = "BM_RESERVATION_CLOSE_FAILED"
            pin = provision_new(self.base / ("typed-" + entry))
            owner = self.reservation(pin)
            if entry in ("require", "complete"):
                cap = owner.acquire("create")
            if entry == "provision":
                call = lambda: provision_new(self.base / "typed-provision")
                target, method = admission, "_path"
            elif entry == "constructor":
                call = lambda: Reservation(pin)
                target, method = admission, "_walk"
            elif entry == "sync":
                call = lambda: admission._sync(owner._fd)
                target, method = admission.os, "fsync"
            else:
                call = {"acquire": lambda: owner.acquire("create"),
                        "require": lambda: owner.require(cap),
                        "complete": lambda: owner.complete(cap, lambda: True)}[entry]
                target, method = (admission, "_completion") if entry == "complete" else (owner, "_read")
            with patch.object(admission.sys, "platform", "linux"), \
                    patch.object(target, method, side_effect=failure):
                with self.assertRaises(AdmissionError) as caught:
                    call()
            self.assertIs(caught.exception, failure)
            self.assertEqual(failure.cleanup_reason, "BM_RESERVATION_CLOSE_FAILED")
            owner.close()

    def test_b2_busy_error_does_not_retain_blocking_io_error(self):
        for ambient in (False, True):
            owner = self.reservation()
            raw = BlockingIOError("INTERNAL_" + "PRIVATE_MARKER")
            with patch.object(admission.fcntl, "flock", side_effect=raw):
                self.assert_sanitized_failure(lambda: owner.acquire("create"), raw,
                                             "BM_RESERVATION_BUSY", ambient)
            self.assertIsNone(owner._capability)
            self.assertIsNone(owner._fd)
            self.assertIsNone(owner._root_fd)

    def test_errors_do_not_expose_paths_or_evidence(self):
        self.lock.write_bytes(b"SECRET/private/config\n")
        with self.assertRaises(AdmissionError) as caught:
            self.reservation().acquire("create")
        self.assertEqual(str(caught.exception), "BM_RESERVATION_EVIDENCE_INVALID")


if __name__ == "__main__":
    unittest.main()
