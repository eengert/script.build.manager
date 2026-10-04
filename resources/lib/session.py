"""Kodi-process session identity for BM-020B."""

from __future__ import annotations

import uuid
from typing import Callable, Optional


SESSION_PROPERTY = "script.build.manager.kodi_session_id"
GLOBAL_WINDOW_ID = 10000


class SessionIdentityError(RuntimeError):
    """Kodi could not provide a process-scoped session property."""


def get_current_kodi_session_id(
    *, window=None, token_factory: Optional[Callable[[], str]] = None
) -> str:
    """Return a UUID held in Kodi's process-scoped global window property."""
    if window is None:
        try:
            import xbmcgui
            window = xbmcgui.Window(GLOBAL_WINDOW_ID)
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise SessionIdentityError("Kodi global window is unavailable") from exc
    try:
        existing = window.getProperty(SESSION_PROPERTY)
    except Exception as exc:  # Kodi runtime exceptions are intentionally bounded.
        raise SessionIdentityError("could not read Kodi session identity") from exc
    if isinstance(existing, str) and existing:
        try:
            uuid.UUID(existing)
            return existing
        except ValueError:
            # A malformed value cannot safely identify a session; replace it.
            pass
    factory = token_factory or (lambda: str(uuid.uuid4()))
    token = factory()
    try:
        uuid.UUID(token)
    except (ValueError, TypeError, AttributeError) as exc:
        raise SessionIdentityError("session identity generator returned an invalid token") from exc
    try:
        window.setProperty(SESSION_PROPERTY, token)
    except Exception as exc:
        raise SessionIdentityError("could not store Kodi session identity") from exc
    return token
