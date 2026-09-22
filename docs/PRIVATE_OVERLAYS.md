# BM-017A Private/Auth Overlay Architecture

Status: BM-017A foundation complete. This document defines the secure
application boundary; it does not authorize or perform capture from the real
Family Room profile.

## Boundary

The public frozen build remains reproducible and shareable. It contains the
software graph, public configuration packages, public setting ownership, and
public private-setting declarations. It never contains private values.

The private overlay is a separately supplied artifact:

```text
public frozen build + user-supplied private overlay = ready-to-use state
```

Private values must not enter Git, a public manifest, a public configuration
package, an artifact ZIP, logs, `.agent/*`, or either durable BM-020/BM-022
transaction. BM-017A only provides the application and local-storage
foundation. Real Family Room private/auth capture remains separately
authorized work.

## Public declarations and ownership

`config.private_settings` is a public declaration list. Each declaration names
the explicit target namespace (`addon` or `skin`), add-on ID and setting ID,
one BM-015 typed setting type (`string`, `bool`, `int`, or `number`), whether
the value is required or optional, and a sensitivity class (`secret`,
`credential`, `token`, or `private_identifier`). The declaration contains no
value.

Overlay entries must match a declaration exactly. An undeclared entry,
duplicate target, wrong type, missing required entry, or build/overlay identity
mismatch fails closed before any Kodi mutation.

A private declaration may intentionally overlap a public managed setting only
when that private target is explicitly declared. Build Manager applies public
configuration first and the validated private value second, making the private
value authoritative for that declared target. An undeclared private value
cannot win by last-writer-wins behavior.

## Overlay format

The version-1 local JSON format is:

```json
{
  "schema_version": 1,
  "overlay_id": "family-room-private",
  "target_build_id": "eric-main",
  "entries": [
    {
      "target": "addon",
      "addon_id": "plugin.video.example",
      "key": "api_token",
      "type": "string",
      "value": "user-supplied-value"
    }
  ]
}
```

The format is canonicalized with sorted JSON keys and compact separators. A
SHA-256 digest of that canonical representation is the overlay fingerprint.
The fingerprint is an integrity/change identity, not encryption and not a
secret-value hiding mechanism. The serialized value is never logged or copied
into a result or transaction.

## Storage and import

BM-017A separates an explicit import artifact from active local storage.

- `PrivateOverlayStore.import_file(path)` validates a user-supplied artifact
  and atomically installs it into active storage.
- Active storage is profile-local:
  `special://profile/addon_data/script.build.manager/private_overlays/`.
- The overlay file is written with mode `0600` and its directory with mode
  `0700` where supported.
- The store rejects non-local profile paths, malformed JSON, unsupported
  schemas, unsafe identifiers, and mismatched file/overlay identity.
- Active storage is outside the repository, public build directory, frozen
  artifact store, and add-on installation package.

The initial backend is restrictive plaintext JSON. BM-017A does not claim
encryption at rest and does not invent cryptography. The storage interface is
the seam for a future OS-keychain or platform-approved encrypted backend. No
cloud synchronization is implemented.

## Application and verification

The existing BM-015 `ConfigurationManager` and typed `ConfigurationBackend`
remain the only settings application engine. Private application uses its
narrow typed-setting seam after public package application:

1. updater quarantine, when owned by BM-022;
2. exact frozen software installation;
3. public BM-015 configuration;
4. validated private overlay settings;
5. required restart/resume;
6. post-restart revalidation;
7. final validation and updater-policy restoration.

Each private setting is read before mutation, written only when drifted, and
read back through the same typed backend. Private result records contain only
target identity, status, changed/verified flags, and a generic safe detail.
Expected and actual private values are not returned. Backend exceptions are
not copied into private result messages.

## Restart and durable transactions

BM-020 restart transactions and BM-022 frozen-install transactions persist
only `private_overlay_id`, `private_overlay_fingerprint`, and
`private_overlay_required`. They never persist entries or values. The ordinary
public desired-state fingerprint continues to exclude private values.

After restart, preview and resume reopen the active overlay through the
storage abstraction and compare the safe identity. Missing required state or
a changed fingerprint enters `NEEDS_ATTENTION` before private mutation. The
updater guard remains the precondition for BM-022 resume.

## Missing overlay and recovery

Software completion and ready-to-use completion are separate outcomes. A
missing optional overlay is a safe no-op. A missing required overlay fails
preflight with `PRIVATE_OVERLAY_REQUIRED`; software may remain valid, but
ready-to-use completion is not claimed. No empty or default credential is
invented.

Malformed storage, ownership conflicts, fingerprint drift, private read-back
failure, and resumed overlay absence fail closed. Explicit recovery/abandon
does not print, clear, or expose private values.

## Logging and future capture boundary

Operation and failure messages may identify the add-on ID, setting ID,
operation, and classification. They may not include a private value,
expected/actual value, serialized overlay, or credential-bearing exception.
The disposable regression fixture uses the recognizable marker
`BM017_TEST_SECRET_DO_NOT_LOG` and asserts that it does not appear in safe
results, errors, or durable transaction files.

Future authorized capture from a Kodi profile and user-provided import both
must produce this same validated overlay schema. BM-017A implements only the
import/storage/application contract. It does not access private Family Room
files, account data, tokens, credentials, or addon data.
