# BM-017B Private Overlay Capture Validation

Status: **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**. This is a sanitized
read-only evidence record. No Family Room private value is present here.

## Scope and connection

The Family Room Apple TV was accessed only through the previously paired
Xcode `devicectl` mechanism, using the `appDataContainer` domain for
`com.eengert.koditvosnew`. The task performed device listing, names-only
directory inspection, and receipt of specifically justified metadata/source
files. It did not write to the device, control Kodi, restart Kodi, refresh a
repository, change add-on state, write a database, run Backup Pro, reconcile,
or install anything.

Temporary evidence was stored outside the repository in a disposable `0700`
directory with received files restricted to `0600`. The raw database and all
received source/metadata copies were deleted after secret-blind inspection;
the temporary directory was verified absent.

## Non-secret inventory

The installed metadata observed on Family Room was:

| Add-on | Installed version | Relevant finding |
|---|---:|---|
| `plugin.video.redlight` | `2.6.8` | Custom settings layer and `databases/settings.db` |
| `plugin.video.umbrella` | `6.7.87` | Native schema and provider integration source; addon data is cache/database state |
| `plugin.video.pov` | `6.09.04` | Native schema and provider integration source; addon data is cache/database state |
| `script.module.myaccounts` | `2.1.2` | Source writes provider auth fields through its settings object; addon_data directory was empty |
| `plugin.video.themoviedb.helper` | `6.17.3` | Player/cache/profile directories; no private source file was identified |
| `script.backup.pro` | `0.9.36` | Operational state only; not an authentication owner |
| `service.skinsettings.backup` | `1.0.16` | Lock, staging, identity, and service state; generated runtime |
| `service.af3.topupaction` | `1.3.7` | Service metadata; no private setting source identified |
| `skin.arctic.fuse.3` | `3.3.1` | Skin metadata; no private/auth source identified |

Red Light's Kodi `resources/settings.xml` exposed only informational/action
entries. Its installed public source defines a separate settings layer and
settings backup/import path, while `databases/settings.db` contains the
authoritative mixed settings table. The table schema was inspected without
selecting or printing values.

MyAccounts source contains direct provider-auth setting operations for Trakt,
Real-Debrid, Premiumize, AllDebrid, and TMDb session state. That establishes
an ownership capability in the add-on, but no user-specific MyAccounts file
was present in its Family Room `addon_data` directory. POV and Umbrella also
contain provider-specific setting operations and integration code; their
observed addon_data directories contained caches/databases rather than a
portable private overlay source. This evidence does not justify duplicating
provider credentials across owners.

## Observed private-state boundary

The Red Light table contained typed string fields for provider/account
categories. Secret-blind comparison of the stored value against the stored
default showed non-default private-state presence for these setting IDs:

- `mdblist.refresh`, `mdblist.token`, `mdblist.user`
- `pm.account_id`, `pm.token`
- `tb.token`
- `trakt.expires`, `trakt.refresh`, `trakt.token`, `trakt.user`

Only IDs, declared storage types, presence, and non-default status were
observed. No value, per-secret hash, token, account identifier, or credential
was emitted.

This state is not a BM-017A typed Kodi-setting overlay. The Red Light Kodi
settings schema does not expose these custom database rows as addressable
typed settings, and replacing or copying `settings.db` would also capture
mixed preferences, generated state, caches, and unrelated user choices. The
whole file is therefore not a safe BM-017 resource. No wildcard declaration,
arbitrary private-file copier, or add-on-specific production exception was
added.

## Result

- Frozen Family Room software: **COMPLETE**
- Software fingerprint:
  `sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`
- Private overlay capture: **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**
- Typed private declarations added in BM-017B: **0**
- Required typed entries captured: **0**
- Optional typed entries captured: **0**
- Private overlay created: **no**
- Private overlay fingerprint: **none**
- Captured desired state: **INCOMPLETE**
- Real-device frozen installation: **NOT VALIDATED**

The smallest safe follow-up is a separately reviewed private-resource design
for Red Light's structured settings database, including explicit ownership,
field-level selection, lifecycle/lock handling, and an application path that
does not replace the mixed database. BM-017B does not implement that design.

## Safety checks

The final secret-blind leak scan compared only the ten non-default private
candidate fields against repository files and returned `leak_detected=false`.
The raw evidence directory was deleted and verified absent. No real source
profile mutation occurred, and no destination installation or next milestone
was started.
