"""Dormant A11 state foundation. No skin/configuration/publication executor.

Only a future trusted coordinator may supply authenticated observations here.
These persistence APIs do not authenticate Kodi or execute either approval.
Cancellation records remain owned/auditable until a separately reviewed release
path exists; ordinary abandon/clear must never consume this protocol.
"""
from dataclasses import dataclass, replace
import hashlib
import json
import re

from resources.lib.build_library import AppliedBuildAssociation
from resources.lib.update_guard import AddonUpdateGuard, AddonUpdatePolicy

AUTHORIZED = 'skin_transition_authorized'
TRANSITIONING = 'skin_transition_in_progress'
AWAITING = 'awaiting_configuration_approval'
CANCELLING = 'skin_cancellation_pending'
CANCELLED = 'skin_cancelled'
PHASES = frozenset((AUTHORIZED, TRANSITIONING, AWAITING, CANCELLING, CANCELLED))


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('skin approval digest invalid')


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,159}', value):
        raise ValueError('skin approval identity invalid')


@dataclass(frozen=True)
class SkinApprovalBinding:
    build_id: str
    profile_id: str
    source_entry_id: str
    frozen_fingerprint: str
    configuration_fingerprint: str
    first_review_fingerprint: str
    previous_skin: str
    previous_applied: AppliedBuildAssociation | None
    skin_id: str = 'skin.arctic.fuse.3'
    skin_version: str = '3.3.12'

    def __post_init__(self):
        _identifier(self.build_id)
        _identifier(self.profile_id)
        _identifier(self.previous_skin)
        if (not self.previous_skin.startswith('skin.') or self.previous_skin == self.skin_id
                or self.skin_id != 'skin.arctic.fuse.3' or self.skin_version != '3.3.12'):
            raise ValueError('unsupported skin transition binding')
        for value in (self.source_entry_id, self.frozen_fingerprint,
                      self.configuration_fingerprint, self.first_review_fingerprint):
            _digest(value)
        if self.previous_applied is not None and (
                not isinstance(self.previous_applied, AppliedBuildAssociation)
                or self.previous_applied.device_profile_id != self.profile_id):
            raise ValueError('previous applied identity invalid')
        if self.previous_applied is not None:
            _digest(self.previous_applied.entry_id)
            _digest(self.previous_applied.resolution_fingerprint)

    def to_dict(self):
        return {**{k: v for k, v in vars(self).items() if k != 'previous_applied'},
                'previous_applied': self.previous_applied.to_dict() if self.previous_applied else None}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError('skin approval binding fields invalid')
        value = dict(value)
        if value['previous_applied'] is not None:
            value['previous_applied'] = AppliedBuildAssociation.from_dict(value['previous_applied'])
        return cls(**value)

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class SkinApprovalState:
    binding: SkinApprovalBinding
    revision: int = 0
    transition_witness: str = ''
    phase: str = AUTHORIZED

    def __post_init__(self):
        if not isinstance(self.binding, SkinApprovalBinding) or type(self.revision) is not int or self.revision < 0:
            raise ValueError('skin approval state invalid')
        if self.phase not in PHASES | {'needs_attention'}:
            raise ValueError('skin approval phase invalid')
        if not isinstance(self.transition_witness, str):
            raise ValueError('skin transition witness invalid')
        if self.transition_witness:
            _digest(self.transition_witness)

    def to_dict(self):
        return {'schema_version': 1, 'binding': self.binding.to_dict(),
                'revision': self.revision, 'transition_witness': self.transition_witness, 'phase': self.phase}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or set(value) != {
                'schema_version', 'binding', 'revision', 'transition_witness', 'phase'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1):
            raise ValueError('skin approval state fields invalid')
        return cls(SkinApprovalBinding.from_dict(value['binding']), value['revision'], value['transition_witness'], value['phase'])

    def validate_transaction(self, tx):
        b = self.binding
        if (tx.library_target is None or tx.build_id != b.build_id
                or tx.device_profile_id != b.profile_id
                or tx.manifest_fingerprint != b.frozen_fingerprint
                or tx.library_target.source.entry_id != b.source_entry_id
                or tx.phase.value != 'needs_attention'
                or tx.activation_hold_ids or not tx.activation_hold_released
                or tx.restart_transaction_id or tx.lifecycle_stage.value != 'none'
                or tx.private_overlay_id or tx.private_overlay_fingerprint or tx.private_overlay_required
                or tx.resolution_records or tx.resolution_fingerprint
                or tx.resolved_software_fingerprint or tx.configuration_manifest_path):
            raise ValueError('skin approval transaction binding invalid')
        if tx.updater_guard_required != (self.phase != CANCELLED):
            raise ValueError('skin approval protection invalid')
        if self.phase == AUTHORIZED and (self.revision or self.transition_witness):
            raise ValueError('skin authorization must be initial')
        if self.phase == TRANSITIONING and self.transition_witness:
            raise ValueError('unconfirmed skin transition has a witness')
        if self.phase == AWAITING and not self.transition_witness:
            raise ValueError('pending approval requires confirmed transition')
        if self.phase != AUTHORIZED and self.revision == 0:
            raise ValueError('skin approval continuation requires a revision')


class SkinApprovalJournal:
    """CAS durable state only, using the existing transaction lock/atomic writer.

    No generic transition to CONFIGURING/COMPLETE and no clearing/publication API.
    Observation arguments are trusted future coordinator inputs, never UI claims.
    """
    def __init__(self, store):
        self.store = store

    def reserve(self, transaction):
        if transaction.skin_approval is None or transaction.skin_approval.phase != AUTHORIZED:
            raise ValueError('initial skin authorization required')
        return self.store.create(transaction)

    def _change(self, expected, binding, phase, *, policy_backend=None,
                observed_skin=None, observed_version=None, stable=False, witness=None):
        from resources.lib.frozen_install import FrozenInstallPhase, FrozenInstallStateConflict, _utc_now
        if expected.skin_approval is None or binding != expected.skin_approval.binding:
            raise FrozenInstallStateConflict('skin approval binding changed')
        old = expected.skin_approval.phase
        allowed = {AUTHORIZED: {TRANSITIONING, CANCELLING, CANCELLED, 'needs_attention'},
                   TRANSITIONING: {AWAITING, 'needs_attention'},
                   AWAITING: {CANCELLING, 'needs_attention'},
                   CANCELLING: {CANCELLED, 'needs_attention'}}
        if phase not in allowed.get(old, set()):
            raise FrozenInstallStateConflict('skin approval transition refused')
        with self.store.locked():
            if self.store._read_unlocked() != expected:
                raise FrozenInstallStateConflict('skin approval snapshot changed')
            from resources.lib.capture_lifecycle import require_no_capture
            require_no_capture(self.store.root)
            if phase != 'needs_attention':
                if policy_backend is None:
                    raise FrozenInstallStateConflict('updater observation required')
                if phase == CANCELLED:
                    restored = policy_backend.get_policy()
                    if not isinstance(restored, AddonUpdatePolicy) or restored != expected.original_update_policy:
                        raise FrozenInstallStateConflict('original updater policy not restored')
                else:
                    AddonUpdateGuard(policy_backend).verify_quarantined()
            state = expected.skin_approval
            if phase in (AWAITING, CANCELLING, CANCELLED):
                wanted = binding.skin_id if state.transition_witness or phase == AWAITING else binding.previous_skin
                if (observed_skin != wanted or observed_version != binding.skin_version or stable is not True):
                    raise FrozenInstallStateConflict('skin transition observation invalid')
            if phase == AWAITING:
                _digest(witness)
                state = replace(state, transition_witness=witness)
            state = replace(state, revision=state.revision + 1, phase=phase)
            updated = replace(expected, phase=FrozenInstallPhase.NEEDS_ATTENTION, skin_approval=state,
                updater_guard_required=phase != CANCELLED, updated_at=_utc_now(),
                status_code=('SKIN_CANCELLED_NOT_APPLIED' if phase == CANCELLED else
                    'SKIN_APPROVAL_UNRESOLVED' if phase == 'needs_attention' else ''), status_message='')
            self.store._write_unlocked(updated)
            return updated

    def begin_transition(self, expected, binding, *, policy_backend):
        return self._change(expected, binding, TRANSITIONING, policy_backend=policy_backend)

    def confirm_transition(self, expected, binding, *, policy_backend, observed_skin,
                           observed_version, stable, witness):
        return self._change(expected, binding, AWAITING, policy_backend=policy_backend,
            observed_skin=observed_skin, observed_version=observed_version, stable=stable, witness=witness)

    def request_cancel(self, expected, binding, *, policy_backend, observed_skin, observed_version, stable):
        return self._change(expected, binding, CANCELLING, policy_backend=policy_backend,
            observed_skin=observed_skin, observed_version=observed_version, stable=stable)

    def confirm_cancel(self, expected, binding, *, policy_backend, observed_skin, observed_version, stable):
        # Does NOT restore updater or release ownership. It records verified
        # restoration only; a future reviewed cancel owner must perform it.
        return self._change(expected, binding, CANCELLED, policy_backend=policy_backend,
            observed_skin=observed_skin, observed_version=observed_version, stable=stable)

    def attention(self, expected, binding):
        return self._change(expected, binding, 'needs_attention')
