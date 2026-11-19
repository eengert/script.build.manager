"""Fixed Test.app A15 acquisition, in one foreground host process only.

No native operation is invoked here. A caller must separately authorize the
intervening UI operation. Private projections live only in this session; they
are not resumable, serializable, or public evidence. The after result also
carries a sanitized D-032 classification of the same session's projections; it
is a classification only and never a practical verdict. A second sibling block
reports whole-file Addons33 byte identity between the two boundaries (D-032
clarification of 2026-11-19), from an in-memory SHA-256 and length that never leave
this module. This is not an atomic snapshot or proof of writer exclusion, maintenance
attribution or qualification.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from tools import bm_test_app as bm
from tools import bm_public_preservation_witness as witness
from tools import bm_practical_preservation_comparator as comparator

PRACTICAL_SCHEMA = 'bm-a15-practical-classification/1'
_PER_FILE_CLASSES = (comparator.EXACT, comparator.MAINTENANCE_ONLY, comparator.MEANINGFUL)
# Whole-file Addons33 byte identity at the two boundaries. Closed vocabulary; the public
# block never carries a digest, a length, a path or any database content.
ADDONS33_BYTES_SCHEMA = 'bm-a15-addons33-bytes/1'
ADDONS33_BYTES_SCOPE = 'addons33_file_bytes'
BYTES_IDENTICAL = 'BYTES_IDENTICAL'
BYTES_DIFFERENT = 'BYTES_DIFFERENT'
BYTES_UNVERIFIED = 'UNVERIFIED'


class _Refused(Exception):
    pass


def _result(boundary, acquisition, reason, statuses=None, practical=None, addons33_bytes=None):
    statuses = statuses or ['UNVERIFIED'] * len(witness.FILES)
    compared = boundary == 'after' and acquisition == 'ACQUIRED'
    scope = ('PRESERVED' if all(s == 'PRESERVED' for s in statuses)
             else 'CHANGED_OR_MISSING') if compared else 'UNVERIFIED'
    result = {'schema': 'bm-a15-acquisition/1', 'boundary': boundary,
              'acquisition': acquisition, 'reason': reason, 'scope_result': scope,
              'files': [{'file': name, 'scope': description, 'status': status}
                        for name, description, status in zip(witness.FILES, witness.SCOPES, statuses)],
              'complete_preservation': 'UNVERIFIED', 'qualification': 'not_qualified',
              'maintenance_attribution': 'UNKNOWN', 'writer_exclusion': 'UNVERIFIED',
              'temporary_cleanup': 'COMPLETE' if acquisition == 'ACQUIRED' else 'UNVERIFIED'}
    if practical is not None:
        result['practical'] = practical
    if addons33_bytes is not None:
        result['addons33_bytes'] = addons33_bytes
    return result


def _aggregate(labels):
    # INCONCLUSIVE dominates, and any meaningful file makes the run non-maintenance.
    for label in ('INCONCLUSIVE', comparator.MEANINGFUL, comparator.MAINTENANCE_ONLY):
        if label in labels:
            return label
    return comparator.EXACT


def _practical_row(name, summary):
    if type(summary) is not comparator.FileSummary or summary.verdict not in _PER_FILE_CLASSES:
        return {'file': name, 'classification': 'INCONCLUSIVE', 'maintenance': [], 'meaningful_count': 0}
    return {'file': name, 'classification': summary.verdict,
            'maintenance': [[cls, count] for cls, count in summary.maintenance],
            'meaningful_count': summary.meaningful_count}


def _practical(before, after):
    """Sanitized D-032 classification of this session's own in-memory projections.

    Each file is classified on its own. A comparator rejection, missing input or any
    other fault makes that file INCONCLUSIVE and never reaches the strict result. The
    output holds fixed names, closed class names and integer counts only. It is a
    classification, not a practical verdict, and it is never PASS.
    """
    sized = type(before) is list and type(after) is list and len(before) == len(after) == len(witness.FILES)
    rows = []
    for index, name in enumerate(witness.FILES):
        summary = None
        if sized:
            try:
                summary = comparator.compare_file(comparator.PROTECTED_KEYS[index], before[index], after[index])
            except Exception:
                summary = None
        rows.append(_practical_row(name, summary))
    return {'schema': PRACTICAL_SCHEMA, 'classification': _aggregate({row['classification'] for row in rows}),
            'files': rows, 'verdict': 'NOT_DECIDED', 'qualification': 'not_qualified'}


def _fingerprint(data):
    """Private SHA-256 and length of an admitted snapshot, or None when it is absent."""
    if type(data) is not bytes:
        return None
    return (hashlib.sha256(data).digest(), len(data))


def _addons33_bytes(before, after):
    """Sanitized byte-identity status from two private fingerprints.

    Equal digests and lengths are strong evidence that the admitted main files were
    identical at the two boundaries. Anything else is not a finding: a difference does
    not show loss, and a missing or malformed fingerprint is simply unverified.
    """
    def valid(value):
        return (type(value) is tuple and len(value) == 2 and type(value[0]) is bytes
                and len(value[0]) == 32 and type(value[1]) is int and value[1] >= 0)
    if not valid(before) or not valid(after):
        status = BYTES_UNVERIFIED
    else:
        status = BYTES_IDENTICAL if before == after else BYTES_DIFFERENT
    return {'schema': ADDONS33_BYTES_SCHEMA, 'scope': ADDONS33_BYTES_SCOPE, 'status': status}


class AcquisitionSession:
    """Explicit begin()/finish(), once each; no daemon, persistence or retry.

    Use with a context manager so abandoning a session drops its references.
    Dropping Python references is not secure memory erasure. Do not inspect or
    log private attributes, enable locals dumps, or serialize the host process.
    """
    __slots__ = ('_services', '_manifest', '_repo', '_target', '_bundle', '_before', '_fingerprint',
                 '_state')

    def __init__(self, services, *, manifest, git_repo):
        self._services = services
        self._manifest = manifest
        self._repo = git_repo
        self._target = services.target
        self._bundle = None
        self._before = None
        self._fingerprint = None
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
        self._fingerprint = None
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
        # Only the stable, admitted Addons33 bytes are fingerprinted; no raw copy is kept.
        return projections, _fingerprint(raw[0][0])

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
            self._before, self._fingerprint = self._capture(baseline=True)
            self._state = 'held'
            return _result('before', 'ACQUIRED', 'baseline_held_in_memory')
        except (Exception, KeyboardInterrupt) as exc:
            return self._failure('before', exc)

    def finish(self):
        if self._state != 'held':
            self.close()
            return _result('after', 'REFUSED', 'session_closed')
        before, before_fingerprint = self._before, self._fingerprint
        self._before = self._fingerprint = None
        self._state = 'closed'  # Consume before any new read; failure cannot retry.
        try:
            after, after_fingerprint = self._capture(baseline=False)
            statuses = ['PRESERVED' if left == right else 'CHANGED_OR_MISSING'
                        for left, right in zip(before, after)]
            return _result('after', 'ACQUIRED', 'scoped_comparison', statuses,
                           _practical(before, after),
                           _addons33_bytes(before_fingerprint, after_fingerprint))
        except (Exception, KeyboardInterrupt) as exc:
            return self._failure('after', exc)
        finally:
            self.close()
