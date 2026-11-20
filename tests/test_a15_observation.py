"""Offline coverage for passive A15 collection and refusal to claim evidence."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from resources.lib import a15_observation as observation
from resources.lib.build_library import AppliedBuildAssociation, BuildLibrary, LibraryConflict, _encode
from resources.lib.frozen_install import FrozenInstallStore, run_frozen_install_startup
from resources.lib.startup import StartupClassification, run_startup
from resources.lib.transaction import TransactionStore
from tools import bm_preservation_driver as driver


class A15ObservationTests(unittest.TestCase):
    def setUp(self):
        area = tempfile.TemporaryDirectory()
        self.addCleanup(area.cleanup)
        self.base = Path(area.name).resolve()
        self.home = self.base / "portable"
        self.profile = self.home / "userdata"
        self.artifacts = self.profile / "addon_data/script.build.manager/frozen-artifacts"
        self.library = BuildLibrary(self.artifacts.parent / "build-library")
        self.app_addons = self.base / "builtins"
        self.temp = self.base / "temp"
        for path in (self.profile, self.app_addons, self.temp, self.home / "addons",
                     self.artifacts / "artifacts", Path(self.library.root)):
            path.mkdir(parents=True, exist_ok=True)
        self.translations = {
            "special://home/": self.home,
            "special://profile/": self.profile,
            "special://profile/addon_data/script.build.manager": self.artifacts.parent,
            "special://home/addons": self.home / "addons",
            "special://xbmc/addons": self.app_addons,
        }
        self.logs = []
        runtime = {
            "xbmcvfs": SimpleNamespace(translatePath=lambda path: str(self.translations[path])),
            "xbmc": SimpleNamespace(LOGINFO=1, log=lambda message, level: self.logs.append(message)),
        }
        for replacement in (patch.dict("sys.modules", runtime),
                            patch.object(observation, "_PORTABLE_HOME", self.home),
                            patch.object(tempfile, "tempdir", str(self.temp))):
            replacement.start()
            self.addCleanup(replacement.stop)

    def phases(self):
        prefix = "[script.build.manager] diagnostic phase="
        for message in self.logs:
            self.assertTrue(message.startswith(prefix), message)
            self.assertNotIn(str(self.base), message)
            self.assertNotIn("sensitive exception text", message)
        return [message.removeprefix(prefix) for message in self.logs]

    def test_staging_emits_before_writes_and_after_cleanup(self):
        with observation.registration_staging() as root:
            self.assertEqual(root.parent, self.temp)
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual(self.phases(), ["create.evidence.staging_confined_before"])
            (root / "public.json").write_text("{}")
        self.assertFalse(root.exists())
        self.assertEqual(self.phases()[-1], "create.evidence.staging_cleaned")

    def test_cold_python_selection_is_distinguished_from_cached_staging(self):
        with patch.object(tempfile, "tempdir", None), patch.dict(os.environ, {"TMPDIR": str(self.temp)}, clear=True):
            with observation.registration_staging() as root:
                self.assertEqual(root.parent, self.temp)
                self.assertEqual(self.phases(), ["create.evidence.staging_confined_first_candidate_before"])
        self.assertEqual(self.phases()[-1], "create.evidence.staging_cleaned")

    def test_cold_fallback_does_not_bound_previous_probes(self):
        with patch.object(tempfile, "tempdir", None), patch.dict(os.environ, {
                "TMPDIR": str(self.temp / "missing"), "TEMP": str(self.temp)}, clear=True):
            with observation.registration_staging() as root:
                self.assertEqual(root.parent, self.temp)
                self.assertEqual(self.phases(), ["create.evidence.staging_confined_cold_before"])
        self.assertEqual(self.phases()[-1], "create.evidence.staging_cleaned")

    def test_changed_temp_cache_cannot_certify_cleanup(self):
        with observation.registration_staging() as root:
            tempfile.tempdir = str(self.base)
        self.assertFalse(root.exists())
        self.assertEqual(self.phases()[-1], "create.evidence.staging_unverified")

    def test_registration_failure_is_unchanged_and_staging_still_cleaned(self):
        failure = LibraryConflict("sensitive exception text")
        with self.assertRaises(LibraryConflict) as raised, observation.registration_staging() as root:
            raise failure
        self.assertIs(raised.exception, failure)
        self.assertFalse(root.exists())
        self.assertEqual(self.phases()[-1], "create.evidence.staging_cleaned")

    def test_observation_fault_does_not_change_cleanup_or_yield(self):
        with patch.object(observation, "_staging_snapshot", side_effect=OSError("sensitive exception text")):
            with observation.registration_staging() as root:
                self.assertTrue(root.is_dir())
        self.assertFalse(root.exists())
        self.assertEqual(self.phases(), ["create.evidence.staging_unverified"])

    def test_staging_within_or_above_protected_scope_is_unverified(self):
        for parent in (self.profile, self.app_addons, self.base):
            with self.subTest(parent=parent), patch.object(tempfile, "tempdir", str(parent)):
                self.logs.clear()
                with observation.registration_staging() as root:
                    self.assertEqual(root.parent, parent)
                self.assertFalse(root.exists())
                self.assertEqual(self.phases(), ["create.evidence.staging_unverified"])

    def test_staging_observation_refuses_redirected_portable_profile(self):
        self.profile.rename(self.base / "redirected-profile")
        self.profile.symlink_to(self.base / "redirected-profile", target_is_directory=True)
        with observation.registration_staging() as root:
            self.assertTrue(root.is_dir())
        self.assertFalse(root.exists())
        self.assertEqual(self.phases(), ["create.evidence.staging_unverified"])

    def test_unknown_temp_parent_alias_and_symlinked_staging_leaf_are_refused(self):
        alias = self.base / "temp-alias"
        alias.symlink_to(self.temp, target_is_directory=True)
        with patch.object(tempfile, "tempdir", str(alias)), observation.registration_staging() as root:
            self.assertEqual(root.parent, self.temp)
        self.assertEqual(self.phases(), ["create.evidence.staging_unverified"])
        link = self.temp / "bm-create-public-unsafe"
        link.symlink_to(self.profile, target_is_directory=True)
        with self.assertRaises(ValueError):
            observation._staging_snapshot(str(link), link.resolve())

    def test_system_temp_alias_is_bound_to_its_known_real_parent(self):
        with patch.object(Path, "is_symlink", return_value=True), patch.object(
                os, "readlink", return_value="private/var"):
            parent = observation._temporary_parent("/var/folders/test/bm-create-public-123")
            self.assertEqual(parent, Path("/private/var/folders/test"))
        with patch.object(Path, "is_symlink", return_value=True), patch.object(
                os, "readlink", return_value="/unrelated"):
            with self.assertRaises(ValueError):
                observation._temporary_parent("/var/folders/test/bm-create-public-123")

    def test_replaced_staging_root_is_unverified_even_if_cleanup_removes_replacement(self):
        old = self.temp / "old"
        with observation.registration_staging() as root:
            root.rename(old)
            root.mkdir()
        self.assertFalse(root.exists())
        self.assertTrue(old.is_dir())
        self.assertEqual(self.phases(), [
            "create.evidence.staging_confined_before", "create.evidence.staging_unverified",
        ])

    def test_replaced_parent_is_unverified_even_when_the_staging_inode_survives(self):
        old = self.temp.with_name("old-parent")
        with observation.registration_staging() as root:
            self.temp.rename(old)
            self.temp.mkdir()
            (old / root.name).rename(root)
        self.assertFalse(root.exists())
        self.assertEqual(self.phases(), [
            "create.evidence.staging_confined_before", "create.evidence.staging_unverified",
        ])

    def test_cleanup_exception_escapes_unchanged_even_if_directory_is_absent(self):
        error = OSError("sensitive exception text")

        class CleanupError(tempfile.TemporaryDirectory):
            def __exit__(self, *args):
                super().__exit__(*args)
                raise error

        with patch.object(tempfile, "TemporaryDirectory", CleanupError):
            with self.assertRaises(OSError) as raised, observation.registration_staging() as root:
                pass
        self.assertIs(raised.exception, error)
        self.assertFalse(root.exists())
        self.assertEqual(self.phases()[-1], "create.evidence.staging_unverified")

    def test_logger_exception_is_contained(self):
        import xbmc
        with patch.object(xbmc, "log", side_effect=RuntimeError("sensitive exception text")):
            with observation.registration_staging() as root:
                self.assertTrue(root.is_dir())
        self.assertFalse(root.exists())
        self.assertEqual(self.logs, [])

    def test_actual_roots_require_exact_portable_translation_and_safe_leaf(self):
        lock = Path(self.library.root) / "library.lock"
        lock.touch()
        observation.observe_create_roots(self.artifacts, self.library)
        self.assertEqual(self.phases(), ["create.evidence.roots_confined"])
        os.link(lock, self.temp / "alias")
        observation.observe_create_roots(self.artifacts, self.library)
        observation.observe_create_roots(self.artifacts, object())
        self.translations["special://profile/"] = self.base / "other"
        observation.observe_create_roots(self.artifacts, self.library)
        self.assertEqual(self.phases()[1:], ["create.evidence.roots_unverified"] * 3)

    def test_startup_records_real_no_owner_and_no_journal_branches(self):
        restart = TransactionStore(str(self.profile))
        with patch("resources.lib.build_library.authoritative_build_library", return_value=self.library):
            with patch("resources.lib.startup.get_current_kodi_session_id", return_value="opaque"):
                status = run_startup(store=restart)
            self.assertIs(status.classification, StartupClassification.NO_TRANSACTION)
            store = FrozenInstallStore(self.artifacts.parent)
            self.assertIsNone(run_frozen_install_startup(bm020_status=status, store=store))
        self.assertEqual(self.phases(), [
            "startup.evidence.guard_frozen_owner_absent",
            "startup.evidence.restart_root_confined",
            "startup.evidence.publication_roots_confined",
            "startup.evidence.journal_and_frozen_owner_absent",
            "startup.evidence.frozen_owner_absent_at_return",
        ])

    def test_existing_acknowledged_journal_cannot_emit_absence(self):
        store = FrozenInstallStore(self.artifacts.parent)
        library = Mock(spec=BuildLibrary)
        library.publication_journal.return_value = SimpleNamespace(state="acknowledged")
        library.pending_publication.return_value = None
        library._validate_applied_publication.side_effect = ValueError("sensitive exception text")
        with patch("resources.lib.build_library.authoritative_build_library", return_value=library):
            result = run_frozen_install_startup(bm020_status=None, store=store)
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(self.phases(), [
            "startup.evidence.journal_present", "startup.evidence.publication_roots_unverified",
        ])
        library.pending_publication.assert_not_called()

    def test_journal_present_roots_require_safe_library_lock_and_resolution_directory(self):
        store = FrozenInstallStore(self.artifacts.parent)
        store.lock_path.touch()
        lock = Path(self.library.root) / "library.lock"
        def observe(expected):
            self.assertIs(observation.observe_publication_roots(store, self.library, journal_present=True),
                          expected == "confined")
            self.assertEqual(self.phases()[-1], "startup.evidence.publication_roots_" + expected)

        # The historical absent-journal route does not require library.lock.
        observation.observe_publication_roots(store, self.library)
        self.assertEqual(self.phases(), ["startup.evidence.publication_roots_confined"])
        observe("unverified")
        self.assertFalse(lock.exists())
        lock.touch()
        observe("unverified")
        store.resolutions_dir.mkdir()
        observe("confined")
        safe = self.temp / "unrelated"
        safe.touch()
        lock.unlink()
        for alias in (lambda: lock.symlink_to(safe), lambda: os.link(safe, lock)):
            alias()
            observe("unverified")
            lock.unlink()
        lock.touch()
        store.resolutions_dir.rmdir()
        store.resolutions_dir.symlink_to(self.temp, target_is_directory=True)
        observe("unverified")

    def test_unreadable_journal_emits_no_positive_startup_record(self):
        (Path(self.library.root) / "applied-publication.json").write_text("invalid")
        store = FrozenInstallStore(self.artifacts.parent)
        with patch("resources.lib.build_library.authoritative_build_library", return_value=self.library):
            result = run_frozen_install_startup(bm020_status=None, store=store)
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(self.phases(), [])

    def stopped_state(self):
        (self.artifacts.parent / "install_resolutions").mkdir(exist_ok=True)
        target = SimpleNamespace(bm_data_dir=self.artifacts.parent, require_chain=Mock())
        public = {"trees": {"build-library": {}, "install_resolutions": {},
                            "frozen-artifacts": {"artifacts": {}}}}
        return target, public

    def test_stopped_identity_matches_only_unchanged_public_paths(self):
        target, public = self.stopped_state()
        journal, before, _ = driver.stopped_path_evidence(target, public)
        self.assertEqual(journal, "ABSENT")
        self.assertIsNotNone(before)
        (target.bm_data_dir / "restart_transaction.lock").touch()
        _, after, _ = driver.stopped_path_evidence(target, public)
        self.assertEqual(driver.stopped_path_comparison(before, after), "STABLE_BOUNDARIES")
        artifacts = self.artifacts / "artifacts"
        artifacts.rename(self.temp / "replaced")
        artifacts.mkdir()
        _, changed, _ = driver.stopped_path_evidence(target, public)
        self.assertEqual(driver.stopped_path_comparison(before, changed), "DIFFERENT")

    def test_stopped_acknowledged_journal_is_present_despite_no_pending_flag(self):
        target, public = self.stopped_state()
        (Path(self.library.root) / "applied-publication.json").write_text("opaque")
        public["trees"]["build-library"]["applied-publication.json"] = "digest"
        public["pending_publication_absent"] = True
        journal, paths, canonical = driver.stopped_path_evidence(target, public)
        self.assertEqual(journal, "PRESENT")
        self.assertIsNotNone(paths)
        self.assertEqual(canonical, "UNVERIFIED")
        public["trees"]["build-library"].clear()
        self.assertEqual(driver.stopped_path_evidence(target, public), ("UNVERIFIED", None, "UNVERIFIED"))

    def test_stopped_canonical_evidence_binds_digest_bytes_and_semantics(self):
        target, public = self.stopped_state()
        association = AppliedBuildAssociation("1" * 64, "profile-one", "2" * 64).to_dict()
        public["association"] = association
        tree = public["trees"]["build-library"]
        path = Path(self.library.root) / "applied.json"
        canonical = _encode(association)
        noncanonical = json.dumps(association, indent=2).encode()
        for data, expected in ((canonical, "TRUE"), (noncanonical, "FALSE"),
                               (b"invalid", "UNVERIFIED"),
                               (_encode(dict(association, entry_id="3" * 64)), "UNVERIFIED")):
            with self.subTest(expected=expected, fixture=data[:1]):
                path.write_bytes(data)
                tree[path.name] = driver.bm.sha256_hex(data)
                journal, paths, status = driver.stopped_path_evidence(target, public)
                self.assertEqual((journal, status), ("ABSENT", expected))
                self.assertIsNotNone(paths)
        path.write_bytes(canonical)
        for digest in ("0" * 64, "invalid", None):
            tree[path.name] = digest
            self.assertEqual(driver.stopped_path_evidence(target, public)[2], "UNVERIFIED")
        tree[path.name] = driver.bm.sha256_hex(canonical)
        public["association"] = dict(association, schema_version=True)
        self.assertEqual(driver.stopped_path_evidence(target, public)[2], "UNVERIFIED")
        public["association"] = association
        original_read = driver._read_at
        def replace_during_read(fd, name, limit):
            data = original_read(fd, name, limit)
            path.unlink()
            path.write_bytes(data)
            return data
        with patch.object(driver, "_read_at", side_effect=replace_during_read):
            self.assertEqual(driver.stopped_path_evidence(target, public)[2], "UNVERIFIED")
        path.unlink()
        tree.clear()
        self.assertEqual(driver.stopped_path_evidence(target, public)[2], "UNVERIFIED")

    def test_stopped_aliased_artifact_leaf_is_unverified(self):
        target, public = self.stopped_state()
        safe = self.temp / "unrelated"
        safe.touch()
        artifact = self.artifacts / "artifacts/example.zip"
        public["trees"]["frozen-artifacts"]["artifacts"]["example.zip"] = "digest"
        for alias in (lambda: artifact.symlink_to(safe), lambda: os.link(safe, artifact)):
            with self.subTest(alias=alias):
                alias()
                self.assertEqual(driver.stopped_path_evidence(target, public), ("ABSENT", None, "UNVERIFIED"))
                artifact.unlink()

    def test_canonical_bytes_require_original_single_link_file_and_library_chain(self):
        _, public = self.stopped_state()
        library = Path(self.library.root)
        applied = library / "applied.json"
        association = AppliedBuildAssociation("1" * 64, "profile-one", "2" * 64).to_dict()
        data = _encode(association)
        applied.write_bytes(data)
        public["association"] = association
        public["trees"]["build-library"][applied.name] = driver.bm.sha256_hex(data)
        directory_chain = driver._directory_chain
        with directory_chain(library) as (_, chain):
            pass

        def identity():
            info = applied.stat()
            return (info.st_dev, info.st_ino), info.st_ctime_ns

        original = identity()
        self.assertEqual(driver._applied_canonical(library, chain, public, original), "TRUE")
        self.assertEqual(driver._applied_canonical(library, chain, public,
                                                   (original[0], original[1] - 1)), "UNVERIFIED")
        applied.rename(self.temp / "previous-applied")
        applied.write_bytes(data)
        current = identity()
        self.assertNotEqual(current[0], original[0])
        self.assertEqual(driver._applied_canonical(library, chain, public, original), "UNVERIFIED")
        self.assertEqual(driver._applied_canonical(library, chain[:-1], public, current), "UNVERIFIED")

        opened_chains = []

        @contextmanager
        def replace_chain_on_recheck(path):
            with directory_chain(path) as (fd, observed):
                opened_chains.append(observed)
                yield fd, observed if len(opened_chains) == 1 else observed[:-1]

        with patch.object(driver, "_directory_chain", replace_chain_on_recheck):
            self.assertEqual(driver._applied_canonical(library, chain, public, current), "UNVERIFIED")
        self.assertEqual(opened_chains, [chain, chain])
        os.link(applied, self.temp / "applied-hardlink")
        self.assertEqual(driver._applied_canonical(library, chain, public, identity()), "UNVERIFIED")

    def test_stopped_observation_error_and_count_limit_are_unverified(self):
        target, public = self.stopped_state()
        target.require_chain.side_effect = OSError("sensitive exception text")
        self.assertEqual(driver.stopped_path_evidence(target, public), ("UNVERIFIED", None, "UNVERIFIED"))
        (self.artifacts / "artifacts/example.zip").touch()
        with observation._directory_chain(self.artifacts / "artifacts") as (fd, chain):
            with self.assertRaises(ValueError):
                driver._public_path_identities(fd, {"example.zip": "digest"}, chain[-1][0], [0])
