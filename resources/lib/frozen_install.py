"""BM-022 frozen-build installation and transaction lifecycle.

The installer consumes only a complete BM-021B manifest and immutable
content-addressed artifacts.  It reuses the project's established validated
staged-package installation boundary, never asks Kodi to resolve a newer
repository version, and fails closed when an existing installation is not the
exact requested version.

The durable transaction owns the global updater quarantine from the first
mutation until explicit final release or recovery.  It is intentionally
separate from BM-020's restart transaction; the startup precondition lets the
frozen transaction reassert ``NEVER_CHECK`` before BM-020 may resume.
"""

from __future__ import annotations

import datetime as _datetime
import errno
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from resources.lib.artifacts import ArtifactStore, ArtifactValidationError, validate_addon_zip
from resources.lib.build_manager import ReconcileRequest
from resources.lib.frozen import (
    AddonCaptureNode,
    CaptureError,
    CaptureStatus,
    FrozenBuildManifest,
)
from resources.lib.repository import _extract_zip_to_directory
from resources.lib.update_guard import (
    AddonUpdatePolicy,
    AddonUpdateGuard,
    KodiJsonRpcUpdatePolicyBackend,
    UpdateGuardError,
    UpdatePolicyBackend,
)


class FrozenInstallError(Exception):
    """Base class for safe frozen-install failures."""

    code = "FROZEN_INSTALL_ERROR"


class FrozenInstallValidationError(FrozenInstallError):
    code = "FROZEN_MANIFEST_INVALID"


class FrozenInstallPersistenceError(FrozenInstallError):
    code = "FROZEN_TRANSACTION_PERSISTENCE_FAILED"


class FrozenInstallStateConflict(FrozenInstallError):
    code = "FROZEN_TRANSACTION_STATE_CONFLICT"


class FrozenInstallPhase(str, Enum):
    PREPARING = "preparing"
    INSTALLING_SOFTWARE = "installing_software"
    CONFIGURING = "configuring"
    AWAITING_RESTART = "awaiting_restart"
    RESUMING = "resuming"
    VALIDATING = "validating"
    NEEDS_ATTENTION = "needs_attention"
    COMPLETE = "complete"


_TRANSACTION_SCHEMA = 1
_TRANSACTION_FILENAME = "frozen_install_transaction.json"
_LOCK_FILENAME = "frozen_install_transaction.lock"
_MAX_CODE = 96
_MAX_MESSAGE = 512
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds")


def _bounded(value: object, limit: int, default: str) -> str:
    text = str(value).strip()
    return (text or default)[:limit]


def _valid_uuid(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise FrozenInstallValidationError(f"{field} must be a UUID")
    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise FrozenInstallValidationError(f"{field} must be a UUID") from exc
    return value


def _valid_fingerprint(value: object) -> str:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value):
        raise FrozenInstallValidationError("manifest fingerprint is invalid")
    return value


@dataclass(frozen=True)
class FrozenInstallTransaction:
    """Secret-safe durable state for one frozen installation."""

    transaction_id: str
    build_id: str
    manifest_path: str
    device_profile_id: str
    manifest_fingerprint: str
    phase: FrozenInstallPhase
    originating_kodi_session_id: str
    original_update_policy: AddonUpdatePolicy
    updater_guard_required: bool = True
    restart_transaction_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    status_code: str = ""
    status_message: str = ""

    def __post_init__(self) -> None:
        _valid_uuid(self.transaction_id, "transaction_id")
        _valid_uuid(self.originating_kodi_session_id, "originating_kodi_session_id")
        if not isinstance(self.build_id, str) or not self.build_id:
            raise FrozenInstallValidationError("build_id must be non-empty")
        if not isinstance(self.manifest_path, str) or not self.manifest_path:
            raise FrozenInstallValidationError("manifest_path must be non-empty")
        if not isinstance(self.device_profile_id, str) or not self.device_profile_id:
            raise FrozenInstallValidationError("device_profile_id must be non-empty")
        _valid_fingerprint(self.manifest_fingerprint)
        if not isinstance(self.phase, FrozenInstallPhase):
            raise FrozenInstallValidationError("invalid frozen-install phase")
        if not isinstance(self.original_update_policy, AddonUpdatePolicy):
            raise FrozenInstallValidationError("invalid original updater policy")
        if not isinstance(self.updater_guard_required, bool):
            raise FrozenInstallValidationError("updater_guard_required must be boolean")
        if self.restart_transaction_id:
            _valid_uuid(self.restart_transaction_id, "restart_transaction_id")
        for field in ("created_at", "updated_at"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or len(value) > 64:
                raise FrozenInstallValidationError(f"{field} is invalid")
        if not isinstance(self.status_code, str) or len(self.status_code) > _MAX_CODE:
            raise FrozenInstallValidationError("status_code is invalid")
        if not isinstance(self.status_message, str) or len(self.status_message) > _MAX_MESSAGE:
            raise FrozenInstallValidationError("status_message is invalid")

    def to_dict(self) -> dict:
        return {
            "schema_version": _TRANSACTION_SCHEMA,
            "transaction_id": self.transaction_id,
            "build_id": self.build_id,
            "manifest_path": self.manifest_path,
            "device_profile_id": self.device_profile_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "phase": self.phase.value,
            "originating_kodi_session_id": self.originating_kodi_session_id,
            "original_update_policy": int(self.original_update_policy),
            "updater_guard_required": self.updater_guard_required,
            "restart_transaction_id": self.restart_transaction_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status_code": self.status_code,
            "status_message": self.status_message,
        }

    @classmethod
    def from_dict(cls, value: object) -> "FrozenInstallTransaction":
        if not isinstance(value, dict):
            raise FrozenInstallPersistenceError("frozen transaction root is not an object")
        required = {
            "schema_version", "transaction_id", "build_id", "manifest_path",
            "device_profile_id", "manifest_fingerprint", "phase",
            "originating_kodi_session_id", "original_update_policy",
            "updater_guard_required", "restart_transaction_id", "created_at",
            "updated_at", "status_code", "status_message",
        }
        if set(value) != required:
            raise FrozenInstallPersistenceError("frozen transaction fields are unsupported")
        if value["schema_version"] != _TRANSACTION_SCHEMA:
            raise FrozenInstallPersistenceError("unsupported frozen transaction schema")
        try:
            return cls(
                transaction_id=value["transaction_id"],
                build_id=value["build_id"],
                manifest_path=value["manifest_path"],
                device_profile_id=value["device_profile_id"],
                manifest_fingerprint=value["manifest_fingerprint"],
                phase=FrozenInstallPhase(value["phase"]),
                originating_kodi_session_id=value["originating_kodi_session_id"],
                original_update_policy=AddonUpdatePolicy(value["original_update_policy"]),
                updater_guard_required=value["updater_guard_required"],
                restart_transaction_id=value["restart_transaction_id"],
                created_at=value["created_at"],
                updated_at=value["updated_at"],
                status_code=value["status_code"],
                status_message=value["status_message"],
            )
        except (KeyError, TypeError, ValueError, FrozenInstallError) as exc:
            if isinstance(exc, FrozenInstallError):
                raise
            raise FrozenInstallPersistenceError("frozen transaction contains invalid fields") from exc

    def with_phase(
        self,
        phase: FrozenInstallPhase,
        *,
        status_code: str = "",
        status_message: str = "",
        restart_transaction_id: Optional[str] = None,
    ) -> "FrozenInstallTransaction":
        return replace(
            self,
            phase=phase,
            status_code=_bounded(status_code, _MAX_CODE, "") if status_code else "",
            status_message=_bounded(status_message, _MAX_MESSAGE, "") if status_message else "",
            restart_transaction_id=(
                self.restart_transaction_id
                if restart_transaction_id is None else restart_transaction_id
            ),
            updated_at=_utc_now(),
        )


class FrozenInstallLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self._handle = self.path.open("a+")
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.release()
            raise FrozenInstallStateConflict("frozen install transaction is busy") from exc
        except OSError as exc:
            self.release()
            raise FrozenInstallPersistenceError("could not acquire frozen transaction lock") from exc

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self._handle.close()
        finally:
            self._handle = None

    def __enter__(self) -> "FrozenInstallLock":
        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()


class FrozenInstallStore:
    """Atomic, profile-local persistence for frozen-install state."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else default_frozen_install_root()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @property
    def transaction_path(self) -> Path:
        return self.root / _TRANSACTION_FILENAME

    @property
    def lock_path(self) -> Path:
        return self.root / _LOCK_FILENAME

    def locked(self) -> FrozenInstallLock:
        return FrozenInstallLock(self.lock_path)

    def inspect(self) -> Optional[FrozenInstallTransaction]:
        with self.locked():
            if not self.transaction_path.exists():
                return None
            try:
                data = json.loads(self.transaction_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FrozenInstallPersistenceError("could not read frozen transaction") from exc
            return FrozenInstallTransaction.from_dict(data)

    def create(self, transaction: FrozenInstallTransaction) -> FrozenInstallTransaction:
        with self.locked():
            if self.transaction_path.exists():
                raise FrozenInstallStateConflict("a frozen install transaction is already active")
            self._write_unlocked(transaction)
            return transaction

    def transition_expected(
        self,
        *,
        transaction_id: str,
        expected_phase: FrozenInstallPhase,
        new_phase: FrozenInstallPhase,
        status_code: str = "",
        status_message: str = "",
        restart_transaction_id: Optional[str] = None,
    ) -> FrozenInstallTransaction:
        with self.locked():
            current = self._read_unlocked()
            if current is None or current.transaction_id != transaction_id:
                raise FrozenInstallStateConflict("frozen transaction identity changed")
            if current.phase is not expected_phase:
                raise FrozenInstallStateConflict("frozen transaction phase changed")
            updated = current.with_phase(
                new_phase,
                status_code=status_code,
                status_message=status_message,
                restart_transaction_id=restart_transaction_id,
            )
            self._write_unlocked(updated)
            return updated

    def clear_expected(
        self, *, transaction_id: str, expected_phase: FrozenInstallPhase
    ) -> bool:
        with self.locked():
            current = self._read_unlocked()
            if current is None:
                return False
            if current.transaction_id != transaction_id or current.phase is not expected_phase:
                raise FrozenInstallStateConflict("frozen transaction changed before clear")
            try:
                self.transaction_path.unlink()
                self._fsync_directory()
            except OSError as exc:
                raise FrozenInstallPersistenceError("could not clear frozen transaction") from exc
            return True

    def clear(self) -> bool:
        with self.locked():
            try:
                self.transaction_path.unlink()
                self._fsync_directory()
                return True
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise FrozenInstallPersistenceError("could not clear frozen transaction") from exc

    def _read_unlocked(self) -> Optional[FrozenInstallTransaction]:
        if not self.transaction_path.exists():
            return None
        try:
            return FrozenInstallTransaction.from_dict(
                json.loads(self.transaction_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrozenInstallPersistenceError("could not read frozen transaction") from exc

    def _write_unlocked(self, transaction: FrozenInstallTransaction) -> None:
        data = (json.dumps(transaction.to_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode()
        staged: Optional[Path] = None
        try:
            fd, name = tempfile.mkstemp(prefix=".frozen-install.", suffix=".tmp", dir=self.root)
            staged = Path(name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, self.transaction_path)
            staged = None
            self._fsync_directory()
            self._read_unlocked()
        except FrozenInstallError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise FrozenInstallPersistenceError("atomic frozen transaction write failed") from exc
        finally:
            if staged is not None:
                try:
                    staged.unlink()
                except OSError:
                    pass

    def _fsync_directory(self) -> None:
        try:
            fd = os.open(self.root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
        finally:
            os.close(fd)


def default_frozen_install_root() -> Path:
    try:
        import xbmcvfs
        return Path(xbmcvfs.translatePath("special://profile/addon_data/script.build.manager"))
    except (ImportError, AttributeError, RuntimeError):
        return Path("/tmp/script.build.manager-frozen-install")


@dataclass(frozen=True)
class FrozenManifestPlan:
    manifest: FrozenBuildManifest
    nodes: Mapping[str, AddonCaptureNode]
    install_order: Tuple[AddonCaptureNode, ...]


def validate_frozen_manifest(
    manifest: FrozenBuildManifest, store: ArtifactStore
) -> FrozenManifestPlan:
    """Validate completeness, artifact identity, edges, and deterministic order."""
    if not isinstance(manifest, FrozenBuildManifest):
        raise FrozenInstallValidationError("frozen installation requires a typed manifest")
    if manifest.schema_version != 1:
        raise FrozenInstallValidationError("unsupported frozen manifest schema")
    if manifest.capture_status is not CaptureStatus.COMPLETE:
        raise FrozenInstallValidationError("incomplete frozen capture is not installable")
    nodes: Dict[str, AddonCaptureNode] = {}
    for node in manifest.addons:
        if node.addon_id in nodes:
            raise FrozenInstallValidationError("frozen manifest contains duplicate add-on IDs")
        nodes[node.addon_id] = node
        if node.system:
            if node.artifact is not None:
                raise FrozenInstallValidationError("system dependency has an artifact")
            continue
        if node.status is not CaptureStatus.COMPLETE or node.artifact is None:
            raise FrozenInstallValidationError(
                f"required artifact is incomplete for {node.addon_id} {node.version}"
            )
        try:
            metadata = store.get_metadata(node.artifact.sha256)
            data = store.read_bytes(node.artifact.sha256)
            if (
                metadata.sha256 != node.artifact.sha256
                or metadata.addon_id != node.addon_id
                or metadata.version != node.version
                or metadata.size != node.artifact.size
                or len(data) != node.artifact.size
                or hashlib.sha256(data).hexdigest() != node.artifact.sha256
            ):
                raise FrozenInstallValidationError(
                    f"artifact identity mismatch for {node.addon_id} {node.version}"
                )
            validate_addon_zip(
                data,
                expected_addon_id=node.addon_id,
                expected_version=node.version,
            )
        except (ArtifactValidationError, FrozenInstallError) as exc:
            if isinstance(exc, FrozenInstallError):
                raise
            raise FrozenInstallValidationError(
                f"artifact validation failed for {node.addon_id} {node.version}"
            ) from exc
        except Exception as exc:
            raise FrozenInstallValidationError(
                f"artifact unavailable for {node.addon_id} {node.version}"
            ) from exc

    edges: Dict[str, set] = {addon_id: set() for addon_id, node in nodes.items() if not node.system}
    reverse: Dict[str, set] = {addon_id: set() for addon_id in edges}
    for node in nodes.values():
        if node.system:
            continue
        for edge in node.dependency_edges:
            if edge.addon_id not in nodes:
                if edge.optional:
                    continue
                raise FrozenInstallValidationError(
                    f"required dependency {edge.addon_id} is absent from frozen manifest"
                )
            if nodes[edge.addon_id].system:
                continue
            edges[node.addon_id].add(edge.addon_id)
            reverse[edge.addon_id].add(node.addon_id)

    ready = sorted(addon_id for addon_id, deps in edges.items() if not deps)
    order = []
    while ready:
        addon_id = ready.pop(0)
        order.append(nodes[addon_id])
        for dependent in sorted(reverse[addon_id]):
            edges[dependent].discard(addon_id)
            if not edges[dependent]:
                ready.append(dependent)
                ready.sort()
    if len(order) != len(edges):
        raise FrozenInstallValidationError("frozen dependency graph contains a cycle")
    return FrozenManifestPlan(manifest, nodes, tuple(order))


@dataclass(frozen=True)
class FrozenInstalledAddon:
    addon_id: str
    version: str
    enabled: bool
    broken: bool = False


class FrozenArtifactBackend:
    """Exact-artifact install and state interface."""

    def get_addon_details(self, addon_id: str) -> Optional[FrozenInstalledAddon]:
        raise NotImplementedError

    def install_exact(self, addon_id: str, version: str, zip_bytes: bytes) -> FrozenInstalledAddon:
        raise NotImplementedError

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> FrozenInstalledAddon:
        raise NotImplementedError


class InMemoryFrozenArtifactBackend(FrozenArtifactBackend):
    """Deterministic backend for transaction tests and fixture design."""

    def __init__(self, installed: Optional[Mapping[str, FrozenInstalledAddon]] = None):
        self.installed = dict(installed or {})
        self.install_calls = []
        self.enable_calls = []
        self.artifacts = {}

    def get_addon_details(self, addon_id: str) -> Optional[FrozenInstalledAddon]:
        return self.installed.get(addon_id)

    def install_exact(self, addon_id: str, version: str, zip_bytes: bytes) -> FrozenInstalledAddon:
        current = self.installed.get(addon_id)
        if current is not None:
            if current.version != version:
                raise FrozenInstallError(
                    f"exact replacement/downgrade is unsupported for {addon_id}"
                )
            if current.broken:
                raise FrozenInstallError(f"existing exact add-on is broken: {addon_id}")
            return current
        self.install_calls.append(addon_id)
        self.artifacts[addon_id] = bytes(zip_bytes)
        result = FrozenInstalledAddon(addon_id, version, False, False)
        self.installed[addon_id] = result
        return result

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> FrozenInstalledAddon:
        current = self.installed.get(addon_id)
        if current is None:
            raise FrozenInstallError(f"cannot set state for missing add-on {addon_id}")
        self.enable_calls.append((addon_id, enabled))
        result = FrozenInstalledAddon(addon_id, current.version, enabled, current.broken)
        self.installed[addon_id] = result
        return result


class KodiRuntimeFrozenArtifactBackend(FrozenArtifactBackend):
    """Kodi runtime adapter using the established validated staged install path."""

    _WAIT_TIMEOUT = 60.0
    _WAIT_INTERVAL = 0.5

    def __init__(self):
        self.install_order = []

    def _xbmc(self):
        try:
            import xbmc
            return xbmc
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise FrozenInstallError("Kodi runtime module is unavailable") from exc

    def _addons_dir(self) -> Path:
        try:
            import xbmcvfs
            return Path(xbmcvfs.translatePath("special://home/addons"))
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise FrozenInstallError("Kodi VFS module is unavailable") from exc

    def _rpc(self, method: str, params: dict) -> dict:
        response = json.loads(self._xbmc().executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params, "id": 1,
        })))
        if not isinstance(response, dict):
            raise FrozenInstallError(f"{method} returned malformed JSON-RPC data")
        return response

    def get_addon_details(self, addon_id: str) -> Optional[FrozenInstalledAddon]:
        response = self._rpc(
            "Addons.GetAddonDetails",
            {"addonid": addon_id, "properties": ["enabled", "version", "broken"]},
        )
        error = response.get("error")
        if isinstance(error, dict) and error.get("code") == -32602:
            return None
        if error is not None:
            raise FrozenInstallError("Kodi refused add-on inspection")
        addon = response.get("result", {}).get("addon", {})
        if not isinstance(addon, dict) or addon.get("addonid") != addon_id:
            return None
        if not isinstance(addon.get("enabled"), bool) or not isinstance(addon.get("version"), str):
            raise FrozenInstallError("Kodi returned malformed add-on state")
        return FrozenInstalledAddon(
            addon_id=addon_id,
            version=addon["version"],
            enabled=addon["enabled"],
            broken=addon.get("broken") is True,
        )

    def install_exact(self, addon_id: str, version: str, zip_bytes: bytes) -> FrozenInstalledAddon:
        self.install_order.append(addon_id)
        current = self.get_addon_details(addon_id)
        if current is not None:
            if current.version != version:
                raise FrozenInstallError(
                    f"exact replacement/downgrade is unsupported for {addon_id}"
                )
            if current.broken:
                raise FrozenInstallError(f"existing exact add-on is broken: {addon_id}")
            return current
        addons_dir = self._addons_dir()
        target = addons_dir / addon_id
        if target.exists():
            raise FrozenInstallError(
                f"unregistered add-on directory already exists for {addon_id}; refusing overwrite"
            )
        staging = Path(tempfile.mkdtemp(prefix=".bm022-", dir=addons_dir))
        try:
            _extract_zip_to_directory(zip_bytes, addon_id, staging)
            if not any(path.is_file() for path in staging.rglob("*")):
                raise FrozenInstallError(f"exact artifact extracted no usable files for {addon_id}")
            os.rename(staging, target)
            staging = None  # type: ignore[assignment]
            self._xbmc().executebuiltin("UpdateLocalAddons")
        except FrozenInstallError:
            raise
        except Exception as exc:
            raise FrozenInstallError(f"exact artifact installation failed for {addon_id}") from exc
        finally:
            if staging is not None and staging.exists():
                import shutil
                shutil.rmtree(staging, ignore_errors=True)
        return self._wait_for_exact(addon_id, version)

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> FrozenInstalledAddon:
        response = self._rpc(
            "Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": bool(enabled)}
        )
        if response.get("error") is not None or response.get("result", {}).get("success") is False:
            raise FrozenInstallError(f"Kodi refused enabled-state change for {addon_id}")
        current = self._wait_for_details(addon_id)
        if current.enabled is not enabled:
            raise FrozenInstallError(f"enabled-state verification failed for {addon_id}")
        return current

    def _wait_for_details(self, addon_id: str) -> FrozenInstalledAddon:
        deadline = time.monotonic() + self._WAIT_TIMEOUT
        while time.monotonic() < deadline:
            current = self.get_addon_details(addon_id)
            if current is not None:
                return current
            time.sleep(self._WAIT_INTERVAL)
        raise FrozenInstallError(f"Kodi did not register exact add-on {addon_id}")

    def _wait_for_exact(self, addon_id: str, version: str) -> FrozenInstalledAddon:
        current = self._wait_for_details(addon_id)
        if current.version != version or current.broken:
            raise FrozenInstallError(f"Kodi registered the wrong or broken version for {addon_id}")
        return current


@dataclass(frozen=True)
class FrozenInstallResult:
    outcome: str
    transaction: Optional[FrozenInstallTransaction] = None
    message: str = ""
    code: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome == "complete"


def _default_manifest_loader(path: str) -> FrozenBuildManifest:
    raw_path = path
    try:
        import xbmcvfs
        if raw_path.startswith("special://"):
            raw_path = xbmcvfs.translatePath(raw_path)
    except (ImportError, AttributeError, RuntimeError):
        pass
    try:
        return FrozenBuildManifest.from_json(Path(raw_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, CaptureError) as exc:
        raise FrozenInstallValidationError("could not load frozen manifest") from exc


class FrozenInstallCoordinator:
    """Coordinate exact software, existing configuration, restart, and release."""

    def __init__(
        self,
        *,
        store: FrozenInstallStore,
        artifact_store: ArtifactStore,
        policy_backend: UpdatePolicyBackend,
        installer: FrozenArtifactBackend,
        manifest_loader: Callable[[str], FrozenBuildManifest] = _default_manifest_loader,
        session_id_provider: Optional[Callable[[], str]] = None,
        configuration_runner: Optional[Callable[[ReconcileRequest], object]] = None,
        final_validator: Optional[Callable[[FrozenManifestPlan], bool]] = None,
    ):
        self.store = store
        self.artifact_store = artifact_store
        self.policy_backend = policy_backend
        self.installer = installer
        self.manifest_loader = manifest_loader
        self.session_id_provider = session_id_provider or _default_session_id
        self.configuration_runner = configuration_runner
        self.final_validator = final_validator

    def install(
        self,
        manifest: FrozenBuildManifest,
        *,
        manifest_path: str,
        device_profile_id: str,
        configuration_manifest_path: str = "",
    ) -> FrozenInstallResult:
        try:
            plan = validate_frozen_manifest(manifest, self.artifact_store)
            session_id = _valid_uuid(self.session_id_provider(), "current_session_id")
        except (FrozenInstallError, CaptureError, ValueError) as exc:
            return FrozenInstallResult("failed", code=getattr(exc, "code", "FROZEN_MANIFEST_INVALID"), message="frozen manifest validation failed")
        active = self._safe_inspect()
        if active is not None:
            if active.manifest_fingerprint == plan.manifest.fingerprint():
                return FrozenInstallResult(
                    "needs_attention" if active.phase is FrozenInstallPhase.NEEDS_ATTENTION else "awaiting_restart",
                    transaction=active,
                    code=active.status_code or "FROZEN_INSTALL_ACTIVE",
                    message="an equivalent frozen install transaction is already active",
                )
            return FrozenInstallResult("failed", transaction=active, code="ACTIVE_TRANSACTION_CONFLICT", message="another frozen install transaction is active")
        try:
            original = AddonUpdatePolicy(self.policy_backend.get_policy())
            transaction = FrozenInstallTransaction(
                transaction_id=str(uuid.uuid4()),
                build_id=plan.manifest.build_id,
                manifest_path=manifest_path,
                device_profile_id=device_profile_id,
                manifest_fingerprint=plan.manifest.fingerprint(),
                phase=FrozenInstallPhase.PREPARING,
                originating_kodi_session_id=session_id,
                original_update_policy=original,
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
            self.store.create(transaction)
        except Exception as exc:
            return FrozenInstallResult(
                "failed",
                code=getattr(exc, "code", "FROZEN_TRANSACTION_CREATE_FAILED"),
                message=_bounded(
                    "frozen install transaction could not be created "
                    f"({type(exc).__name__})",
                    _MAX_MESSAGE,
                    "transaction creation failed",
                ),
            )
        guard = AddonUpdateGuard(self.policy_backend)
        try:
            guard.engage_with_original(original)
            transaction = self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.PREPARING,
                new_phase=FrozenInstallPhase.INSTALLING_SOFTWARE,
            )
            for node in plan.install_order:
                data = self.artifact_store.read_bytes(node.artifact.sha256)  # type: ignore[union-attr]
                self.installer.install_exact(node.addon_id, node.version, data)
            transaction = self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.INSTALLING_SOFTWARE,
                new_phase=FrozenInstallPhase.CONFIGURING,
            )
            if self.configuration_runner is not None:
                request_path = configuration_manifest_path or manifest_path
                result = self.configuration_runner(ReconcileRequest(request_path, device_profile_id))
                transaction, awaiting = self._handle_configuration_result(transaction, result)
                if awaiting is not None:
                    return awaiting
            return self._finalize(transaction, plan, guard)
        except Exception as exc:
            return self._attention(
                transaction,
                getattr(exc, "code", "FROZEN_INSTALL_FAILED"),
                _bounded(
                    "frozen installation failed "
                    f"({type(exc).__name__}): {exc}",
                    _MAX_MESSAGE,
                    "frozen installation failed",
                ),
            )

    def resume_after_restart(self, *, current_session_id: Optional[str] = None) -> FrozenInstallResult:
        transaction = self._safe_inspect()
        if transaction is None:
            return FrozenInstallResult("failed", code="FROZEN_TRANSACTION_MISSING", message="no frozen install transaction is active")
        if transaction.phase is not FrozenInstallPhase.AWAITING_RESTART:
            return FrozenInstallResult("needs_attention", transaction=transaction, code="FROZEN_TRANSACTION_NOT_AWAITING", message="frozen transaction is not awaiting restart")
        try:
            session = _valid_uuid(current_session_id or self.session_id_provider(), "current_session_id")
            if session == transaction.originating_kodi_session_id:
                return FrozenInstallResult("awaiting_restart", transaction=transaction, code="SAME_SESSION", message="Kodi has not crossed the restart boundary")
            guard = AddonUpdateGuard(self.policy_backend)
            guard.reassert_required()
            manifest = self.manifest_loader(transaction.manifest_path)
            plan = validate_frozen_manifest(manifest, self.artifact_store)
            if plan.manifest.fingerprint() != transaction.manifest_fingerprint:
                return self._attention(transaction, "FROZEN_FINGERPRINT_MISMATCH", "frozen manifest changed before resume")
            transaction = self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.AWAITING_RESTART,
                new_phase=FrozenInstallPhase.RESUMING,
            )
            return self._finalize(transaction, plan, guard)
        except Exception as exc:
            return self._attention(
                transaction,
                getattr(exc, "code", "FROZEN_RESUME_FAILED"),
                _bounded(
                    "frozen installation resume failed "
                    f"({type(exc).__name__}): {exc}",
                    _MAX_MESSAGE,
                    "frozen installation resume failed",
                ),
            )

    def abandon(self, *, acknowledge_restore_failure: bool = False) -> FrozenInstallResult:
        transaction = self._safe_inspect()
        if transaction is None:
            return FrozenInstallResult("complete", message="no frozen transaction is active")
        guard = AddonUpdateGuard(self.policy_backend)
        try:
            guard.restore_original(transaction.original_update_policy)
        except Exception:
            if not acknowledge_restore_failure:
                return self._attention(transaction, "UPDATE_POLICY_RESTORE_FAILED", "explicit abandon could not restore updater policy")
        try:
            self.store.clear_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=transaction.phase,
            )
        except Exception:
            return self._attention(transaction, "FROZEN_TRANSACTION_CLEAR_FAILED", "explicit abandon could not clear transaction")
        return FrozenInstallResult("complete", message="frozen installation explicitly abandoned; software was not rolled back")

    def _handle_configuration_result(self, transaction, result):
        outcome = getattr(getattr(result, "outcome", None), "value", getattr(result, "outcome", ""))
        if outcome in ("manual_restart_required", "awaiting_restart"):
            restart_tx = getattr(result, "transaction", None)
            restart_id = getattr(restart_tx, "transaction_id", "")
            updated = self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.CONFIGURING,
                new_phase=FrozenInstallPhase.AWAITING_RESTART,
                restart_transaction_id=restart_id,
            )
            return updated, FrozenInstallResult("awaiting_restart", transaction=updated, code="AWAITING_RESTART", message="restart Kodi completely to continue frozen installation")
        if outcome in ("failed", "needs_attention"):
            raise FrozenInstallError("configuration/restart handoff failed")
        if hasattr(result, "success") and not result.success:
            raise FrozenInstallError("configuration reconciliation failed")
        return transaction, None

    def _finalize(self, transaction, plan, guard) -> FrozenInstallResult:
        transaction = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=transaction.phase,
            new_phase=FrozenInstallPhase.VALIDATING,
        )
        if self.final_validator is not None and not self.final_validator(plan):
            return self._attention(transaction, "FINAL_VALIDATION_FAILED", "frozen software/configuration validation failed")
        for node in plan.install_order:
            current = self.installer.get_addon_details(node.addon_id)
            if current is None or current.version != node.version or current.broken:
                return self._attention(transaction, "EXACT_VERSION_VALIDATION_FAILED", f"exact frozen version validation failed for {node.addon_id}")
            if current.enabled is not node.desired_enabled:
                self.installer.set_addon_enabled(node.addon_id, node.desired_enabled)
        for node in plan.install_order:
            current = self.installer.get_addon_details(node.addon_id)
            if current is None or current.version != node.version or current.enabled is not node.desired_enabled or current.broken:
                return self._attention(transaction, "FINAL_STATE_VALIDATION_FAILED", f"final frozen state validation failed for {node.addon_id}")
        transaction = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=FrozenInstallPhase.VALIDATING,
            new_phase=FrozenInstallPhase.COMPLETE,
        )
        try:
            guard.restore_original(transaction.original_update_policy)
        except Exception:
            return self._attention(transaction, "UPDATE_POLICY_RESTORE_FAILED", "original updater policy could not be restored")
        try:
            self.store.clear_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.COMPLETE,
            )
        except Exception:
            return self._attention(transaction, "FROZEN_TRANSACTION_CLEAR_FAILED", "completed frozen transaction could not be cleared")
        return FrozenInstallResult("complete", message="frozen installation completed and updater policy restored")

    def _attention(self, transaction, code: str, message: str) -> FrozenInstallResult:
        try:
            current = self.store.inspect() or transaction
            if current.phase is not FrozenInstallPhase.NEEDS_ATTENTION:
                current = self.store.transition_expected(
                    transaction_id=current.transaction_id,
                    expected_phase=current.phase,
                    new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
                    status_code=_bounded(code, _MAX_CODE, "FROZEN_INSTALL_FAILED"),
                    status_message=_bounded(message, _MAX_MESSAGE, "frozen install requires attention"),
                )
        except Exception:
            current = transaction
        return FrozenInstallResult("needs_attention", transaction=current, code=code, message=message)

    def _safe_inspect(self) -> Optional[FrozenInstallTransaction]:
        try:
            return self.store.inspect()
        except Exception:
            return None


@dataclass(frozen=True)
class FrozenStartupPrecondition:
    allowed: bool
    transaction: Optional[FrozenInstallTransaction] = None
    code: str = ""
    message: str = ""


def ensure_frozen_install_guard(
    *,
    store: Optional[FrozenInstallStore] = None,
    policy_backend: Optional[UpdatePolicyBackend] = None,
) -> FrozenStartupPrecondition:
    """Reassert quarantine before any BM-020 startup/resume work."""
    target = store or FrozenInstallStore()
    try:
        transaction = target.inspect()
    except Exception:
        return FrozenStartupPrecondition(False, code="FROZEN_TRANSACTION_INSPECTION_FAILED", message="active frozen transaction could not be inspected")
    if transaction is None:
        return FrozenStartupPrecondition(True)
    backend = policy_backend or _default_policy_backend()
    try:
        AddonUpdateGuard(backend).reassert_required()
    except Exception:
        try:
            updated = target.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=transaction.phase,
                new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
                status_code="UPDATER_REASSERT_FAILED",
                status_message="NEVER_CHECK could not be reasserted before startup resume",
            )
        except Exception:
            updated = transaction
        return FrozenStartupPrecondition(False, updated, "UPDATER_REASSERT_FAILED", "NEVER_CHECK could not be reasserted before startup resume")
    try:
        import xbmc
        xbmc.log(
            "Build Manager BM-022 updater guard reasserted before BM-020 startup",
            xbmc.LOGINFO,
        )
    except (ImportError, AttributeError, RuntimeError):
        pass
    if transaction.phase is FrozenInstallPhase.NEEDS_ATTENTION:
        return FrozenStartupPrecondition(False, transaction, "FROZEN_NEEDS_ATTENTION", "frozen installation requires explicit recovery")
    return FrozenStartupPrecondition(True, transaction, message="frozen updater guard reasserted")


def run_frozen_install_startup(
    *,
    bm020_status: object,
    store: Optional[FrozenInstallStore] = None,
    artifact_store: Optional[ArtifactStore] = None,
    policy_backend: Optional[UpdatePolicyBackend] = None,
    installer: Optional[FrozenArtifactBackend] = None,
) -> Optional[FrozenInstallResult]:
    """Finish a frozen install after BM-020 has completed its resume step.

    The service calls this only after ``run_startup``.  The precondition is
    repeated defensively, then a successful BM-020 resume is the sole event
    that permits frozen finalization.
    """
    target = store or FrozenInstallStore()
    transaction = target.inspect()
    if transaction is None:
        return None
    precondition = ensure_frozen_install_guard(
        store=target, policy_backend=policy_backend
    )
    if not precondition.allowed:
        return FrozenInstallResult(
            "needs_attention",
            transaction=precondition.transaction or transaction,
            code=precondition.code,
            message=precondition.message,
        )
    resume_result = getattr(bm020_status, "resume_result", None)
    if transaction.phase is not FrozenInstallPhase.AWAITING_RESTART:
        return FrozenInstallResult(
            "needs_attention" if transaction.phase is FrozenInstallPhase.NEEDS_ATTENTION else "awaiting_restart",
            transaction=transaction,
            code=transaction.status_code or "FROZEN_STARTUP_WAITING",
            message=transaction.status_message or "frozen installation is not ready for finalization",
        )
    if resume_result is None or not getattr(resume_result, "succeeded", False):
        return FrozenInstallResult(
            "awaiting_restart",
            transaction=transaction,
            code="BM020_RESUME_PENDING",
            message="frozen installation is waiting for successful BM-020 resume",
        )
    root = default_frozen_install_root()
    coordinator = FrozenInstallCoordinator(
        store=target,
        artifact_store=artifact_store or ArtifactStore(root / "frozen-artifacts"),
        policy_backend=policy_backend or _default_policy_backend(),
        installer=installer or KodiRuntimeFrozenArtifactBackend(),
    )
    return coordinator.resume_after_restart()


def _default_policy_backend() -> UpdatePolicyBackend:
    try:
        import xbmc

        def _rpc(method, params):
            response = json.loads(
                xbmc.executeJSONRPC(json.dumps({
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": 1,
                }))
            )
            return response.get("result", response)

        return KodiJsonRpcUpdatePolicyBackend(
            _rpc
        )
    except (ImportError, AttributeError, RuntimeError) as exc:
        raise FrozenInstallError("Kodi JSON-RPC runtime is unavailable") from exc


def _default_session_id() -> str:
    from resources.lib.session import get_current_kodi_session_id
    return get_current_kodi_session_id()
