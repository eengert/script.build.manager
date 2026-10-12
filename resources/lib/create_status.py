"""Creation-free Create record observation; no runtime or recovery authority.

Only validated record phase/commitment is exposed. Two lock-free reads detect
visible disagreement, not every external race. No owner or operation eligibility
is inferred, and no private record fields cross this adapter boundary.
"""
from pathlib import Path

from resources.lib.capture_lifecycle import CaptureStore
from resources.lib.status_model import CreateObservation


def observe_create_state(root: Path) -> CreateObservation:
    try:
        store = CaptureStore(root)
        record = store.read()
        if store.read() != record:
            return CreateObservation.UNVERIFIABLE
        if record is None:
            return CreateObservation.NO_RECORD_OBSERVED
        if record.commit_pending:
            return CreateObservation.TERMINAL_PENDING
        if record.held:
            return CreateObservation.HELD
        return CreateObservation.TERMINAL_RELEASED
    except Exception:
        return CreateObservation.UNVERIFIABLE
