"""Shared activation-hold enforcement for Build Manager coordinators."""

from __future__ import annotations

from typing import Callable, FrozenSet, Optional


class ActivationHoldError(Exception):
    """A Build Manager operation would activate an add-on held by a lifecycle."""


def current_activation_holds(
    provider: Optional[Callable[[], FrozenSet[str]]] = None,
) -> FrozenSet[str]:
    """Read the holds from the active BM-022 transaction, failing closed."""
    if provider is not None:
        result = provider()
        if not isinstance(result, (set, frozenset)):
            raise ActivationHoldError("activation-hold provider returned invalid state")
        return frozenset(result)
    from resources.lib.frozen_install import active_activation_hold_ids
    return active_activation_hold_ids()


def reject_held_activation(
    addon_id: str,
    *,
    provider: Optional[Callable[[], FrozenSet[str]]] = None,
) -> None:
    """Raise before a coordinator can enable or native-install a held add-on."""
    if addon_id in current_activation_holds(provider):
        raise ActivationHoldError("add-on activation is held by a resource lifecycle")
