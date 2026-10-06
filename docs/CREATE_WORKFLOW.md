# Native Create Build workflow (BM-UI-003C)

`default.py` injects a lazy `CreateBuildWorkflow` into the skin-owned native
menu. The route selects all eligible installed roots and the current skin by
default. Build Manager, shared Kodi system dependencies, Python modules,
resource packages and internal binary/runtime types are not selectable roots.
Names sort case-insensitively with ID tie-breaking; unsafe/unavailable names
fall back to IDs. Frozen dependency closure remains the accepted capture path.
Excluding a dependency does not promote it back into a managed root.

The session preserves exclusions across native multiselect cancellation and
reopening. Private capture defaults on. The canonical trusted catalog uses
`af3-common` as the supported public schema (capture reads current values), and
`redlight_declaration()` for supported Red Light 2.6.8 private resources. Unknown
components have software capture only. There is no setting-key/path editor or
settings.xml/addon_data enumeration. Excluded owners and the private-off option
remove corresponding declarations before request validation.

Names and device labels generate a bounded ASCII slug plus a digest of the
original trimmed label. This preserves stable identity while avoiding ordinary
punctuation, Unicode and truncation collisions. Existing same-ID/different-name
entries fail closed. Versions require MAJOR.MINOR.PATCH; the suggestion is
1.0.0 or the highest stored semantic version's next patch. Platform IDs use the
inspector's six trusted platform identities. The editable device label defaults
to the localized Current device string.

Review produces one immutable request. Counts, exclusion details and final
native yes/no confirmation precede acquisition and persistence. Back/Cancel
creates nothing. The optional `expected_active_skin` request field is a narrow
capture-contract extension: the confirmed current skin must still be active
when capture inspects state; drift returns incomplete rather than silently
capturing another skin. Older capture callers retain their existing default.
A native `busydialognocancel` presents indeterminate activity; no percentages
are fabricated. Every confirmed attempt ends in an acknowledged native result.

Only COMPLETE capture proceeds. Private content uses a deterministic ID derived
from build ID/version. `PrivateOverlayStore.create_commit()` holds a no-follow,
profile-local advisory lock across private publication, registration and any
rollback. `ensure_exact()` validates bounded regular existing content, rejects
malformed/duplicate-key JSON and conflicts, and atomically links a fully synced
0600 private file without replacing a target. Existing exact content is
idempotent. The legacy explicit overwrite/import path cooperates with this
lock; Create never uses it. `remove_if_exact()` checks the expected fingerprint
and removes only a new overlay owned by this attempt.

Public registration uses `PreparedPublicBundle.registration_inputs()` and the
accepted BuildLibrary API. Registration can raise after publishing its registry;
`registered_bundle()` distinguishes a validated published entry from proven
absence before rollback. If authoritative state cannot be read, private content
is retained and the result says saving could not be confirmed. Successful
registration selects the new entry/profile. Selection failure preserves both
stores and reports that the saved build could not be selected automatically.

The stores are not one atomic transaction. A crash after private publication
can leave a non-authoritative private orphan (or a private staging inode);
unreadable/unsafe state during rollback can also require retention. No broad
orphan cleanup is attempted. A successfully published public build always has
its correctly validated required private content at publication. Capture
creation timestamps participate in accepted frozen/public identity; fresh
attempts with different timestamps may conflict at the same build/version.
Choose a new version rather than overwriting prior content.

UI-safe results carry localized categories and counts, never exception text,
private values, staged paths or internal hashes. Private content is persisted
only in PrivateOverlayStore. Create calls no install, enable/disable, skin
activation, public/private apply, updater-policy or restart operation.

Offline tests cover native interaction, real capture/library/store commits,
privacy sentinels, rollback and publication ambiguity. Live visual/end-to-end
behavior remains unqualified until independent review accepts the exact commit
and a separate task stages it to portable Kodi Build Manager Test.app (`-p`).
