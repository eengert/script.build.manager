"""Global Kodi add-on updater guard (BM-021B).

The guard is intentionally independent of installation orchestration.  It
captures the current global policy, changes it through the supported Settings
JSON-RPC API, verifies the result, and requires an explicit restore call.
Failures never silently restore a partial transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional


class UpdateGuardError(Exception):
    """The global updater policy could not be safely read or changed."""


class AddonUpdatePolicy(IntEnum):
    AUTOMATIC = 0
    NOTIFY_ONLY = 1
    NEVER_CHECK = 2


class UpdatePolicyBackend:
    """Injectable backend for the supported Kodi updater setting."""

    def get_policy(self) -> AddonUpdatePolicy:
        raise NotImplementedError

    def set_policy(self, policy: AddonUpdatePolicy) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class UpdateGuardSnapshot:
    original: AddonUpdatePolicy
    guarded: AddonUpdatePolicy


class AddonUpdateGuard:
    """Fail-closed guard for Kodi's global add-on updater policy.

    ``restore()`` is deliberately explicit.  A failed future transaction must
    be able to leave the updater inhibited until recovery code or a human
    explicitly chooses to restore the original policy.
    """

    def __init__(self, backend: UpdatePolicyBackend):
        self.backend = backend
        self._snapshot: Optional[UpdateGuardSnapshot] = None

    @property
    def snapshot(self) -> Optional[UpdateGuardSnapshot]:
        return self._snapshot

    @property
    def engaged(self) -> bool:
        return self._snapshot is not None

    def engage(self) -> UpdateGuardSnapshot:
        if self._snapshot is not None:
            self.reassert()
            return self._snapshot
        original = self._read_policy("read original updater policy")
        return self.engage_with_original(original)

    def engage_with_original(
        self, original: AddonUpdatePolicy
    ) -> UpdateGuardSnapshot:
        """Acquire the guard after the caller durably records ``original``.

        Frozen installation persists the original policy before changing Kodi.
        This seam avoids a second, potentially different read between the
        durable transaction write and the quarantine mutation.
        """
        original = _coerce_policy(original)
        if self._snapshot is not None:
            if self._snapshot.original != original:
                raise UpdateGuardError("cannot replace an active updater snapshot")
            self.reassert()
            return self._snapshot
        try:
            self.backend.set_policy(AddonUpdatePolicy.NEVER_CHECK)
        except Exception as exc:
            raise UpdateGuardError("failed to set NEVER_CHECK updater policy") from exc
        self._verify(AddonUpdatePolicy.NEVER_CHECK, "verify NEVER_CHECK updater policy")
        self._snapshot = UpdateGuardSnapshot(original, AddonUpdatePolicy.NEVER_CHECK)
        return self._snapshot

    def reassert(self) -> None:
        if self._snapshot is None:
            raise UpdateGuardError("cannot reassert an updater guard that is not engaged")
        self.reassert_required()

    def reassert_required(self) -> None:
        """Set and verify NEVER_CHECK using durable transaction ownership.

        This operation intentionally does not require an in-memory snapshot;
        startup after Kodi restart reconstructs ownership from the durable
        frozen-install transaction.
        """
        try:
            self.backend.set_policy(AddonUpdatePolicy.NEVER_CHECK)
        except Exception as exc:
            raise UpdateGuardError("failed to reassert NEVER_CHECK updater policy") from exc
        self._verify(AddonUpdatePolicy.NEVER_CHECK, "verify reasserted updater policy")

    def restore(self) -> AddonUpdatePolicy:
        if self._snapshot is None:
            raise UpdateGuardError("cannot restore an updater guard that is not engaged")
        original = self._snapshot.original
        restored = self.restore_original(original)
        self._snapshot = None
        return restored

    def restore_original(self, original: AddonUpdatePolicy) -> AddonUpdatePolicy:
        """Restore a durably captured policy after a process restart."""
        original = _coerce_policy(original)
        try:
            self.backend.set_policy(original)
        except Exception as exc:
            raise UpdateGuardError("failed to restore original updater policy") from exc
        self._verify(original, "verify restored updater policy")
        return original

    def _read_policy(self, context: str) -> AddonUpdatePolicy:
        try:
            value = self.backend.get_policy()
            return _coerce_policy(value)
        except Exception as exc:
            raise UpdateGuardError(f"{context} failed") from exc

    def _verify(self, expected: AddonUpdatePolicy, context: str) -> None:
        actual = self._read_policy(context)
        if actual != expected:
            raise UpdateGuardError(
                f"{context}: expected {expected.name}, observed {actual.name}"
            )


def _coerce_policy(value: object) -> AddonUpdatePolicy:
    if isinstance(value, bool):
        raise UpdateGuardError("updater policy must be an integer enum")
    try:
        return AddonUpdatePolicy(int(value))
    except (TypeError, ValueError) as exc:
        raise UpdateGuardError("unknown updater policy") from exc


class KodiJsonRpcUpdatePolicyBackend(UpdatePolicyBackend):
    """Supported JSON-RPC adapter for ``general.addonupdates``."""

    SETTING_ID = "general.addonupdates"

    def __init__(self, call: Callable[[str, dict], object]):
        self._call = call

    def get_policy(self) -> AddonUpdatePolicy:
        response = self._call(
            "Settings.GetSettingValue", {"setting": self.SETTING_ID}
        )
        if not isinstance(response, dict):
            raise UpdateGuardError("Settings.GetSettingValue returned a malformed response")
        value = response.get("value")
        return _coerce_policy(value)

    def set_policy(self, policy: AddonUpdatePolicy) -> None:
        policy = _coerce_policy(policy)
        response = self._call(
            "Settings.SetSettingValue",
            {"setting": self.SETTING_ID, "value": int(policy)},
        )
        if isinstance(response, dict) and response.get("success") is False:
            raise UpdateGuardError("Settings.SetSettingValue reported failure")
