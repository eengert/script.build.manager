"""Fixed Test.app A15 acquisition, in one foreground host process only.

No native operation is invoked here. A caller must separately authorize the
intervening UI operation. Private projections live only in this session; they
are not resumable, serializable, or public evidence. This is not an atomic
snapshot or proof of writer exclusion, maintenance attribution or qualification.
"""
from __future__ import annotations

import copy
from pathlib import Path

from tools import bm_test_app as bm
from tools import bm_public_preservation_witness as witness


class _Refused(Exception):
    pass


def _result(boundary, acquisition, reason, statuses=None):
    statuses = statuses or ['UNVERIFIED'] * len(witness.FILES)
    compared = boundary == 'after' and acquisition == 'ACQUIRED'
    scope = ('PRESERVED' if all(s == 'PRESERVED' for s in statuses)
             else 'CHANGED_OR_MISSING') if compared else 'UNVERIFIED'
    return {'schema': 'bm-a15-acquisition/1', 'boundary': boundary,
            'acquisition': acquisition, 'reason': reason, 'scope_result': scope,
            'files': [{'file': name, 'scope': description, 'status': status}
                      for name, description, status in zip(witness.FILES, witness.SCOPES, statuses)],
            'complete_preservation': 'UNVERIFIED', 'qualification': 'not_qualified',
            'maintenance_attribution': 'UNKNOWN', 'writer_exclusion': 'UNVERIFIED',
            'temporary_cleanup': 'COMPLETE' if acquisition == 'ACQUIRED' else 'UNVERIFIED'}


class AcquisitionSession:
    """Explicit begin()/finish(), once each; no daemon, persistence or retry.

    Use with a context manager so abandoning a session drops its references.
    Dropping Python references is not secure memory erasure. Do not inspect or
    log private attributes, enable locals dumps, or serialize the host process.
    """
    __slots__ = ('_services', '_manifest', '_repo', '_target', '_bundle', '_before', '_state')

    def __init__(self, services, *, manifest, git_repo):
        self._services = services
        self._manifest = manifest
        self._repo = git_repo
        self._target = services.target
        self._bundle = None
        self._before = None
        self._state = 'new'

    def __repr__(self):
        return '<A15 AcquisitionSession: private baseline withheld>'

    def __reduce_ex__(self, protocol):
        raise TypeError('A15 sessions cannot be serialized')

    def __copy__(self):
        raise TypeError('A15 sessions cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('A15 sessions cannot be copied')

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def close(self):
        self._before = None
        self._bundle = None
        self._state = 'closed'

    def _admit(self):
        target = self._services.target
        if (target is not self._target or type(target) is not bm.TestAppTarget
                or target.production is not True or str(target.root) != bm.AUTHORIZED_TEST_APP
                or not isinstance(self._repo, Path) or not self._repo.is_absolute()):
            raise _Refused('admission_refused')
        try:
            identity = bm.identify(self._services, require='not_running')
        except Exception:
            raise _Refused('admission_refused') from None
        try:
            manifest = bm.validate_manifest(self._manifest)
            verification = bm.verify_installed(self._services, manifest, git_repo=self._repo)
            if (verification.get('installed_equals_manifest') is not True
                    or verification.get('installed_equals_candidate') is not True
                    or verification.get('git_binding', {}).get('checked') is not True
                    or verification['git_binding'].get('ok') is not True):
                raise ValueError()
        except Exception:
            raise _Refused('source_unverified') from None
        try:
            final_identity = bm.identify(self._services, require='not_running')
        except Exception:
            raise _Refused('admission_refused') from None
        if (identity.bundle != final_identity.bundle
                or (self._bundle is not None and identity.bundle != self._bundle)):
            raise _Refused('admission_refused')
        return identity.bundle

    def _capture(self, *, baseline):
        bundle = self._admit()
        if self._bundle is None:
            self._bundle = bundle
        # Reuse only the descriptor reader, after fixed native target admission.
        # The offline entry point/root policy and snapshot ReadGuard stay intact;
        # this separate API grants no arbitrary path or root selection.
        root = self._target.portable_data
        def read_all():
            return [witness.read_copy(root, name, witness.MAX_DB if i < 2 else witness.MAX_XML)
                    for i, name in enumerate(witness.FILES)]
        raw = read_all()
        if baseline and any(item[0] is None for item in raw):
            raise witness.Unverified('missing_input')
        projections = []
        for i, (data, unused_identity) in enumerate(raw):
            projections.append(None if data is None else
                               witness.database_projection(data, i) if i < 2 else
                               witness.xml_projection(data, i))
        # Includes bytes and descriptor identities for all five sources. Stopped
        # is not writer-free. Any observed change invalidates the entire capture.
        self._admit()
        if raw != read_all():
            raise witness.Unverified('input_changed')
        self._admit()
        return projections

    def _failure(self, boundary, exc):
        self.close()
        if type(exc) is _Refused:
            reason = exc.args[0] if len(exc.args) == 1 and type(exc.args[0]) is str else None
            return _result(boundary, 'REFUSED', reason if reason in
                           ('admission_refused', 'source_unverified') else 'acquisition_failed')
        reason = witness.refusal_reason(exc, 'acquisition_failed')
        return _result(boundary, 'REFUSED' if type(exc) is witness.Unverified else 'FAILED', reason)

    def begin(self):
        if self._state != 'new':
            self.close()
            return _result('before', 'REFUSED', 'session_closed')
        self._state = 'acquiring'
        try:
            self._manifest = copy.deepcopy(self._manifest)
            self._before = self._capture(baseline=True)
            self._state = 'held'
            return _result('before', 'ACQUIRED', 'baseline_held_in_memory')
        except (Exception, KeyboardInterrupt) as exc:
            return self._failure('before', exc)

    def finish(self):
        if self._state != 'held':
            self.close()
            return _result('after', 'REFUSED', 'session_closed')
        before = self._before
        self._before = None
        self._state = 'closed'  # Consume before any new read; failure cannot retry.
        try:
            after = self._capture(baseline=False)
            statuses = ['PRESERVED' if left == right else 'CHANGED_OR_MISSING'
                        for left, right in zip(before, after)]
            return _result('after', 'ACQUIRED', 'scoped_comparison', statuses)
        except (Exception, KeyboardInterrupt) as exc:
            return self._failure('after', exc)
        finally:
            self.close()
