# Red Light configuration portability (BM-016)

## 1. Scope and evidence

This report covers the installed **Red Light 2.6.2** add-on
(`plugin.video.redlight`) inspected on macOS on 2026-09-19. The inspection was
read-only. No Kodi process was started, stopped, or reconfigured; no Apple TV or
other physical device was accessed; and no real profile file was written.

The evidence is:

- distributed add-on source under
  `special://home/addons/plugin.video.redlight/`;
- field-name/schema-only inspection of
  `special://profile/addon_data/plugin.video.redlight/`, including SQLite opened
  read-only with `mode=ro&immutable=1`;
- BM-015's implemented package and typed-setting semantics at matrix commit
  `91b41a1`.

No credential value, private account value, database payload, QR payload, or
playback job was printed, copied into this repository, or included below.
Defaults for private fields are deliberately redacted even when the source uses
an empty sentinel.

The classifications mean:

- `PUBLIC_PORTABLE`: semantically an ordinary non-secret preference that looks
  useful across devices. It is **not** necessarily deployable by BM-015 today.
- `PRIVATE_PORTABLE_CANDIDATE`: private/authentication material that BM-017 may
  investigate by field name only; reauthorization remains the safe default.
- `DEVICE_SPECIFIC`: tied to a path, skin/view ID, device capability,
  performance choice, platform behavior, or authorization device.
- `GENERATED_RUNTIME`: Red Light-created display, migration, expiry, or other
  lifecycle state that should be regenerated.
- `DO_NOT_COPY`: state Build Manager should leave unmanaged.
- `UNKNOWN_NEEDS_TESTING`: evidence is insufficient for a safe classification.

Cross-platform confidence is `UNTESTED_CROSS_PLATFORM` unless explicitly
stated otherwise. macOS source inspection is not proof for tvOS, Android TV, or
Fire OS.

## 2. Add-on identity and storage architecture

| Item | Architectural path | Finding |
|---|---|---|
| Add-on | `special://home/addons/plugin.video.redlight/` | ID `plugin.video.redlight`, version `2.6.2`, metadata platform `all` |
| Kodi settings definition | `special://home/addons/plugin.video.redlight/resources/settings.xml` | Only an informational row and an action that opens Red Light's custom settings window |
| Red Light setting definitions | `resources/lib/caches/settings_cache.py::default_settings()` | 508 custom definitions |
| Custom settings UI | `resources/skins/Default/1080i/settings_manager.xml` | Reads and writes Red Light's custom settings layer |
| Real preference store | `special://profile/addon_data/plugin.video.redlight/databases/settings.db` | SQLite table `settings(setting_id, setting_type, setting_default, setting_value)` |
| Kodi-generated settings file | `special://profile/addon_data/plugin.video.redlight/settings.xml` | 78-byte launcher stub; only safe setting ID observed was `label0` |

This distinction controls the BM-016 result. Red Light does **not** expose its
508 substantive preferences as Kodi add-on settings. Its source reads and
writes `settings.db`, then publishes selected rows into transient Kodi window
properties. The custom database contains ordinary preferences, credentials,
derived display-name rows, migration sentinels, and lifecycle state together.

BM-015 supports two mutation forms:

1. selected settings exposed by Kodi's typed `Settings` API; and
2. exact replacement of a file that Build Manager legitimately owns in full.

Neither form safely fits Red Light 2.6.2:

- the typed API cannot address the custom database rows; and
- Build Manager cannot own all of `settings.db`, because replacing it would
  overwrite secrets, device-local values, generated state, and unrelated user
  choices.

Therefore **zero Red Light settings are directly deployable by BM-015 today**,
even though 337 are semantically classified `PUBLIC_PORTABLE`.

### Counts

| Measure | Count |
|---|---:|
| Source-defined settings | 508 |
| `action` | 117 |
| `boolean` | 198 |
| `path` | 16 |
| `string` | 175 |
| Explicit source `name` rows | 2 |
| Additional generated display-name rows in the inspected DB | 70 |
| Total inspected DB rows | 578 |
| Source-defined settings differing from the installed source default | 82 |
| Dynamic default not compared (`default_addon_fanart`) | 1 |

Red Light's `boolean` and `action` values are stored as text in its own schema;
these are Red Light types, not BM-015/Kodi typed-setting declarations.

## 3. Setting classification summary

| Classification | Count | Conclusion |
|---|---:|---|
| `PUBLIC_PORTABLE` | 337 | Ordinary non-secret preferences; candidates only after a safe structured Red Light writer exists |
| `PRIVATE_PORTABLE_CANDIDATE` | 71 | BM-017 evidence candidates; never public; reauthorize unless separately proven safe |
| `DEVICE_SPECIFIC` | 47 | Leave local unless a tested platform/device layer is justified |
| `GENERATED_RUNTIME` | 45 | Regenerate; never declare as desired state |
| `UNKNOWN_NEEDS_TESTING` | 8 | Leave unmanaged pending a focused future test |

The 70 extra database `name` rows are derived display labels and are also
`GENERATED_RUNTIME`; they are not source setting definitions and are excluded
from the 508-row matrix.

Representative public families include content/list behavior, result sorting,
playback behavior, widget preferences, provider selection, notification
preferences, colors, and non-secret cache intervals. Provider enablement and
watched-provider selection may be portable preferences, but they only become
functional when the corresponding account is authorized locally.

Representative device-specific families include download/source paths, Kodi
view IDs, language-invoker behavior, concurrency limits, quality/HDR/Dolby
Vision/codec filters, volume handling, and an authorization device ID.

The complete field-by-field inventory is in Appendix A. “Current differs?” is
only a boolean comparison; no current value is present in this document.

## 4. File and persistent-state inventory

All database paths below are relative to
`special://profile/addon_data/plugin.video.redlight/`.

| Path | Purpose / format | State kind | Secrets or mixed fields? | Whole-file BM ownership | Recommendation |
|---|---|---|---|---|---|
| `databases/settings.db` | SQLite custom settings; 578 rows | User config + auth + generated | Yes, heavily mixed | Unsafe | Structured partial management would be required; never place the file in a public package |
| `databases/navigator.db` | SQLite navigation/menu definitions; 4 rows | Persistent user customization | Content may embed actions/paths | Not established | `UNKNOWN_NEEDS_TESTING`; Red Light backs it up, but that does not make it public desired state |
| `databases/personal_lists.db` | SQLite personal lists; empty in snapshot | User-authored content | Potentially private titles/metadata | No | `DO_NOT_COPY` as build configuration |
| `databases/discover.db` | SQLite saved discover definitions; empty | User-authored/runtime | Potentially private filters/history | No | `UNKNOWN_NEEDS_TESTING`; leave unmanaged |
| `databases/episode_groups.db` | SQLite episode-group choices; empty | User choice | No known secret, but content-specific | No | `UNKNOWN_NEEDS_TESTING`; leave unmanaged |
| `databases/list_sort.db` | SQLite per-list sort specs; 18 rows | Portable-looking preference state | No secret seen at schema level | Not established | `UNKNOWN_NEEDS_TESTING`; absent from Red Light's own backup allowlist |
| `databases/favourites.db` | SQLite favourites | User library/history | Private viewing choices | No | `DO_NOT_COPY` |
| `databases/watched.db` | SQLite watched/progress/status | Playback history and resume state | Private history/timestamps | No | `DO_NOT_COPY` |
| `databases/mdblistcache.db` | MDBList payload, watched/progress/status caches | Remote/account-derived runtime | Account-derived payload | No | `DO_NOT_COPY`; regenerate from service |
| `databases/traktcache.db` | Trakt payload and watched/progress/status caches | Remote/account-derived runtime | Account-derived payload | No | `DO_NOT_COPY`; regenerate |
| `databases/simklcache.db` | Simkl payload and watched/progress/status caches | Remote/account-derived runtime | Account-derived payload | No | `DO_NOT_COPY`; regenerate |
| `databases/punchplaycache.db` | PunchPlay payload and watched/progress/status caches | Remote/account-derived runtime | Account-derived payload | No | `DO_NOT_COPY`; regenerate |
| `databases/maincache.db` | General response/cache entries with expiry | Generated runtime | May contain query/account-derived payload | No | `DO_NOT_COPY` |
| `databases/metacache.db` | Metadata, season metadata, function cache | Generated runtime | Media metadata | No | `DO_NOT_COPY` |
| `databases/debridcache.db` | Hash/debrid availability cache | Generated runtime | Service-derived | No | `DO_NOT_COPY` |
| `databases/external.db` | Scraper results and expiry | Generated runtime | Queries/results may be private | No | `DO_NOT_COPY` |
| `databases/lists.db` | Expiring list cache | Generated runtime | May be account-derived | No | `DO_NOT_COPY` |
| `databases/tmdb_lists.db` | Expiring TMDb list cache | Generated runtime | May be account-derived | No | `DO_NOT_COPY` |
| `databases/random_widgets.db` | Random-widget cache | Generated runtime | No need to preserve | No | `DO_NOT_COPY` |
| `settings.xml` | Kodi launcher stub XML | Generated/non-substantive | No useful desired state | No | `DO_NOT_COPY` |
| `qr.png`, `qr_<hash>_<timestamp>.png` | Generated QR images | Transient auth/help artifact | Potentially sensitive URL payload | No | `DO_NOT_COPY`; never decode for BM-016 |
| `playback_remote/` | Timestamp/PID JSON work queue when populated | Transient playback/scrobble jobs | Can contain session and playback data | No | `DO_NOT_COPY`; producers/consumers delete jobs |

The source uses SQLite WAL mode and live service processes. Even a database
that contained only portable data would require lifecycle-safe structured
handling; raw replacement while Red Light is active is not justified.

Two TMDb Helper player files named `redlight.auto.json` and
`redlight.select.json` were found under TMDb Helper's own profile data. Their
safe key names are `name`, `plugin`, `priority`, `is_resolvable`, `play_movie`,
and `play_episode`. They are TMDb Helper-owned integration files, not Red Light
configuration, so BM-016 does not claim them. A separate owner/content review
would be required before whole-file management.

## 5. Authentication/private-state matrix

All fields in this section live in `databases/settings.db`. “Current evidence”
reports only whether a non-sentinel user-specific field was detected or whether
the field is supplied as a bundled add-on default. It never reports a value.

| Service/purpose | Field/key names | Current evidence | Lifecycle/device clues | BM-017 conclusion |
|---|---|---|---|---|
| MDBList | `mdblist.user`, `mdblist.client`, `mdblist.token`, `mdblist.refresh` | User, token, and refresh present; client supplied by add-on | Token/refresh lifecycle; no device binding proven | Candidate by field name only; reauthorization is safer until a disposable restore test proves otherwise |
| PunchPlay | `punchplay.user`, `punchplay.client`, `punchplay.token`, `punchplay.refresh`, `punchplay.expires`, `punchplay.device_id` | No user-specific authorization detected; client supplied by add-on | Explicit device ID and expiry | Do not copy device ID/expiry; reauthorize |
| Simkl | `simkl.user`, `simkl.client`, `simkl.token` | No user-specific authorization detected; client supplied by add-on | Token lifecycle | Private candidate only; reauthorize by default |
| WeTrakr | `wetrakr.user`, `wetrakr.token` | No user-specific authorization detected | Token lifecycle unknown | Private candidate only |
| Trakt | `trakt.user`, `trakt.client`, `trakt.secret`, `trakt.token`, `trakt.refresh`, `trakt.expires` | No user-specific authorization detected; client/secret supplied by add-on | OAuth token, refresh, expiry | Add-on defaults regenerate; test user tokens only in BM-017 or reauthorize |
| TMDb account/API | `tmdb_api`, `tmdb.lists_read_token`, `tmdb.token`, `tmdb.username`, `tmdb.account_id`, `tmdb.session_id`, `tmdb.account_session_id` | API defaults supplied by add-on; no user account detected | Session/account lifecycle | Never public; regenerate shipped defaults and reauthorize account sessions |
| Metadata/AI APIs | `fanarttv_api`, `omdb_api`, `rpdb_api`, `google_api`, `groq_api` | Some defaults supplied by add-on; no user-specific value reported | Static-key-looking, but revocation/ownership unknown | Possible private overlay only for user-owned keys after BM-017 review |
| Real-Debrid | `rd.token`, `rd.account_id`, `rd.client_id`, `rd.refresh`, `rd.secret` | No user-specific authorization detected | OAuth-style refresh/client fields | Reauthorize unless BM-017 proves a complete portable set |
| Premiumize | `pm.token`, `pm.account_id` | Both user-specific fields present | Token expiry/binding not established | Private candidate; disposable proof required |
| AllDebrid | `ad.token`, `ad.account_id` | No user-specific authorization detected | Token lifecycle unknown | Private candidate; reauthorize by default |
| Offcloud | `oc.token`, `oc.account_id` | No user-specific authorization detected | Token lifecycle unknown | Private candidate; reauthorize by default |
| TorBox | `tb.token` | User-specific token present | Token lifecycle unknown | Private candidate; disposable proof required |
| EasyNews | `easynews_user`, `easynews_password` | No user-specific authorization detected | Static credentials, highly sensitive | Possible private overlay only if explicit credential storage is accepted; otherwise prompt/login |
| AIOStreams | `aiostreams.profiles`, `aiostreams.custom_url`, `aiostreams.username`, `aiostreams.password` | No values reported | `profiles` is composite JSON and can contain credentials/endpoints | Never public or whole-file; structured BM-017 analysis required |
| NZB indexers | `nzb1.url`, `nzb1.key`, `nzb2.url`, `nzb2.key`, `nzb3.url`, `nzb3.key` | No values reported | Endpoint/key pairs may identify private services | Possible private overlay only after explicit review |
| OpenSubtitles | `playback.opensubs_api_key`, `playback.opensubs_username`, `playback.opensubs_password`, `playback.opensubs_token` | API default may be add-on supplied; no user login reported | Token is generated from credentials | Prefer re-login; do not copy generated token |
| Custom provider endpoints | `comet.custom_url`, `torrentio.custom_url`, `torz.custom_url`, `piratebay.custom_url`, `mediafusion.custom_url`, `zilean.custom_url` | No values reported | URLs may embed private hosts or credentials | Treat as private until sanitized and tested |

Red Light's own import/export warning says its backup can contain API keys,
tokens, and account logins and that imported OAuth accounts may require
reauthorization. Its whole-database backup behavior is useful evidence that
some state is portable-looking, but it is not evidence that copying every row
is safe or appropriate for Build Manager.

## 6. Controlled-validation result

No Red Light mutation experiment was started. This is a deliberate result of
the storage discovery, not an isolation failure:

1. A fresh Red Light installation would expose only the launcher action through
   Kodi's typed Settings API.
2. The representative non-secret candidates are custom SQLite rows, so applying
   them with BM-015's typed mechanism would not reach the state Red Light reads.
3. Testing a whole-file package would require claiming ownership of a mixed
   secret-bearing database and was therefore prohibited.
4. Building a Red-Light-specific or arbitrary SQLite writer would be production
   architecture outside BM-016.

The existing BM-015 disposable validation proves the typed mechanism and
restart persistence for a real native Kodi settings add-on. It does **not**
prove Red Light portability. Red Light restart persistence and structured row
application remain `UNKNOWN_NEEDS_TESTING` for a future explicitly scoped
adapter/import task.

The real Kodi profile was only read. SQLite inspection was immutable/read-only;
no secret-bearing file was dumped; no QR image was viewed; and no profile or
device process was controlled.

## 7. Public BM-015 package candidates

### Current recommendation: create no Red Light package

A `redlight-common` package created now would be misleading: BM-015 cannot
express Red Light custom database rows, and declaring `settings.db` as a managed
file would violate BM-015's whole-file ownership rule.

After a separately reviewed, lifecycle-safe structured Red Light writer exists,
the minimal useful shape would be one conceptual `redlight-common` layer
containing only explicitly selected `PUBLIC_PORTABLE` fields. Values should
come from reviewed desired-state choices, not from blindly exporting the
current database. No `redlight-tvos`, `redlight-android`, or per-device layer is
justified yet; the current device-specific classifications identify what would
need testing, not packages that should be created.

For every future public field, the manifest—not the data file—must declare
ownership. Authentication fields, generated labels/migrations, paths, caches,
and history remain outside that scope.

## 8. BM-017 private-overlay input

BM-017 should use the authentication matrix above as its bounded field-name
inventory. Its safest initial questions are:

1. For each service, does a clean disposable Red Light install accept copied
   user authorization fields without a device code, refresh failure, or account
   corruption?
2. Which fields form an indivisible credential set?
3. Which services explicitly bind tokens to a device/client or require expiry
   refresh?
4. Can Red Light's own import path safely import a structured, service-scoped
   subset, or does it only replace the mixed database?

BM-017 should not copy shipped client/API defaults; the installed add-on already
regenerates them. It should not copy device IDs, expiry/display rows, QR files,
provider caches, or generated access tokens where reauthorization is safer.
No private-overlay implementation was started in BM-016.

## 9. Do-not-manage state

Build Manager should leave the following state alone:

- every cache database and provider watched/progress cache: remote or generated
  state will refresh and may contain private activity;
- `watched.db`, favourites, personal lists, and history-like records: user data,
  not declarative build configuration;
- QR images and `playback_remote/`: transient and potentially sensitive;
- Kodi's launcher `settings.xml`: it contains no useful Red Light preference;
- all of `settings.db` as a file: mixed authority and secret boundary;
- derived `*_name` rows and migration sentinels: Red Light must regenerate them;
- expiry timestamps, refresh lifecycle state, and authorization device IDs;
- shipped client/API defaults: use the copy bundled with the installed add-on.

## 10. Cross-platform conclusions

Evidence supporting likely portability:

- the add-on declares platform `all`;
- its default internal locations use Kodi `special://profile/` paths; and
- ordinary preferences are stored as simple text rows in a schema shared by the
  installed source.

Limits and platform-specific risks:

- user-selected folders may contain macOS, Android, Fire OS, tvOS, hostname, or
  network-share paths;
- view IDs and presentation choices depend on the installed skin;
- concurrency, quality, HDR/Dolby Vision/codec, volume, and external-scraper
  choices may legitimately differ by hardware/platform;
- SQLite format compatibility does not make a live mixed database safe to copy;
- metadata platform `all` proves install compatibility, not settings
  portability.

No live tvOS, Android TV/Shield, or Fire OS test was performed. All such claims
remain `UNTESTED_CROSS_PLATFORM`.

## 11. Remaining unknowns

- Whether Red Light will expose a stable, supported structured import/set API
  suitable for Build Manager without direct database editing.
- Restart persistence and side effects of applying individual custom setting
  rows through such an API.
- Portability and device binding of every authentication service.
- Whether `navigator.db`, `discover.db`, `episode_groups.db`, or `list_sort.db`
  should ever be declarative desired state rather than user data.
- Which device-specific preferences genuinely need platform layers.
- How a later Red Light version will migrate the 2.6.2 settings schema.

These unknowns do not change the BM-016 conclusion and should not be eliminated
by broad exploration.

## 12. Recommended next steps

1. Accept BM-016's no-package conclusion for BM-015 as currently implemented.
2. Keep BM-017 strictly focused on the named authentication fields and
   disposable reauthorization/restore evidence; do not copy a whole database.
3. If public Red Light preference deployment remains desirable, assign a
   separate task to evaluate a narrowly scoped structured adapter or Red
   Light-native import surface with concurrency, schema-version, sanitization,
   idempotency, and restart tests.
4. Only after that mechanism is proven, select a small reviewed subset of
   `PUBLIC_PORTABLE` settings for `redlight-common`; add platform/device layers
   only when physical-device evidence demonstrates a real difference.

## Appendix A — Complete source setting inventory

| Key | Red Light type | Default | Current differs? | Sensitivity | Classification | Purpose / recommended strategy |
|---|---|---|---:|---|---|---|
| `auto_start_redlight` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `addon_icon_choice` | `string` | `resources/media/addon_icons/icon.png` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `default_addon_fanart` | `path` | `<runtime-derived>` | not compared | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `limit_concurrent_threads` | `boolean` | `false` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `max_threads` | `action` | `20` | yes | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `window_theme` | `string` | `CC1F2020` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `window_theme_opacity` | `string` | `CC` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `watched_indicators` | `action` | `0` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `mdblist.user` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `mdblist.client` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `mdblist.token` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `mdblist.refresh` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `mdblist.sync_interval` | `action` | `60` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `mdblist.refresh_widgets` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `punchplay.user` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `punchplay.client` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `punchplay.token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `punchplay.refresh` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `punchplay.expires` | `string` | `0` | no | non-secret | GENERATED_RUNTIME | lifecycle/expiry state; Regenerate; do not manage |
| `punchplay.device_id` | `string` | `empty_setting` | no | path/device | DEVICE_SPECIFIC | authorization device identifier; Do not copy; reauthorize |
| `punchplay.sync_interval` | `action` | `60` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `punchplay.refresh_widgets` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `simkl.user` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `simkl.client` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `simkl.token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `simkl.sync_interval` | `action` | `60` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `simkl.refresh_widgets` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `simkl.cm_menu_migrated` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `mdblist.cm_menu_migrated` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `punchplay.cm_menu_migrated` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `external_scraper.cm_menu_migrated` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `cm_manager_order_migrated` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `cm_manager_order_migrated_v2` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `cm_manager_order_migrated_v3` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `wetrakr.user` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `wetrakr.token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `wetrakr.scrobble` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `wetrakr.scrobble_threshold` | `action` | `90` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.sync_interval` | `action` | `60` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.refresh_widgets` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `datetime.offset` | `action` | `0` | yes | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `movie_download_directory` | `path` | `special://profile/addon_data/plugin.video.redlight/Movies Downloads/` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `tvshow_download_directory` | `path` | `special://profile/addon_data/plugin.video.redlight/TV Show Downloads/` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `premium_download_directory` | `path` | `special://profile/addon_data/plugin.video.redlight/Premium Downloads/` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `image_download_directory` | `path` | `special://profile/addon_data/plugin.video.redlight/Image Downloads/` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `import_export_directory` | `path` | `special://profile/addon_data/plugin.video.redlight/Import Export/` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `extras.enable_extra_ratings` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.enabled_ratings` | `string` | `Meta, Tom/Critic, Tom/User, IMDb, TMDb` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.enable_item_ratings` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.enable_scrollbars` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `media_open_action_movie` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `media_open_action_tvshow` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `media_open_action_skip_inprogress_movie` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `media_open_action_skip_inprogress_tvshow` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ai_model.order` | `string` | `gemini-3.1-flash-lite,llama-3.3-70b-versatile,gemma-4-31b-it,llama-3.1-8b-instant` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ai_model.limit` | `action` | `15` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `paginate.lists` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `paginate.limit_addon` | `action` | `20` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `paginate.limit_widgets` | `action` | `20` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `paginate.catalogue_limit_addon` | `action` | `20` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `paginate.catalogue_limit_widgets` | `action` | `20` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `paginate.jump_to` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ignore_articles` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `search.history_sort` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `recommend_service` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `recommend_seed` | `action` | `5` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `mpaa_region` | `string` | `US` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `meta_language` | `string` | `en` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `lists_cache_duraton` | `string` | `24` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tmdb.premieres_sort` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tv_progress_location` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `show_specials` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `exclude_specials_progress` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `use_season_name` | `boolean` | `false` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `default_all_episodes` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `avoid_episode_spoilers` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `show_loading_plot` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `include_anime_tvshow` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `show_public_calendars` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `public_calendar_include_anime` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `public_calendar_max_items` | `action` | `250` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `public_calendar_cache_list` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `anime.seasons_episode_group_fallback` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `show_unaired_watchlist` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `meta_filter` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `use_viewtypes` | `boolean` | `true` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `manual_viewtypes` | `boolean` | `false` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `view.main` | `string` | `55` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `view.movies` | `string` | `500` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `view.tvshows` | `string` | `500` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `view.seasons` | `string` | `55` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `view.episodes` | `string` | `55` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `view.episodes_single` | `string` | `55` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `view.premium` | `string` | `55` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `sort.progress` | `action` | `0` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `sort.watched` | `action` | `0` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `sort.default.movies` | `string` | `title:asc` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `sort.default.movies_name` | `name` | `Title (ascending)` | yes | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `sort.default.shows` | `string` | `title:asc` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `sort.default.shows_name` | `name` | `Title (ascending)` | yes | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `personal_list.sort_unseen_to_top` | `boolean` | `true` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `personal_list.highlight_unseen` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `personal_list.unseen_highlight` | `string` | `FF4DDBFF` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `personal_list.show_author` | `boolean` | `true` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `widget_refresh_timer` | `string` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `widget_refresh_notification` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `widget_hide_watched` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `widget_hide_watched_fill` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `widget_hide_next_page` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rpdb_enabled` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rpdb_format` | `string` | `` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `context_menu.enabled` | `string` | `extras,options,playback_options,external_scraper_settings,browse_movie_set,browse_seasons,browse_episodes,recommended,related,more_like_this,similar,in_trakt_list,mdblist_manager,punchplay_manager,simkl_manager,tmdb_manager,trakt_manager,personal_manager,favorites_manager,mark_watched,unmark_previous_episode,exit,refresh,reload` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `context_menu.order` | `string` | `extras,options,playback_options,external_scraper_settings,browse_movie_set,browse_seasons,browse_episodes,recommended,related,more_like_this,similar,in_trakt_list,mdblist_manager,punchplay_manager,simkl_manager,tmdb_manager,trakt_manager,personal_manager,favorites_manager,mark_watched,unmark_previous_episode,exit,refresh,reload` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `single_ep_display` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `single_ep_display_widget` | `action` | `1` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `single_ep_widget_omit_tvshowtitle` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `single_ep_widget_omit_season_episode` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `single_ep_unwatched_episodes` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `single_ep_unwatched_in_title` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.method` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.sort_type` | `action` | `0` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.sort_order` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.limit_history` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.limit` | `action` | `20` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.include_unwatched` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.include_airdate` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.airing_today` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nextep.include_unaired` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.flatten_episodes` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.calendar_display` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.calendar_display_widget` | `action` | `1` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.calendar_sort_order` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.calendar_date_labels` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.calendar_previous_days` | `action` | `7` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.calendar_future_days` | `action` | `7` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `trakt.user` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `trakt.client` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `trakt.secret` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `tmdb_api` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `tmdb.lists_read_token` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `tmdb.token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `tmdb.username` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `fanarttv_api` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `omdb_api` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `rpdb_api` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `google_api` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `groq_api` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `provider.external` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `external_scraper.name` | `string` | `empty_setting` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `external_scraper.slot1.module` | `string` | `empty_setting` | yes | non-secret | UNKNOWN_NEEDS_TESTING | installed scraper binding; Leave unmanaged pending focused test |
| `external_scraper.slot1.name` | `string` | `empty_setting` | yes | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `external_scraper.slot1.enabled` | `boolean` | `false` | yes | non-secret | UNKNOWN_NEEDS_TESTING | installed scraper binding; Leave unmanaged pending focused test |
| `external_scraper.slot2.module` | `string` | `empty_setting` | no | non-secret | UNKNOWN_NEEDS_TESTING | installed scraper binding; Leave unmanaged pending focused test |
| `external_scraper.slot2.name` | `string` | `empty_setting` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `external_scraper.slot2.enabled` | `boolean` | `false` | no | non-secret | UNKNOWN_NEEDS_TESTING | installed scraper binding; Leave unmanaged pending focused test |
| `external_scraper.slot3.module` | `string` | `empty_setting` | no | non-secret | UNKNOWN_NEEDS_TESTING | installed scraper binding; Leave unmanaged pending focused test |
| `external_scraper.slot3.name` | `string` | `empty_setting` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `external_scraper.slot3.enabled` | `boolean` | `false` | no | non-secret | UNKNOWN_NEEDS_TESTING | installed scraper binding; Leave unmanaged pending focused test |
| `external_scraper.run_mode` | `action` | `1` | no | non-secret | UNKNOWN_NEEDS_TESTING | installed scraper binding; Leave unmanaged pending focused test |
| `provider.internal` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.prefer_internal` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.comet` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `comet.url` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `comet.custom_url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `internal.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `indexer.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `indexer.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `indexer.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `site.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `site.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `site.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `site.strict_filenames` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `comet.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `comet.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.torrentio` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `torrentio.url` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `torrentio.custom_url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `torrentio.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `torrentio.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.torz` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `torz.url` | `action` | `1` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `torz.custom_url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `torz.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `torz.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.nyaa` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nyaa.category` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nyaa.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nyaa.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.animetosho` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `animetosho.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `animetosho.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.piratebay` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `piratebay.url` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `piratebay.custom_url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `provider.mediafusion` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `mediafusion.url` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `mediafusion.custom_url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `provider.zilean` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `zilean.url` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `zilean.custom_url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `migration.external_scraper_slots_v160` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `migration.cache_check_pm_oc_tb_v129e` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `migration.ad_cache_check_removed_v173` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `migration.rd_cache_check_removed_v243` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `migration.internal_site_defaults_v245` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `migration.simkl_client_v246` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `migration.simkl_client_v250` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `migration.my_content_nav_mode_v136` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `migration.unified_list_sort` | `boolean` | `false` | yes | non-secret | GENERATED_RUNTIME | migration sentinel; Regenerate; do not manage |
| `rd.token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `rd.enabled` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rd.cache_check` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rd.account_id` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `store_resolved_to_cloud.real-debrid` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.rd_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rd_cloud.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rd_cloud.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.rd_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.rd_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.sort_rdcloud_first` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rd.priority` | `action` | `10` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rd.alternate_base_url` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rd.free_active_slot` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `pm.token` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `pm.enabled` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `pm.cache_check` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `pm.include_uncached` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `pm.account_id` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `store_resolved_to_cloud.premiumize.me` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.pm_cloud` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `pm_cloud.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `pm_cloud.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.pm_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.pm_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.sort_pmcloud_first` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `pm.priority` | `action` | `10` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ad.token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `ad.enabled` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ad.cache_check` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ad.account_id` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `store_resolved_to_cloud.alldebrid` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.ad_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ad_cloud.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ad_cloud.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.ad_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.ad_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.sort_adcloud_first` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `ad.priority` | `action` | `10` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `oc.token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `oc.account_id` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `oc.enabled` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `oc.cache_check` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `oc.include_uncached` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `store_resolved_to_cloud.offcloud` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `oc.notify_cloud_ready` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.oc_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `oc_cloud.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `oc_cloud.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.oc_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.oc_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.sort_occloud_first` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `oc.priority` | `action` | `10` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tb.token` | `string` | `[redacted sentinel/default]` | yes | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `tb.enabled` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tb.cache_check` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tb.include_uncached` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `store_resolved_to_cloud.torbox` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tb.notify_cloud_ready` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.tb_cloud` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tb_cloud.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tb_cloud.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.tb_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.tb_cloud` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.sort_tbcloud_first` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tb.priority` | `action` | `10` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.easynews` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `services.expiry_alert_days` | `action` | `7` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `services.expiry_alert_state` | `string` | `{}` | no | non-secret | GENERATED_RUNTIME | lifecycle/expiry state; Regenerate; do not manage |
| `services.expiry_alert.ad` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `services.expiry_alert.easynews` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `services.expiry_alert.oc` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `services.expiry_alert.pm` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `services.expiry_alert.rd` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `services.expiry_alert.tb` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews_user` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `easynews_password` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `easynews.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.filter_lang` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.exclude_adult` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.lang_filters` | `string` | `eng` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.refresh_credentials` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.lang_include_unknown` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.fallback_search` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.search_width` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.easynews` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.easynews` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `en.priority` | `action` | `7` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.aiostreams` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `aiostreams.instance` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `aiostreams.profiles` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `aiostreams.custom_url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `aiostreams.username` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `aiostreams.password` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `aiostreams.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `aiostreams.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `aiostreams.preserve_order` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.aiostreams` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.aiostreams` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `aio.priority` | `action` | `7` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.aiostreams_highlight` | `string` | `FF00D4FF` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.folders` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `folders.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `folders.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.folders` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.folders` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.sort_folders_first` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.folders_ignore_filters` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `folders.priority` | `action` | `6` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.nzb` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nzb1.enabled` | `boolean` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb1.label` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb1.url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb1.key` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb2.enabled` | `boolean` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb2.label` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb2.url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb2.key` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb3.enabled` | `boolean` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb3.label` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb3.url` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb3.key` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `nzb.title_filter` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nzb.same_title_year` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nzb.title_filter_episode` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nzb.fallback_search` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nzb.search_width` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `check.nzb` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay.nzb` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `nzb.priority` | `action` | `7` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.nzb_highlight` | `string` | `FFD4A017` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.timeout` | `action` | `20` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.list_format` | `string` | `List` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `results.show_episode_title` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.cache_ignored` | `action` | `1` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.cache_ignored.order` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.imdb_year` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.imdb_year.order` | `action` | `1` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.with_all` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.with_all.order` | `action` | `2` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.episode_group` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.episode_group.order` | `action` | `3` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.ignore_filters` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.ignore_filters.order` | `action` | `4` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.full_scrape` | `action` | `2` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.full_scrape.order` | `action` | `5` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.sort_order_display` | `string` | `Quality, Size, Provider` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.quality_sort_order` | `string` | `4K, 1080p, 720p, SD` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.filter_size_method` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.line_speed` | `action` | `25` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `results.movie_size_max` | `action` | `10000` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.episode_size_max` | `action` | `3000` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.movie_size_min` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.episode_size_min` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.size_unknown` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.size_sort_weighted` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.size_sort_direction` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.uncached_min_seeders` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.limit_number_quality` | `string` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.limit_number_total` | `string` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results.include.unknown.size` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `filter.include_prerelease` | `action` | `0` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `filter.hevc` | `action` | `0` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `filter.hevc.max_quality` | `action` | `4K` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `filter.hevc.max_autoplay_quality` | `action` | `4K` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `filter.3d` | `action` | `0` | yes | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `filter.hdr` | `action` | `0` | yes | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `filter.dv` | `action` | `0` | yes | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `filter.av1` | `action` | `0` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `filter.enhanced_upscaled` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `filter.sort_to_top` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `filter.prefer_release_groups` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `filter.preferred_filters` | `string` | `empty_setting` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `filter_audio` | `string` | `empty_setting` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `highlight.type` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.easynews_highlight` | `string` | `FF00B3B2` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.debrid_cloud_highlight` | `string` | `FF7A01CC` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.folders_highlight` | `string` | `FFB36B00` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.rd_highlight` | `string` | `FF3C9900` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.pm_highlight` | `string` | `FFFF3300` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.ad_highlight` | `string` | `FFE6B800` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.oc_highlight` | `string` | `FF5C6BC0` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `provider.tb_highlight` | `string` | `FF01662A` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `scraper_4k_highlight` | `string` | `FFFF00FE` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `scraper_1080p_highlight` | `string` | `FFE6B800` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `scraper_720p_highlight` | `string` | `FF3C9900` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `scraper_SD_highlight` | `string` | `FF0166FF` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `scraper_single_highlight` | `string` | `FF008EB2` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `scraper_total_highlight` | `string` | `FFFF33AE` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `highlight.scrape_progress_colours` | `boolean` | `true` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `highlight.tint_focused_background` | `boolean` | `true` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `highlight.background_opacity` | `string` | `66` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `highlight.background_opacity_name` | `string` | `40%` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `auto_play_movie` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results_quality_movie` | `string` | `SD, 720p, 1080p, 4K` | yes | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `autoplay_quality_movie` | `string` | `SD, 720p, 1080p, 4K` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `autoplay.movie_size_max` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `auto_resume_movie` | `action` | `0` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `stinger_alert.show` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `stinger_alert.window_percentage` | `action` | `90` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `stinger_alert.alert_timing` | `action` | `1` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `auto_play_episode` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `results_quality_episode` | `string` | `SD, 720p, 1080p, 4K` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `autoplay_quality_episode` | `string` | `SD, 720p, 1080p, 4K` | yes | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `autoplay.episode_size_max` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay_next_episode` | `boolean` | `false` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay_alert_method` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay_default_action` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay_next_window_percentage` | `action` | `95` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay_alert_timing` | `action` | `3` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay_skip_intro` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `skip_intro_all_episodes` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoplay_watching_check` | `action` | `3` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoscrape_next_episode` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoscrape_next_window_percentage` | `action` | `95` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoscrape_alert_timing` | `action` | `3` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `autoscrape_confirm` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `auto_resume_episode` | `action` | `0` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `playback.limit_resolve` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.playback_method` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.playback_method_retries` | `action` | `1` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `easynews.playback_method_limited` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `playback.volumecheck_enabled` | `boolean` | `false` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `playback.volumecheck_percent` | `action` | `50` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `playback.auto_enable_subs` | `boolean` | `false` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `playback.opensubs_api_key` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `playback.opensubs_username` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `playback.opensubs_password` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `playback.subs_source` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `playback.submaker_manifest` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `playback.submaker_language` | `action` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `playback.submaker_prefer_local` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `playback.subs_show_notifications` | `boolean` | `true` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tmdb.account_id` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `tmdb.session_id` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `tmdb.account_session_id` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `reuse_language_invoker` | `string` | `true` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `addon_icon_choice_name` | `string` | `icon.png` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `widget_refresh_timer_name` | `string` | `Off` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `mpaa_region_display_name` | `string` | `United States` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `meta_language_display_name` | `string` | `English` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `lists_cache_duraton_display_name` | `string` | `1 Day` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `results.limit_number_quality_name` | `string` | `Off` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `results.limit_number_total_name` | `string` | `Off` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `rpdb_format_name` | `string` | `Default` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `window_theme_contrast` | `string` | `FF4a4347` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `window_theme_name` | `string` | `Dark` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `window_theme_opacity_name` | `string` | `80%` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `external_scraper.module` | `string` | `empty_setting` | no | non-secret | UNKNOWN_NEEDS_TESTING | installed scraper binding; Leave unmanaged pending focused test |
| `trakt.next_daily_clear` | `string` | `0` | no | non-secret | GENERATED_RUNTIME | lifecycle/expiry state; Regenerate; do not manage |
| `trakt.expires` | `string` | `0` | no | non-secret | GENERATED_RUNTIME | lifecycle/expiry state; Regenerate; do not manage |
| `trakt.refresh` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `trakt.token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `playback.opensubs_token` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `tmdblist.list_sort` | `string` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `tmdblist.list_sort_name` | `string` | `Title` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `personal_list.list_sort` | `string` | `0` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `personal_list.list_sort_name` | `string` | `Title` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `rd.client_id` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `rd.refresh` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `rd.secret` | `string` | `[redacted sentinel/default]` | no | secret/private | PRIVATE_PORTABLE_CANDIDATE | credential, private identifier, or private endpoint; BM-017 evidence only; reauthorize unless proven |
| `results.sort_order` | `string` | `1` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `folder1.display_name` | `string` | `Folder 1` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `folder1.movies_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder1.tv_shows_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder2.display_name` | `string` | `Folder 2` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `folder2.movies_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder2.tv_shows_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder3.display_name` | `string` | `Folder 3` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `folder3.movies_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder3.tv_shows_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder4.display_name` | `string` | `Folder 4` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `folder4.movies_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder4.tv_shows_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder5.display_name` | `string` | `Folder 5` | no | non-secret | GENERATED_RUNTIME | derived display label; Regenerate; do not manage |
| `folder5.movies_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `folder5.tv_shows_directory` | `path` | `None` | no | path/device | DEVICE_SPECIFIC | filesystem, skin, or platform binding; Leave local; layer only after platform test |
| `extras.enabled` | `string` | `2050,2051,2052,2053,2054,2055,2056,2057,2058,2059,2060,2061,2062,2063,2064,2065,2066` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.order` | `string` | `2050,2051,2052,2053,2054,2055,2056,2057,2058,2059,2060,2061,2062,2063,2064,2065,2066` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.enabled` | `string` | `cache_ignored,imdb_year,with_all,episode_group,ignore_filters,full_scrape` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `rescrape.order` | `string` | `cache_ignored,imdb_year,with_all,episode_group,ignore_filters,full_scrape` | yes | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.tvshow.button10` | `string` | `tvshow_browse` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.tvshow.button11` | `string` | `show_trailers` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.tvshow.button12` | `string` | `show_keywords` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.tvshow.button13` | `string` | `show_images` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.tvshow.button14` | `string` | `show_extrainfo` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.tvshow.button15` | `string` | `show_genres` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.tvshow.button16` | `string` | `play_nextep` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.tvshow.button17` | `string` | `show_options` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.movie.button10` | `string` | `movies_play` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.movie.button11` | `string` | `show_trailers` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.movie.button12` | `string` | `show_keywords` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.movie.button13` | `string` | `show_images` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.movie.button14` | `string` | `show_extrainfo` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.movie.button15` | `string` | `show_genres` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.movie.button16` | `string` | `show_director` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
| `extras.movie.button17` | `string` | `show_options` | no | non-secret | PUBLIC_PORTABLE | ordinary user preference; Future structured writer; no BM-015 package today |
