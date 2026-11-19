"""Bounded metadata observations for the portable A15 evidence run."""
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from resources.lib.failure_diagnostics import emit


_PORTABLE_HOME = Path("/Applications/Kodi Build Manager Test.app/Contents/Resources/Kodi/portable_data")
_BM_DATA = Path("addon_data/script.build.manager")


def _local_absolute(value):
    path = Path(value)
    if path.anchor != "/" or ".." in path.parts or len(path.parts) > 64:
        raise ValueError("unverified directory")
    return path


@contextmanager
def _directory_chain(path):
    """Return the leaf descriptor and identities along a no-follow directory walk."""
    path = _local_absolute(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        chain = [_identity(os.fstat(fd))]
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            chain.append(_identity(os.fstat(fd)))
        yield fd, tuple(chain)
    finally:
        os.close(fd)


def _identity(info):
    return info.st_dev, info.st_ino


def _portable_profile():
    import xbmcvfs
    profile = _PORTABLE_HOME / "userdata"
    if (Path(xbmcvfs.translatePath("special://home/")) != _PORTABLE_HOME or
            Path(xbmcvfs.translatePath("special://profile/")) != profile or
            Path(xbmcvfs.translatePath("special://home/addons")) != _PORTABLE_HOME / "addons"):
        raise ValueError("unverified portable profile")
    return profile


def _temporary_parent(directory):
    parent = _local_absolute(directory).parent
    # Accept the macOS system aliases explicitly. Other links are refused by
    # the descriptor walk, even when they happen to resolve outside the profile.
    if len(parent.parts) > 1 and parent.parts[1] in ("var", "tmp"):
        alias = Path("/") / parent.parts[1]
        if alias.is_symlink():
            expected = Path("/private") / alias.name
            if os.readlink(alias) not in (str(expected), str(expected.relative_to("/"))):
                raise ValueError("unverified system temporary alias")
            return Path("/private").joinpath(*parent.parts[1:])
    return parent


def _staging_snapshot(directory, root):
    import xbmcvfs
    profile = _portable_profile()
    original = _local_absolute(directory)
    # TemporaryDirectory has already made its selection. Read Python's cached
    # answer without calling gettempdir(), which could probe the filesystem.
    if _local_absolute(os.fsdecode(tempfile.tempdir)) != original.parent:
        raise ValueError("unverified Python temporary location")
    # The platform may spell a system temp ancestor as /var or /tmp. Resolve
    # that parent, then inspect its real chain and the newly created leaf.
    parent = _temporary_parent(original)
    if root != parent / original.name or not original.name.startswith("bm-create-public-"):
        raise ValueError("unverified staging root")
    with _directory_chain(parent) as (fd, chain):
        stage = os.stat(original.name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISDIR(stage.st_mode) or stage.st_uid != os.geteuid():
            raise ValueError("unverified staging directory")
    if _temporary_parent(original) != parent:
        raise ValueError("unverified temporary parent")
    protected = (_PORTABLE_HOME, profile, _PORTABLE_HOME / "addons",
                 _local_absolute(xbmcvfs.translatePath("special://xbmc/addons")))
    protected_chains = []
    for path in protected:
        with _directory_chain(path) as (_, protected_chain):
            if chain[-1] in protected_chain or protected_chain[-1] in chain:
                raise ValueError("unverified temporary confinement")
            protected_chains.append(protected_chain)
    return parent, chain, _identity(stage), tuple(protected_chains)


def _temp_candidates():
    # CPython's candidate builder only reads names. Never call its chooser
    # here: selecting a default is itself a write-and-unlink probe.
    try:
        candidates = tempfile._candidate_tempdir_list()
        if type(candidates) is list and 0 < len(candidates) <= 8:
            return tuple(os.path.abspath(path) for path in candidates)
    except Exception:
        pass
    return ()


@contextmanager
def registration_staging():
    """Observe the existing temporary directory lifecycle without deciding it."""
    before = None
    stable_at_exit = False
    body_error = None
    cold_temp_selection = tempfile.tempdir is None
    candidates = _temp_candidates() if cold_temp_selection else ()
    try:
        with tempfile.TemporaryDirectory(prefix="bm-create-public-") as directory:
            root = Path(directory).resolve()
            try:
                before = _staging_snapshot(directory, root)
                phase = "create.evidence.staging_confined_before"
                if cold_temp_selection:
                    phase = "create.evidence.staging_confined_cold_before"
                    chosen = str(Path(directory).parent)
                    if (candidates and candidates == _temp_candidates()
                            and candidates[0] == chosen and candidates.count(chosen) == 1):
                        phase = "create.evidence.staging_confined_first_candidate_before"
            except Exception:
                before = None
            else:
                emit(phase)
            try:
                yield root
            except BaseException as exc:
                body_error = exc
                raise
            finally:
                try:
                    stable_at_exit = before is not None and _staging_snapshot(directory, root) == before
                except Exception:
                    pass
    except BaseException as exc:
        if exc is not body_error:
            # A staging setup/cleanup fault cannot be a positive observation,
            # even if it left no directory behind.
            stable_at_exit = False
        raise
    finally:
        cleaned = False
        if stable_at_exit:
            try:
                parent, expected_chain, _, _ = before
                if _temporary_parent(directory) == parent:
                    with _directory_chain(parent) as (fd, chain):
                        if chain == expected_chain:
                            try:
                                os.stat(root.name, dir_fd=fd, follow_symlinks=False)
                            except FileNotFoundError:
                                cleaned = True
            except Exception:
                pass
        emit("create.evidence.staging_cleaned" if cleaned else "create.evidence.staging_unverified")


def _check_roots(profile, paths):
    for relative, actual, lock in paths:
        if Path(actual) != profile / _BM_DATA / relative:
            raise ValueError("unverified Build Manager directory")
        with _directory_chain(actual) as (fd, _):
            if lock is not None:
                info = os.stat(lock, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("unverified Build Manager lock")


def observe_create_roots(artifact_root, library):
    try:
        _check_roots(_portable_profile(), (
            ("frozen-artifacts/artifacts", artifact_root / "artifacts", None),
            ("build-library", library.root, "library.lock"),
        ))
    except Exception:
        emit("create.evidence.roots_unverified")
    else:
        emit("create.evidence.roots_confined")


def observe_restart_root(store):
    try:
        _check_roots(_portable_profile(), (("", store.directory, "restart_transaction.lock"),))
    except Exception:
        emit("startup.evidence.restart_root_unverified")
    else:
        emit("startup.evidence.restart_root_confined")


def observe_publication_roots(store, library):
    try:
        _check_roots(_portable_profile(), (
            ("", store.root, "frozen_install_transaction.lock"),
            ("build-library", library.root, None),
        ))
    except Exception:
        emit("startup.evidence.publication_roots_unverified")
    else:
        emit("startup.evidence.publication_roots_confined")
