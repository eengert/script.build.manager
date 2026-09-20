"""
Build Manager configuration package deployment (BM-015).

Public API
----------
ConfigPackageLoader(packages_root)
    .load_package(package_id) -> ConfigPackage
        Parse and validate one embedded configuration package.
    .resolve(config) -> EffectiveConfiguration
        Load every package named by a ConfigDeclarations block, overlay them in
        declared order, and validate the result against the manifest's declared
        ownership. Pure — no Kodi access, no mutation.

ConfigurationManager(backend)
    .apply(effective) -> ConfigApplyResult
        Apply a fully-resolved EffectiveConfiguration through a
        ConfigurationBackend. Every operation is verified after it is performed.

KodiRuntimeConfigurationBackend(profile_root="special://profile/")
    Production backend. Settings are read and written through the Kodi 20+
    typed Settings wrapper, xbmcaddon.Addon(id).getSettings(), with the owning
    Addon deliberately kept alive across the call — see the class docstring.
    Managed files are resolved against special://profile/ and replaced
    atomically via a securely created same-directory temporary file.

default_packages_root() -> str
    Filesystem path of the add-on's embedded package root
    (resources/config/packages), resolved relative to this module.

Responsibility split
--------------------
PURE (no Kodi, no I/O beyond reading package files):
    descriptor parsing, schema/type validation, package overlay resolution,
    ownership validation, completeness validation.

RUNTIME (behind ConfigurationBackend):
    reading current typed setting values, reading managed files, applying
    changes, verifying applied state.

Authority model
---------------
The manifest declares WHAT Build Manager owns; packages contain the desired
VALUES. A package is data. A package can never expand Build Manager's authority:

  * every effective setting target must appear in config.managed_settings
  * every effective file destination must appear in config.managed_files
  * every declared managed target must be supplied by some selected package

A package that targets anything else fails preflight, and preflight failure
means zero mutations.

Preflight guarantee
-------------------
resolve() performs ALL parsing, type validation, path validation, source-file
reading, overlay resolution and ownership/completeness validation before
returning. ConfigurationManager.apply() only ever sees a fully-validated
EffectiveConfiguration. A malformed later package therefore cannot leave
earlier packages already applied.

This is a preflight guarantee, not transactional rollback. Once apply() begins,
an individual operation may fail; earlier successful operations are not undone.
Each operation is independently verified and reported.

Package layout
--------------
    <packages_root>/<package-id>/
        package.json
        files/
            ...

Descriptor (schema_version 1)
-----------------------------
    {
      "schema_version": 1,
      "id": "example-common",
      "settings": [
        {"addon_id": "plugin.video.example", "key": "quality",
         "type": "string", "value": "1080p"}
      ],
      "files": [
        {"source": "files/example.json",
         "destination": "addon_data/plugin.video.example/example.json"}
      ]
    }

Supported setting types: string, bool, int, number. Exact JSON value types are
required: bool is never accepted for int or number, and int/float is never
accepted for bool. Lists, objects, secrets, templates and environment/shell
substitution are not supported and are rejected.

Overlay semantics
-----------------
Packages are applied in the order given by ConfigDeclarations.packages, which
the resolver (BM-004) already produced in deterministic first-seen order
(base -> platform -> device -> optional groups). Duplicate package IDs are
collapsed to their first occurrence, matching resolver union semantics.

For a setting target (addon_id, key) or a file destination named by more than
one selected package, the LAST package in that order wins. This supports
layering such as common -> tvos -> bonus-room without manifest schema changes.

Determinism
-----------
The same packages in the same order always produce an identical
EffectiveConfiguration. Output collections are sorted (settings by
(addon_id, key), files by destination) because that ordering carries no
semantic meaning; package order is preserved only where it decides precedence.

Number comparison
-----------------
Kodi serializes a number setting with the default std::ostringstream double
formatting, i.e. 6 significant digits. Two values that agree to 6 significant
digits are therefore indistinguishable once Kodi has persisted them. BM-015:

  * rejects a package `number` value that does not survive a 6-significant-digit
    round trip, so a package can never request a value Kodi cannot store; and
  * compares number settings at exactly that precision.

This is a narrow, documented comparison tied to Kodi's own serialization, not a
general floating-point tolerance.

Secrets boundary
----------------
BM-015 handles PUBLIC configuration only. Packages must never contain
credentials, tokens, passwords, OAuth state, or debrid/Trakt/EasyNews account
data. private_overlay is never read here; portable authentication state is
BM-017's subject. Operation results carry content identities (digests), never
raw setting values or file contents.

Skin boundary
-------------
SkinEntry.config_packages are appended to ResolvedBuild.config by the BM-018B
resolver integration. BM-015 consumes that merged ConfigDeclarations through
the same generic loader, ownership checks and deployer; there is no separate
skin package format or deployer.

Add-on absence
--------------
A setting target whose add-on is not installed (or cannot be opened) fails the
operation clearly. BM-015 never installs an add-on; BM-011 owns installation.

Fail closed
-----------
A Kodi API error is never converted into a default or empty value. Read
failures, write failures and verification mismatches all produce FAILED.

Stdlib only — no new runtime dependencies.
No shell execution, no Kodi database edits, no recursive directory replacement,
and no direct editing of generated per-add-on settings.xml files.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import posixpath
import re
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from resources.lib.af3 import AF3PolicyError, validate_skin_settings
from resources.lib.manifest import ConfigDeclarations, SettingTargetKind
from resources.lib.restart import (
    RestartObservation,
    RestartRequirement,
    RestartReport,
    aggregate_restart_requirements,
)


# Public configuration name for the manifest-level target discriminator.
ConfigTargetKind = SettingTargetKind


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Base class for all BM-015 configuration deployment errors."""


class ConfigPackageError(ConfigError):
    """A configuration package is missing, malformed, or unsafe.

    Covers invalid package IDs, descriptor schema violations, wrong setting
    value types, unsafe source/destination paths, and duplicate targets inside
    a single package.
    """


class ConfigOwnershipError(ConfigError):
    """The effective configuration does not match manifest-declared ownership.

    Raised when a package targets something the manifest does not declare, or
    when the manifest declares a managed target that no selected package
    supplies. Both are preflight failures: zero mutations occur.
    """


class ConfigBackendError(ConfigError):
    """A Kodi runtime or filesystem operation failed.

    Never swallowed into a default value. The affected operation is reported
    as FAILED.
    """


class ConfigAddonUnavailableError(ConfigBackendError):
    """A targeted add-on is not installed or cannot be opened.

    BM-015 does not install add-ons (BM-011 owns installation).
    """


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ConfigSettingType(str, Enum):
    """Setting types supported by package descriptor schema_version 1."""
    STRING = "string"
    BOOL = "bool"
    INT = "int"
    NUMBER = "number"


class ConfigOperationKind(str, Enum):
    """Whether an operation targets an add-on setting or a managed file."""
    SETTING = "setting"
    FILE = "file"


class ConfigOperationStatus(str, Enum):
    """Per-operation outcome from ConfigurationManager.apply()."""
    ALREADY_CORRECT = "already_correct"
    UPDATED = "updated"
    CREATED = "created"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Grammar / limits
# ---------------------------------------------------------------------------

_RE_PACKAGE_ID = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
_RE_ADDON_ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$')
_RE_SETTING_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
_RE_URI_SCHEME = re.compile(r'^[A-Za-z][A-Za-z0-9+.\-]*:')

_MAX_PACKAGE_ID_LEN = 64

_DESCRIPTOR_NAME = "package.json"
_DESCRIPTOR_KEYS = frozenset({"schema_version", "id", "settings", "files"})
_SETTING_KEYS = frozenset({"target", "addon_id", "key", "type", "value"})
_FILE_KEYS = frozenset({"source", "destination"})

_SCHEMA_VERSION = 1

#: Significant digits Kodi preserves when serializing a number setting.
NUMBER_SIGNIFICANT_DIGITS = 6

#: Prefix for the securely created staging file used during atomic replace.
#: The full name is chosen by tempfile.mkstemp(), never predictable.
_TMP_PREFIX = ".bm-config-"
_TMP_SUFFIX = ".tmp"


# ---------------------------------------------------------------------------
# Frozen data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigSetting:
    """One desired add-on setting value supplied by a package.

    value is already type-checked against setting_type. package_id names the
    package that supplied this (winning) value.
    """
    addon_id: str
    key: str
    setting_type: ConfigSettingType
    value: object
    package_id: str
    target_kind: ConfigTargetKind = ConfigTargetKind.ADDON

    @property
    def target(self) -> Tuple[str, str, str]:
        """(target_kind, addon_id, key) — the owned setting identity."""
        return (self.target_kind.value, self.addon_id, self.key)


@dataclass(frozen=True)
class ConfigFile:
    """One desired whole-file managed asset supplied by a package.

    content holds the source bytes, read during preflight so that a missing or
    unreadable source fails before any mutation. source is the package-relative
    source path, retained for diagnostics only.
    """
    destination: str
    source: str
    content: bytes
    package_id: str


@dataclass(frozen=True)
class ConfigPackage:
    """A parsed, validated configuration package.

    settings and files are in descriptor order. Duplicate targets within one
    package are rejected at parse time, so order carries no override meaning
    inside a package.
    """
    package_id: str
    settings: Tuple[ConfigSetting, ...] = ()
    files: Tuple[ConfigFile, ...] = ()


@dataclass(frozen=True)
class EffectiveConfiguration:
    """Complete desired configuration after package overlay and ownership checks.

    packages:  selected package IDs in application order (duplicates collapsed).
    settings:  winning settings, sorted by (addon_id, key).
    files:     winning managed files, sorted by destination.

    An EffectiveConfiguration is only ever produced by a fully successful
    preflight, so ConfigurationManager.apply() may assume it is authorized.
    """
    packages: Tuple[str, ...] = ()
    settings: Tuple[ConfigSetting, ...] = ()
    files: Tuple[ConfigFile, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when there is nothing to apply."""
        return not self.settings and not self.files

    @property
    def identity(self) -> str:
        """Deterministic SHA-256 fingerprint of the desired configuration.

        Covers the ordered package selection and, per target, the full desired
        content identity — not merely the target scope. Two resolutions with
        the same managed scope but a different desired value, setting type,
        file content, package order or winning package produce different
        identities.

        This is what lets BM-014 tell "verified against the configuration I am
        being shown" from "verified against some earlier configuration with the
        same scope". Raw values never appear: settings contribute their
        type-tagged digest and files their content digest.
        """
        lines = [
            f"schema:{_SCHEMA_VERSION}",
            "packages:" + ",".join(self.packages),
        ]
        for item in sorted(
            self.settings,
            key=lambda s: (s.target_kind.value, s.addon_id, s.key),
        ):
            lines.append("setting:" + "\x1f".join((
                item.target_kind.value,
                item.addon_id,
                item.key,
                item.setting_type.value,
                _setting_identity(item.setting_type, item.value),
                item.package_id,
            )))
        for item in sorted(self.files, key=lambda f: f.destination):
            lines.append("file:" + "\x1f".join((
                item.destination,
                _content_identity(item.content),
                item.package_id,
            )))
        digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


@dataclass(frozen=True)
class ConfigOperationResult:
    """Result of one applied configuration operation.

    addon_id/key are set for SETTING operations; destination is set for FILE
    operations. The unused fields are empty strings.

    expected_identity / previous_identity are content identities (type-tagged
    SHA-256 digests), never raw setting values or file contents. They are
    diagnostics for comparing runs — not a confidentiality mechanism. Public
    configuration packages must contain no secrets.

    package_id names the package responsible for the final desired value.
    """
    kind: ConfigOperationKind
    package_id: str
    status: ConfigOperationStatus
    expected_identity: str
    previous_identity: Optional[str]
    detail: str
    addon_id: str = ""
    key: str = ""
    destination: str = ""
    target_kind: ConfigTargetKind = ConfigTargetKind.ADDON
    restart_requirement: RestartRequirement = RestartRequirement.NONE

    @property
    def target(self) -> str:
        """Human-readable target: 'addon_id/key' for settings, path for files."""
        if self.kind is ConfigOperationKind.SETTING:
            if self.target_kind is ConfigTargetKind.ADDON:
                return f"{self.addon_id}/{self.key}"
            return f"{self.target_kind.value}:{self.addon_id}/{self.key}"
        return self.destination

    @property
    def restart_report(self) -> RestartReport:
        """Typed restart metadata for this operation's actual outcome."""
        return aggregate_restart_requirements((RestartObservation(
            requirement=self.restart_requirement,
            changed=self.status in (
                ConfigOperationStatus.UPDATED,
                ConfigOperationStatus.CREATED,
            ),
            succeeded=self.status is not ConfigOperationStatus.FAILED,
            operation=self.target,
        ),))


@dataclass(frozen=True)
class ConfigurationValidationState:
    """Immutable snapshot of what BM-015 actually verified.

    Consumed optionally by BM-014's validator. Target tuples describe the FULL
    resolved managed scope that was applied; the verified_* tuples are the
    subset whose post-operation verification succeeded.

    effective_identity binds the snapshot to the exact EffectiveConfiguration
    that produced it. Target scope alone is not sufficient evidence: a package
    whose desired value changed keeps the same scope, so a stale snapshot would
    otherwise appear to validate the new configuration.

    BM-014 requires BOTH an exact scope match against the manifest's declared
    scope AND an exact identity match against the EffectiveConfiguration it is
    given before it reports configuration as validated.
    """
    effective_identity: str = ""
    setting_targets: Tuple[tuple, ...] = ()
    file_targets: Tuple[str, ...] = ()
    verified_settings: Tuple[tuple, ...] = ()
    verified_files: Tuple[str, ...] = ()

    @property
    def failed_settings(self) -> Tuple[tuple, ...]:
        verified = set(self.verified_settings)
        return tuple(t for t in self.setting_targets if t not in verified)

    @property
    def failed_files(self) -> Tuple[str, ...]:
        verified = set(self.verified_files)
        return tuple(t for t in self.file_targets if t not in verified)

    @property
    def is_fully_verified(self) -> bool:
        """True when every target in scope was verified correct."""
        return (
            len(self.verified_settings) == len(self.setting_targets)
            and len(self.verified_files) == len(self.file_targets)
        )


@dataclass(frozen=True)
class ConfigApplyResult:
    """Aggregate result of ConfigurationManager.apply().

    results is in deterministic order: all settings (sorted by addon_id, key)
    followed by all files (sorted by destination). Exactly one result is
    produced per effective target.

    effective_identity is the identity of the EffectiveConfiguration that was
    applied, carried through so validation_state can bind to it.
    """
    results: Tuple[ConfigOperationResult, ...] = ()
    effective_identity: str = ""

    @property
    def settings(self) -> Tuple[ConfigOperationResult, ...]:
        return tuple(r for r in self.results if r.kind is ConfigOperationKind.SETTING)

    @property
    def files(self) -> Tuple[ConfigOperationResult, ...]:
        return tuple(r for r in self.results if r.kind is ConfigOperationKind.FILE)

    @property
    def changed(self) -> Tuple[ConfigOperationResult, ...]:
        """Operations that mutated Kodi state (UPDATED or CREATED)."""
        return tuple(
            r for r in self.results
            if r.status in (ConfigOperationStatus.UPDATED, ConfigOperationStatus.CREATED)
        )

    @property
    def unchanged(self) -> Tuple[ConfigOperationResult, ...]:
        """Operations that needed no mutation (ALREADY_CORRECT)."""
        return tuple(
            r for r in self.results
            if r.status is ConfigOperationStatus.ALREADY_CORRECT
        )

    @property
    def failed(self) -> Tuple[ConfigOperationResult, ...]:
        return tuple(
            r for r in self.results if r.status is ConfigOperationStatus.FAILED
        )

    @property
    def all_applied(self) -> bool:
        """True when no operation failed. An empty result set is applied."""
        return not self.failed

    @property
    def restart_report(self) -> RestartReport:
        """Aggregate restart metadata without downgrading earlier results."""
        return aggregate_restart_requirements(
            RestartObservation(
                requirement=result.restart_requirement,
                changed=result.status in (
                    ConfigOperationStatus.UPDATED,
                    ConfigOperationStatus.CREATED,
                ),
                succeeded=result.status is not ConfigOperationStatus.FAILED,
                operation=result.target,
            )
            for result in self.results
        )

    @property
    def restart_requirement(self) -> RestartRequirement:
        """The final typed requirement for this configuration reconciliation."""
        return self.restart_report.requirement

    @property
    def validation_state(self) -> ConfigurationValidationState:
        """Immutable snapshot for optional consumption by BM-014.

        Scope is the full set of targets this apply() covered. Only operations
        that completed post-operation verification are reported as verified.
        """
        settings = self.settings
        files = self.files
        return ConfigurationValidationState(
            effective_identity=self.effective_identity,
            setting_targets=tuple(sorted(
                (r.target_kind.value, r.addon_id, r.key) for r in settings
            )),
            file_targets=tuple(sorted(r.destination for r in files)),
            verified_settings=tuple(sorted(
                (r.target_kind.value, r.addon_id, r.key) for r in settings
                if r.status is not ConfigOperationStatus.FAILED
            )),
            verified_files=tuple(sorted(
                r.destination for r in files
                if r.status is not ConfigOperationStatus.FAILED
            )),
        )


# ---------------------------------------------------------------------------
# Path / identifier validation (pure)
# ---------------------------------------------------------------------------

def validate_package_id(package_id: object) -> str:
    """Validate a configuration package ID and return it.

    Package IDs are path-safe identifiers matching [a-z0-9][a-z0-9._-]* with a
    64-character limit. Empty values, absolute paths, slashes, backslashes,
    '..', whitespace and null bytes are rejected. A package ID is never treated
    as an arbitrary path.

    Raises:
        ConfigPackageError on any violation.
    """
    if not isinstance(package_id, str):
        raise ConfigPackageError(
            f"package id must be a string, got {type(package_id).__name__}"
        )
    if not package_id:
        raise ConfigPackageError("package id must not be empty")
    if len(package_id) > _MAX_PACKAGE_ID_LEN:
        raise ConfigPackageError(
            f"package id {package_id!r} exceeds {_MAX_PACKAGE_ID_LEN} characters"
        )
    if ".." in package_id:
        raise ConfigPackageError(
            f"package id {package_id!r} must not contain '..'"
        )
    if not _RE_PACKAGE_ID.match(package_id):
        raise ConfigPackageError(
            f"package id {package_id!r} is not a valid package identifier "
            f"(must match [a-z0-9][a-z0-9._-]*)"
        )
    return package_id


def _normalize_relative_path(raw: object, *, label: str) -> str:
    """Validate and normalize a contained, relative POSIX-style path.

    Rejects: non-strings, empty strings, null bytes, absolute paths, UNC paths,
    Windows drive paths, URI schemes (including arbitrary 'special://' values),
    '..' components, and anything that normalizes to '.' or escapes the root.

    Returns the normalized forward-slash path.
    """
    if not isinstance(raw, str):
        raise ConfigPackageError(f"{label}: path must be a string")
    if not raw:
        raise ConfigPackageError(f"{label}: path must not be empty")
    if "\x00" in raw:
        raise ConfigPackageError(f"{label}: path must not contain null bytes")
    if raw.strip() != raw or not raw.strip():
        raise ConfigPackageError(
            f"{label}: path must not be whitespace-padded or whitespace-only"
        )
    if _RE_URI_SCHEME.match(raw):
        raise ConfigPackageError(
            f"{label}: URI-scheme paths are not allowed (got {raw!r}); "
            f"paths must be relative"
        )
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise ConfigPackageError(f"{label}: UNC-style paths are not allowed")
    if raw.startswith("/") or raw.startswith("\\"):
        raise ConfigPackageError(f"{label}: absolute paths are not allowed")

    normalized = raw.replace("\\", "/")
    for component in normalized.split("/"):
        if component == "..":
            raise ConfigPackageError(
                f"{label}: path traversal ('..') is not allowed"
            )

    normed = posixpath.normpath(normalized)
    if normed.startswith("/") or normed.startswith(".."):
        raise ConfigPackageError(f"{label}: path normalizes outside the allowed root")
    if normed in (".", ""):
        raise ConfigPackageError(f"{label}: path must name a file")
    return normed


def _is_within(child: str, parent: str) -> bool:
    """True when child is strictly nested inside parent (both already realpath'd)."""
    if child == parent:
        return False
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Value typing / identity (pure)
# ---------------------------------------------------------------------------

def _number_canonical(value: object) -> str:
    """Canonical text form of a number at Kodi's serialization precision."""
    number = float(value)
    if number == 0:
        number = 0.0
    return f"{number:.{NUMBER_SIGNIFICANT_DIGITS}g}"


def _number_round_trips(value: float) -> bool:
    """True when value survives Kodi's 6-significant-digit serialization."""
    return float(_number_canonical(value)) == float(value)


def _validate_descriptor_value(
    setting_type: ConfigSettingType, value: object, *, label: str
) -> object:
    """Enforce exact JSON value typing for a package setting. Fails closed."""
    if setting_type is ConfigSettingType.STRING:
        if not isinstance(value, str):
            raise ConfigPackageError(
                f"{label}.value: type 'string' requires a JSON string, "
                f"got {type(value).__name__}"
            )
        return value

    if setting_type is ConfigSettingType.BOOL:
        if not isinstance(value, bool):
            raise ConfigPackageError(
                f"{label}.value: type 'bool' requires a JSON boolean, "
                f"got {type(value).__name__}"
            )
        return value

    if setting_type is ConfigSettingType.INT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigPackageError(
                f"{label}.value: type 'int' requires a JSON integer "
                f"(booleans are not integers), got {type(value).__name__}"
            )
        return value

    # NUMBER
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigPackageError(
            f"{label}.value: type 'number' requires a JSON number "
            f"(booleans are not numbers), got {type(value).__name__}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise ConfigPackageError(
            f"{label}.value: type 'number' requires a finite value"
        )
    if not _number_round_trips(number):
        raise ConfigPackageError(
            f"{label}.value: number {value!r} exceeds the "
            f"{NUMBER_SIGNIFICANT_DIGITS} significant digits Kodi preserves for "
            f"number settings; Build Manager would never be able to verify it"
        )
    return number


def _check_runtime_value(
    setting_type: ConfigSettingType, value: object, *, context: str
) -> object:
    """Validate a value returned by the backend. Raises ConfigBackendError.

    Infrastructure must never be allowed to degrade into a default value, so a
    wrongly-typed backend response is an error rather than a coercion.
    """
    if setting_type is ConfigSettingType.STRING:
        if not isinstance(value, str):
            raise ConfigBackendError(
                f"{context}: expected a string value, got {type(value).__name__}"
            )
        return value
    if setting_type is ConfigSettingType.BOOL:
        if not isinstance(value, bool):
            raise ConfigBackendError(
                f"{context}: expected a boolean value, got {type(value).__name__}"
            )
        return value
    if setting_type is ConfigSettingType.INT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigBackendError(
                f"{context}: expected an integer value, got {type(value).__name__}"
            )
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigBackendError(
            f"{context}: expected a numeric value, got {type(value).__name__}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise ConfigBackendError(f"{context}: numeric value is not finite")
    return number


def values_equal(
    setting_type: ConfigSettingType, left: object, right: object
) -> bool:
    """Compare two typed setting values.

    string / bool / int compare exactly. number compares at Kodi's
    serialization precision (6 significant digits); see the module docstring.
    """
    if setting_type is ConfigSettingType.NUMBER:
        return _number_canonical(left) == _number_canonical(right)
    if setting_type is ConfigSettingType.BOOL:
        return bool(left) is bool(right)
    return left == right


def _setting_identity(setting_type: ConfigSettingType, value: object) -> str:
    """Type-tagged digest identifying a setting value without revealing it."""
    if setting_type is ConfigSettingType.NUMBER:
        token = _number_canonical(value)
    elif setting_type is ConfigSettingType.BOOL:
        token = "true" if value else "false"
    elif setting_type is ConfigSettingType.INT:
        token = str(int(value))
    else:
        token = str(value)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{setting_type.value}:sha256:{digest}"


def _content_identity(data: bytes) -> str:
    """Digest identifying managed file content without revealing it."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


# ---------------------------------------------------------------------------
# Embedded package root
# ---------------------------------------------------------------------------

def default_packages_root() -> str:
    """Absolute path of the add-on's embedded configuration package root.

    Resolved relative to this module (resources/lib/config.py ->
    resources/config/packages) so it is correct wherever Kodi installed the
    add-on. BM-015 supports embedded/local packages only; remote or versioned
    package delivery is deliberately out of scope.
    """
    lib_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(lib_dir), "config", "packages")


# ---------------------------------------------------------------------------
# Package loader (pure)
# ---------------------------------------------------------------------------

class ConfigPackageLoader:
    """Load, validate, overlay and authorize embedded configuration packages.

    Pure: no Kodi imports, no Kodi state access, no mutation. The only I/O is
    reading package descriptors and package source files from packages_root.

    Usage:
        loader = ConfigPackageLoader(default_packages_root())
        effective = loader.resolve(desired.config)
    """

    def __init__(self, packages_root: str) -> None:
        if not isinstance(packages_root, str) or not packages_root:
            raise ConfigPackageError("packages_root must be a non-empty string")
        self._packages_root = os.path.realpath(packages_root)

    @property
    def packages_root(self) -> str:
        """Resolved absolute path of the package root."""
        return self._packages_root

    # -- public -------------------------------------------------------------

    def resolve(
        self, config: Optional[ConfigDeclarations]
    ) -> EffectiveConfiguration:
        """Resolve a ConfigDeclarations block into an EffectiveConfiguration.

        Performs the complete preflight: package ID validation, descriptor
        parsing, setting type validation, source and destination path
        validation, source file reading, overlay resolution, manifest ownership
        validation and managed-target completeness validation.

        config=None returns a clean empty no-op result. A config that declares
        nothing and selects no packages also resolves to a no-op.

        Raises:
            ConfigPackageError:   a package is missing, malformed or unsafe.
            ConfigOwnershipError: a package targets something the manifest does
                not declare, or a declared managed target has no value.
        """
        if config is None:
            return EffectiveConfiguration()

        ordered_ids = self._ordered_package_ids(config)
        packages = [self.load_package(pid) for pid in ordered_ids]

        settings_map, files_map = _overlay(packages)
        try:
            validate_skin_settings(settings_map)
        except AF3PolicyError as exc:
            raise ConfigPackageError(str(exc)) from exc
        _validate_ownership(config, settings_map, files_map)

        return EffectiveConfiguration(
            packages=tuple(ordered_ids),
            settings=tuple(settings_map[key] for key in sorted(settings_map)),
            files=tuple(files_map[key] for key in sorted(files_map)),
        )

    def load_package(self, package_id: str) -> ConfigPackage:
        """Load and validate a single package by ID.

        Raises ConfigPackageError if the ID is invalid, the package directory
        or descriptor is missing, the descriptor is malformed, or any declared
        source file is missing, unsafe or not a regular file.
        """
        pkg_id = validate_package_id(package_id)
        package_dir = os.path.realpath(
            os.path.join(self._packages_root, pkg_id)
        )
        if not _is_within(package_dir, self._packages_root):
            raise ConfigPackageError(
                f"package {pkg_id!r} resolves outside the package root"
            )
        if not os.path.isdir(package_dir):
            raise ConfigPackageError(
                f"package {pkg_id!r} not found at {package_dir}"
            )

        descriptor_path = os.path.join(package_dir, _DESCRIPTOR_NAME)
        # The descriptor obeys the same trust boundary as package source
        # assets: it must be a real regular file inside the package directory,
        # never a symlink escaping it.
        resolved_descriptor = os.path.realpath(descriptor_path)
        if not _is_within(resolved_descriptor, package_dir):
            raise ConfigPackageError(
                f"package {pkg_id!r}: {_DESCRIPTOR_NAME} escapes the package "
                f"directory"
            )
        if not os.path.isfile(resolved_descriptor):
            raise ConfigPackageError(
                f"package {pkg_id!r} has no {_DESCRIPTOR_NAME}"
            )
        try:
            with open(resolved_descriptor, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise ConfigPackageError(
                f"package {pkg_id!r}: cannot read {_DESCRIPTOR_NAME}: {exc}"
            ) from exc

        try:
            raw = json.loads(text, parse_constant=_reject_json_constant)
        except ValueError as exc:
            raise ConfigPackageError(
                f"package {pkg_id!r}: {_DESCRIPTOR_NAME} is not valid JSON: {exc}"
            ) from exc

        return _parse_descriptor(raw, package_id=pkg_id, package_dir=package_dir)

    # -- internal -----------------------------------------------------------

    def _ordered_package_ids(self, config: ConfigDeclarations) -> List[str]:
        """Validated package IDs in application order, duplicates collapsed."""
        seen: set = set()
        ordered: List[str] = []
        for raw_id in config.packages:
            pkg_id = validate_package_id(raw_id)
            if pkg_id in seen:
                continue
            seen.add(pkg_id)
            ordered.append(pkg_id)
        return ordered


def _reject_json_constant(name: str) -> object:
    """Reject the non-standard JSON constants NaN / Infinity / -Infinity."""
    raise ValueError(f"non-finite JSON constant {name!r} is not allowed")


# ---------------------------------------------------------------------------
# Descriptor parsing (pure)
# ---------------------------------------------------------------------------

def _parse_descriptor(
    raw: object, *, package_id: str, package_dir: str
) -> ConfigPackage:
    """Parse and validate a package.json document."""
    label = f"package {package_id!r}"
    if not isinstance(raw, dict):
        raise ConfigPackageError(f"{label}: {_DESCRIPTOR_NAME} must be an object")

    unknown = sorted(set(raw) - _DESCRIPTOR_KEYS)
    if unknown:
        raise ConfigPackageError(
            f"{label}: unknown descriptor field(s): {', '.join(unknown)}"
        )

    if "schema_version" not in raw:
        raise ConfigPackageError(f"{label}.schema_version: required field is missing")
    schema_version = raw["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ConfigPackageError(f"{label}.schema_version: must be an integer")
    if schema_version != _SCHEMA_VERSION:
        raise ConfigPackageError(
            f"{label}.schema_version: unsupported version {schema_version} "
            f"(expected {_SCHEMA_VERSION})"
        )

    if "id" not in raw:
        raise ConfigPackageError(f"{label}.id: required field is missing")
    declared_id = validate_package_id(raw["id"])
    if declared_id != package_id:
        raise ConfigPackageError(
            f"{label}.id: descriptor declares {declared_id!r} but the package "
            f"directory is {package_id!r}"
        )

    settings = _parse_settings(raw.get("settings", []), package_id=package_id)
    files = _parse_files(
        raw.get("files", []), package_id=package_id, package_dir=package_dir
    )
    return ConfigPackage(package_id=package_id, settings=settings, files=files)


def _parse_settings(
    raw: object, *, package_id: str
) -> Tuple[ConfigSetting, ...]:
    """Parse the descriptor 'settings' array. Rejects duplicate targets."""
    label = f"package {package_id!r}.settings"
    if not isinstance(raw, list):
        raise ConfigPackageError(f"{label}: must be an array")

    seen: set = set()
    parsed: List[ConfigSetting] = []
    for index, entry in enumerate(raw):
        entry_label = f"{label}[{index}]"
        if not isinstance(entry, dict):
            raise ConfigPackageError(f"{entry_label}: must be an object")
        unknown = sorted(set(entry) - _SETTING_KEYS)
        if unknown:
            raise ConfigPackageError(
                f"{entry_label}: unknown field(s): {', '.join(unknown)}"
            )
        for required in ("addon_id", "key", "type", "value"):
            if required not in entry:
                raise ConfigPackageError(
                    f"{entry_label}.{required}: required field is missing"
                )

        target_kind = _parse_target_kind(
            entry.get("target", "addon"), label=entry_label
        )

        addon_id = entry["addon_id"]
        if not isinstance(addon_id, str) or not _RE_ADDON_ID.match(addon_id):
            raise ConfigPackageError(
                f"{entry_label}.addon_id: invalid add-on ID {addon_id!r}"
            )

        key = entry["key"]
        if not isinstance(key, str) or not key:
            raise ConfigPackageError(
                f"{entry_label}.key: must be a non-empty string"
            )
        if not _RE_SETTING_KEY.match(key):
            raise ConfigPackageError(
                f"{entry_label}.key: invalid setting key {key!r} "
                f"(must match [A-Za-z0-9][A-Za-z0-9._-]*)"
            )

        raw_type = entry["type"]
        if not isinstance(raw_type, str):
            raise ConfigPackageError(f"{entry_label}.type: must be a string")
        try:
            setting_type = ConfigSettingType(raw_type)
        except ValueError as exc:
            supported = ", ".join(t.value for t in ConfigSettingType)
            raise ConfigPackageError(
                f"{entry_label}.type: unsupported setting type {raw_type!r} "
                f"(supported: {supported})"
            ) from exc

        value = _validate_descriptor_value(
            setting_type, entry["value"], label=entry_label
        )

        if target_kind is ConfigTargetKind.SKIN and setting_type not in (
            ConfigSettingType.BOOL, ConfigSettingType.STRING,
        ):
            raise ConfigPackageError(
                f"{entry_label}.type: skin targets support only 'bool' and "
                f"'string', got {setting_type.value!r}"
            )

        target = (target_kind.value, addon_id, key)
        if target in seen:
            raise ConfigPackageError(
                f"{entry_label}: duplicate setting target "
                f"{target_kind.value}:{addon_id}/{key} "
                f"within package {package_id!r}"
            )
        seen.add(target)
        parsed.append(ConfigSetting(
            addon_id=addon_id,
            key=key,
            setting_type=setting_type,
            value=value,
            package_id=package_id,
            target_kind=target_kind,
        ))
    return tuple(parsed)


def _parse_target_kind(raw: object, *, label: str) -> ConfigTargetKind:
    if not isinstance(raw, str):
        raise ConfigPackageError(
            f"{label}.target: must be a string when present"
        )
    try:
        return ConfigTargetKind(raw)
    except ValueError as exc:
        supported = ", ".join(kind.value for kind in ConfigTargetKind)
        raise ConfigPackageError(
            f"{label}.target: unsupported target kind {raw!r} "
            f"(supported: {supported})"
        ) from exc


def _parse_files(
    raw: object, *, package_id: str, package_dir: str
) -> Tuple[ConfigFile, ...]:
    """Parse the descriptor 'files' array, reading and containing each source."""
    label = f"package {package_id!r}.files"
    if not isinstance(raw, list):
        raise ConfigPackageError(f"{label}: must be an array")

    seen: set = set()
    parsed: List[ConfigFile] = []
    for index, entry in enumerate(raw):
        entry_label = f"{label}[{index}]"
        if not isinstance(entry, dict):
            raise ConfigPackageError(f"{entry_label}: must be an object")
        unknown = sorted(set(entry) - _FILE_KEYS)
        if unknown:
            raise ConfigPackageError(
                f"{entry_label}: unknown field(s): {', '.join(unknown)}"
            )
        for required in ("source", "destination"):
            if required not in entry:
                raise ConfigPackageError(
                    f"{entry_label}.{required}: required field is missing"
                )

        source = _normalize_relative_path(
            entry["source"], label=f"{entry_label}.source"
        )
        destination = _normalize_relative_path(
            entry["destination"], label=f"{entry_label}.destination"
        )

        content = _read_source_file(
            package_dir=package_dir,
            source=source,
            label=f"{entry_label}.source",
        )

        if destination in seen:
            raise ConfigPackageError(
                f"{entry_label}: duplicate file destination {destination!r} "
                f"within package {package_id!r}"
            )
        seen.add(destination)
        parsed.append(ConfigFile(
            destination=destination,
            source=source,
            content=content,
            package_id=package_id,
        ))
    return tuple(parsed)


def _read_source_file(*, package_dir: str, source: str, label: str) -> bytes:
    """Read a package source file after confirming containment and file type.

    The source must stay inside the package root after symlink resolution and
    must be a regular file. Reading here makes source availability part of
    preflight, so a missing source in a later package causes zero mutations.
    """
    package_root = os.path.realpath(package_dir)
    resolved = os.path.realpath(os.path.join(package_root, *source.split("/")))
    if not _is_within(resolved, package_root):
        raise ConfigPackageError(
            f"{label}: source {source!r} escapes the package root"
        )
    if not os.path.exists(resolved):
        raise ConfigPackageError(f"{label}: source file {source!r} does not exist")
    if not os.path.isfile(resolved):
        raise ConfigPackageError(
            f"{label}: source {source!r} is not a regular file"
        )
    try:
        with open(resolved, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise ConfigPackageError(
            f"{label}: cannot read source file {source!r}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Overlay + ownership (pure)
# ---------------------------------------------------------------------------

def _overlay(
    packages: List[ConfigPackage],
) -> Tuple[Dict[Tuple[str, str, str], ConfigSetting], Dict[str, ConfigFile]]:
    """Overlay packages in order; later packages win per target."""
    settings_map: Dict[Tuple[str, str, str], ConfigSetting] = {}
    files_map: Dict[str, ConfigFile] = {}
    for package in packages:
        for setting in package.settings:
            settings_map[setting.target] = setting
        for config_file in package.files:
            files_map[config_file.destination] = config_file
    return settings_map, files_map


def _validate_ownership(
    config: ConfigDeclarations,
    settings_map: Dict[Tuple[str, str, str], ConfigSetting],
    files_map: Dict[str, ConfigFile],
) -> None:
    """Enforce manifest ownership and managed-target completeness.

    Effective targets must exactly equal declared managed targets:

      * an effective target the manifest does not declare is an attempt by
        package data to expand Build Manager's authority; and
      * a declared target no package supplies is configuration Build Manager
        could not actually reconcile.

    Both raise ConfigOwnershipError before any mutation.
    """
    declared_settings = {
        (scope.target_kind.value, scope.addon_id, key)
        for scope in config.managed_settings
        for key in scope.keys
    }
    declared_files = set()
    for index, path in enumerate(config.managed_files):
        try:
            declared_files.add(
                _normalize_relative_path(path, label=f"config.managed_files[{index}]")
            )
        except ConfigPackageError as exc:
            raise ConfigOwnershipError(
                f"manifest declares an unusable managed file path: {exc}"
            ) from exc

    undeclared_settings = sorted(set(settings_map) - declared_settings)
    if undeclared_settings:
        target_kind, addon_id, key = undeclared_settings[0]
        package_id = settings_map[(target_kind, addon_id, key)].package_id
        raise ConfigOwnershipError(
            f"package {package_id!r} targets setting "
            f"{target_kind}:{addon_id}/{key}, which is "
            f"not declared in config.managed_settings "
            f"({len(undeclared_settings)} undeclared setting target(s) total)"
        )

    undeclared_files = sorted(set(files_map) - declared_files)
    if undeclared_files:
        destination = undeclared_files[0]
        package_id = files_map[destination].package_id
        raise ConfigOwnershipError(
            f"package {package_id!r} targets file {destination!r}, which is not "
            f"declared in config.managed_files "
            f"({len(undeclared_files)} undeclared file target(s) total)"
        )

    unresolved_settings = sorted(declared_settings - set(settings_map))
    if unresolved_settings:
        target_kind, addon_id, key = unresolved_settings[0]
        raise ConfigOwnershipError(
            f"unresolved managed configuration: config.managed_settings declares "
            f"{target_kind}:{addon_id}/{key} but no selected package supplies a value "
            f"({len(unresolved_settings)} unresolved setting target(s) total)"
        )

    unresolved_files = sorted(declared_files - set(files_map))
    if unresolved_files:
        raise ConfigOwnershipError(
            f"unresolved managed configuration: config.managed_files declares "
            f"{unresolved_files[0]!r} but no selected package supplies content "
            f"({len(unresolved_files)} unresolved file target(s) total)"
        )


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class ConfigurationBackend:
    """Injectable backend for Kodi runtime and filesystem access.

    Override all methods in a concrete subclass. Defaults raise
    NotImplementedError so incomplete fakes surface missing stubs immediately.

    All methods must fail closed: infrastructure problems raise
    ConfigBackendError rather than returning a default or empty value.
    """

    def get_setting(
        self, addon_id: str, key: str, setting_type: ConfigSettingType
    ) -> object:
        """Return the current typed value of an add-on setting.

        Raises:
            ConfigAddonUnavailableError: the add-on is not installed or cannot
                be opened.
            ConfigBackendError: any other failure (unknown key, type mismatch,
                Kodi API error).
        """
        raise NotImplementedError

    def get_skin_setting(
        self, addon_id: str, key: str, setting_type: ConfigSettingType
    ) -> object:
        """Return a typed value from the currently active Kodi skin."""
        raise ConfigBackendError(
            "backend does not support explicit skin-setting targets"
        )

    def set_setting(
        self, addon_id: str, key: str, setting_type: ConfigSettingType, value: object
    ) -> None:
        """Set an add-on setting to value. Raises ConfigBackendError on failure.

        The caller always re-reads the value afterwards; a successful return is
        not accepted as proof the value was stored.
        """
        raise NotImplementedError

    def set_skin_setting(
        self, addon_id: str, key: str, setting_type: ConfigSettingType, value: object
    ) -> None:
        """Set one typed value in the currently active Kodi skin."""
        raise ConfigBackendError(
            "backend does not support explicit skin-setting targets"
        )

    def read_file(self, destination: str) -> Optional[bytes]:
        """Return the bytes of a managed file, or None when it does not exist.

        Raises ConfigBackendError on any failure other than absence.
        """
        raise NotImplementedError

    def write_file(self, destination: str, data: bytes) -> None:
        """Replace a managed file's entire contents with data.

        Creates parent directories as needed. Raises ConfigBackendError on
        failure. The caller re-reads the destination to verify.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# ConfigurationManager (business logic; backend-injectable)
# ---------------------------------------------------------------------------

class ConfigurationManager:
    """Apply an EffectiveConfiguration and verify every operation.

    Usage (real Kodi runtime):
        manager = ConfigurationManager(KodiRuntimeConfigurationBackend())
        result = manager.apply(effective)

    Usage (tests, no Kodi required):
        manager = ConfigurationManager(FakeConfigurationBackend(...))

    apply() never validates ownership itself — an EffectiveConfiguration can
    only be produced by a successful ConfigPackageLoader.resolve() preflight.
    """

    def __init__(self, backend: ConfigurationBackend) -> None:
        self._backend = backend

    def apply(self, effective: EffectiveConfiguration) -> ConfigApplyResult:
        """Apply every setting then every file, in deterministic order.

        Each operation reads current state, skips when already correct, writes
        when drifted, and re-reads to verify. One failed operation does not
        prevent the remaining independent operations from being attempted; all
        results are returned.

        An empty EffectiveConfiguration produces a clean no-op result with no
        backend calls at all.
        """
        results: List[ConfigOperationResult] = []
        for setting in effective.settings:
            results.append(self._apply_setting(setting))
        for config_file in effective.files:
            results.append(self._apply_file(config_file))
        return ConfigApplyResult(
            results=tuple(results),
            effective_identity=effective.identity,
        )

    # -- settings -----------------------------------------------------------

    def _apply_setting(self, setting: ConfigSetting) -> ConfigOperationResult:
        expected = _setting_identity(setting.setting_type, setting.value)
        context = (
            f"{setting.addon_id}/{setting.key}"
            if setting.target_kind is ConfigTargetKind.ADDON
            else f"{setting.target_kind.value}:{setting.addon_id}/{setting.key}"
        )
        get_setting = (
            self._backend.get_setting
            if setting.target_kind is ConfigTargetKind.ADDON
            else self._backend.get_skin_setting
        )
        set_setting = (
            self._backend.set_setting
            if setting.target_kind is ConfigTargetKind.ADDON
            else self._backend.set_skin_setting
        )

        def failure(detail: str, previous: Optional[str]) -> ConfigOperationResult:
            return ConfigOperationResult(
                kind=ConfigOperationKind.SETTING,
                package_id=setting.package_id,
                status=ConfigOperationStatus.FAILED,
                expected_identity=expected,
                previous_identity=previous,
                detail=detail,
                addon_id=setting.addon_id,
                key=setting.key,
                target_kind=setting.target_kind,
            )

        try:
            current = get_setting(
                setting.addon_id, setting.key, setting.setting_type
            )
            current = _check_runtime_value(
                setting.setting_type, current, context=f"read {context}"
            )
        except ConfigAddonUnavailableError as exc:
            return failure(
                f"add-on {setting.addon_id!r} is not installed or cannot be "
                f"opened: {exc}",
                None,
            )
        except ConfigBackendError as exc:
            return failure(f"could not read {context}: {exc}", None)

        previous = _setting_identity(setting.setting_type, current)

        if values_equal(setting.setting_type, current, setting.value):
            return ConfigOperationResult(
                kind=ConfigOperationKind.SETTING,
                package_id=setting.package_id,
                status=ConfigOperationStatus.ALREADY_CORRECT,
                expected_identity=expected,
                previous_identity=previous,
                detail=f"{context} already matches the desired value",
                addon_id=setting.addon_id,
                key=setting.key,
                target_kind=setting.target_kind,
            )

        try:
            set_setting(
                setting.addon_id, setting.key, setting.setting_type, setting.value
            )
        except ConfigBackendError as exc:
            return failure(f"could not set {context}: {exc}", previous)

        try:
            after = get_setting(
                setting.addon_id, setting.key, setting.setting_type
            )
            after = _check_runtime_value(
                setting.setting_type, after, context=f"verify {context}"
            )
        except ConfigBackendError as exc:
            return failure(
                f"could not verify {context} after writing: {exc}", previous
            )

        if not values_equal(setting.setting_type, after, setting.value):
            return failure(
                f"verification mismatch for {context}: expected "
                f"{expected}, read back "
                f"{_setting_identity(setting.setting_type, after)}",
                previous,
            )

        return ConfigOperationResult(
            kind=ConfigOperationKind.SETTING,
            package_id=setting.package_id,
            status=ConfigOperationStatus.UPDATED,
            expected_identity=expected,
            previous_identity=previous,
            detail=f"{context} updated and verified",
            addon_id=setting.addon_id,
            key=setting.key,
            target_kind=setting.target_kind,
        )

    # -- files --------------------------------------------------------------

    def _apply_file(self, config_file: ConfigFile) -> ConfigOperationResult:
        expected = _content_identity(config_file.content)
        destination = config_file.destination

        def result(
            status: ConfigOperationStatus, previous: Optional[str], detail: str
        ) -> ConfigOperationResult:
            return ConfigOperationResult(
                kind=ConfigOperationKind.FILE,
                package_id=config_file.package_id,
                status=status,
                expected_identity=expected,
                previous_identity=previous,
                detail=detail,
                destination=destination,
            )

        try:
            current = self._backend.read_file(destination)
        except ConfigBackendError as exc:
            return result(
                ConfigOperationStatus.FAILED, None,
                f"could not read {destination!r}: {exc}",
            )
        if current is not None and not isinstance(current, (bytes, bytearray)):
            return result(
                ConfigOperationStatus.FAILED, None,
                f"backend returned a non-bytes value for {destination!r}",
            )
        current_bytes = None if current is None else bytes(current)
        previous = None if current_bytes is None else _content_identity(current_bytes)

        if current_bytes is not None and current_bytes == config_file.content:
            return result(
                ConfigOperationStatus.ALREADY_CORRECT, previous,
                f"{destination!r} already matches the desired content",
            )

        try:
            self._backend.write_file(destination, config_file.content)
        except ConfigBackendError as exc:
            return result(
                ConfigOperationStatus.FAILED, previous,
                f"could not write {destination!r}: {exc}",
            )

        try:
            after = self._backend.read_file(destination)
        except ConfigBackendError as exc:
            return result(
                ConfigOperationStatus.FAILED, previous,
                f"could not verify {destination!r} after writing: {exc}",
            )
        if after is None:
            return result(
                ConfigOperationStatus.FAILED, previous,
                f"verification failed: {destination!r} is absent after writing",
            )
        if bytes(after) != config_file.content:
            return result(
                ConfigOperationStatus.FAILED, previous,
                f"verification mismatch for {destination!r}: expected "
                f"{expected}, read back {_content_identity(bytes(after))}",
            )

        status = (
            ConfigOperationStatus.CREATED if current_bytes is None
            else ConfigOperationStatus.UPDATED
        )
        verb = "created" if current_bytes is None else "updated"
        return result(status, previous, f"{destination!r} {verb} and verified")


# ---------------------------------------------------------------------------
# Production backend — Kodi runtime
# ---------------------------------------------------------------------------

class KodiRuntimeConfigurationBackend(ConfigurationBackend):
    """Production backend using the Kodi 20+ typed Settings wrapper and special://.

    Kodi modules (xbmcaddon, xbmcvfs) are imported lazily inside each method so
    this class is instantiable outside Kodi. Calling a method without Kodi
    loaded raises ConfigBackendError.

    Settings
    --------
    Both reads and writes use the Kodi 20+ typed Settings wrapper, which is the
    current recommended API:

        addon = xbmcaddon.Addon(addon_id)
        settings = addon.getSettings()
        settings.getString(key) / settings.setString(key, value)   # etc.

    The deprecated Addon.setSettingString/setSettingBool/setSettingInt/
    setSettingNumber (deprecated since Kodi 20) are deliberately NOT used.

    ADDON LIFETIME IS LOAD-BEARING
    ------------------------------
    The Addon object must stay referenced for as long as the Settings wrapper
    derived from it is used. Kodi's CAddonSettings reaches its owning add-on
    through a WEAK reference, so once the Addon is released the wrapper can
    still serve in-memory reads and accept writes while Save() is no longer
    able to reach its owner. The result is a silent persistence failure: the
    setter does not raise, in-memory state changes, no settings.xml appears,
    a fresh handle does not see the value, and a restart loses it.

    A helper of the shape

        def _settings_for(addon_id):          # WRONG
            addon = xbmcaddon.Addon(addon_id)
            return addon.getSettings()        # addon dies here

    reproduces exactly that failure, and an earlier revision of this module did
    so. Settings.setBool/setInt/setNumber/setString in
    xbmc/interfaces/legacy/Settings.cpp DO call settings->Save(); the wrapper
    is not at fault. That is why _open_addon() returns the Addon and every
    accessor keeps it bound in its own frame.

    Per-add-on settings.xml files are never edited directly: Build Manager owns
    selected keys, not the whole generated file.

    A fresh Addon handle is opened for every call, so post-write verification
    always reads through a new Addon/Settings pair rather than the handle that
    performed the write.

    Managed files
    -------------
    Destinations are relative to the current Kodi profile and are resolved
    against special://profile/ via xbmcvfs.translatePath — never a hard-coded
    OS path. After translation and symlink resolution, a destination that is
    not strictly inside the profile root is refused.

    Symlink policy
    --------------
    A managed destination names that exact filesystem path, never an alias to
    another file. No path component beneath the profile root may be a symlink —
    not a parent directory, not the destination itself. If any existing
    component is a symlink the operation fails closed, whether the link points
    outside the profile or at a different file inside it. Following an
    in-profile symlink would let a declared managed path redirect writes to an
    undeclared file, which would break the ownership model.

    Atomic replacement strategy
    ---------------------------
    Desired bytes are written to a securely created temporary file in the
    destination's own directory via tempfile.mkstemp(), which creates the file
    with O_CREAT|O_EXCL and mode 0600. The staging name is unique and
    unpredictable, so a pre-existing symlink cannot capture the write before
    the swap. The file is written, flushed, fsync'ed and closed, then moved
    into place with os.replace(), which overwrites atomically on both POSIX and
    Windows. Because the staging file is always a sibling of the destination,
    no cross-filesystem move occurs. The staging file is removed on every
    failure path.

    xbmcvfs.rename() is deliberately not used for the swap: Kodi documents it
    as unable to move between filesystems on all platforms, and CFile::Rename
    delegates straight to the platform handler with neither guaranteed
    overwrite semantics nor a copy+delete fallback. The original file is never
    deleted ahead of its replacement.

    Limitation (documented): this strategy requires special://profile/ to
    translate to a local filesystem path. If translation yields a VFS URL, the
    backend fails closed rather than falling back to a weaker mechanism. Every
    write is verified by re-reading the destination regardless.
    """

    def __init__(self, profile_root: str = "special://profile/", *,
                 skin_settings_backend=None) -> None:
        self._profile_root = profile_root
        self._translated_root: Optional[str] = None
        self._skin_settings_backend = skin_settings_backend

    # -- lazy Kodi imports --------------------------------------------------

    @staticmethod
    def _xbmcaddon():
        try:
            import xbmcaddon  # noqa: PLC0415
            return xbmcaddon
        except ImportError as exc:
            raise ConfigBackendError(
                f"Kodi runtime module (xbmcaddon) is not available: {exc}"
            ) from exc

    @staticmethod
    def _xbmcvfs():
        try:
            import xbmcvfs  # noqa: PLC0415
            return xbmcvfs
        except ImportError as exc:
            raise ConfigBackendError(
                f"Kodi runtime module (xbmcvfs) is not available: {exc}"
            ) from exc

    # -- settings -----------------------------------------------------------

    #: Settings-wrapper getter names, by setting type.
    _GETTER_NAMES = {
        ConfigSettingType.STRING: "getString",
        ConfigSettingType.BOOL: "getBool",
        ConfigSettingType.INT: "getInt",
        ConfigSettingType.NUMBER: "getNumber",
    }
    #: Settings-wrapper setter names, by setting type. The deprecated
    #: Addon.setSettingString/Bool/Int/Number are deliberately never used.
    _SETTER_NAMES = {
        ConfigSettingType.STRING: "setString",
        ConfigSettingType.BOOL: "setBool",
        ConfigSettingType.INT: "setInt",
        ConfigSettingType.NUMBER: "setNumber",
    }

    def _open_addon(self, addon_id: str):
        """Open a fresh Addon handle for addon_id.

        The caller MUST keep the returned object referenced for as long as the
        Settings wrapper derived from it is used — see the class docstring.
        This method therefore returns the Addon, never a Settings wrapper.
        """
        xbmcaddon = self._xbmcaddon()
        try:
            return xbmcaddon.Addon(addon_id)
        except Exception as exc:  # Kodi raises RuntimeError for unknown add-ons
            raise ConfigAddonUnavailableError(
                f"add-on {addon_id!r} could not be opened "
                f"(not installed, or disabled): {exc}"
            ) from exc

    @staticmethod
    def _settings_of(addon, addon_id: str):
        """Return the typed Settings wrapper for an already-open Addon."""
        try:
            return addon.getSettings()
        except Exception as exc:
            raise ConfigBackendError(
                f"add-on {addon_id!r}: getSettings() failed: {exc}"
            ) from exc

    def get_setting(
        self, addon_id: str, key: str, setting_type: ConfigSettingType
    ) -> object:
        # `addon` stays bound in this frame for the whole call: the Settings
        # wrapper must never outlive its owning Addon.
        addon = self._open_addon(addon_id)
        settings = self._settings_of(addon, addon_id)
        try:
            value = getattr(settings, self._GETTER_NAMES[setting_type])(key)
        except Exception as exc:
            raise ConfigBackendError(
                f"reading {addon_id}/{key} as {setting_type.value} failed: {exc}"
            ) from exc
        # Explicitly keep the owning Addon alive until after the wrapper call.
        del addon
        return value

    def set_setting(
        self, addon_id: str, key: str, setting_type: ConfigSettingType, value: object
    ) -> None:
        # `addon` stays bound in this frame across the setter call. Kodi's
        # CAddonSettings reaches its owning add-on through a WEAK reference,
        # so Save() cannot persist anything once the Addon has been released.
        addon = self._open_addon(addon_id)
        settings = self._settings_of(addon, addon_id)
        coerced = float(value) if setting_type is ConfigSettingType.NUMBER else value
        try:
            outcome = getattr(settings, self._SETTER_NAMES[setting_type])(
                key, coerced
            )
        except Exception as exc:
            raise ConfigBackendError(
                f"writing {addon_id}/{key} as {setting_type.value} failed: {exc}"
            ) from exc
        # Kodi's Settings setters return None (void) and raise on type errors.
        # Only an explicit False — from any other implementation — is a failure.
        if outcome is False:
            raise ConfigBackendError(
                f"Kodi rejected the value for {addon_id}/{key} "
                f"({setting_type.value})"
            )
        # Explicitly keep the owning Addon alive until after the setter and its
        # internal Save(). The caller still re-reads through a fresh handle.
        del addon

    # -- explicit skin settings --------------------------------------------

    def _skin_backend(self):
        """Return the dedicated skin-settings adapter, created lazily."""
        if self._skin_settings_backend is None:
            try:
                from resources.lib.skin import (  # noqa: PLC0415
                    KodiRuntimeSkinSettingsBackend,
                )
                self._skin_settings_backend = KodiRuntimeSkinSettingsBackend()
            except Exception as exc:
                raise ConfigBackendError(
                    f"skin-settings backend is unavailable: {exc}"
                ) from exc
        return self._skin_settings_backend

    def get_skin_setting(
        self, addon_id: str, key: str, setting_type: ConfigSettingType
    ) -> object:
        try:
            return self._skin_backend().get_setting(addon_id, key, setting_type)
        except ConfigBackendError:
            raise
        except Exception as exc:
            raise ConfigBackendError(
                f"reading skin:{addon_id}/{key} as {setting_type.value} failed: {exc}"
            ) from exc

    def set_skin_setting(
        self, addon_id: str, key: str, setting_type: ConfigSettingType, value: object
    ) -> None:
        try:
            self._skin_backend().set_setting(
                addon_id, key, setting_type, value
            )
        except ConfigBackendError:
            raise
        except Exception as exc:
            raise ConfigBackendError(
                f"writing skin:{addon_id}/{key} as {setting_type.value} failed: {exc}"
            ) from exc

    # -- managed files ------------------------------------------------------

    def _profile_path(self) -> str:
        """Resolved local filesystem path of special://profile/."""
        if self._translated_root is not None:
            return self._translated_root
        xbmcvfs = self._xbmcvfs()
        try:
            translated = xbmcvfs.translatePath(self._profile_root)
        except Exception as exc:
            raise ConfigBackendError(
                f"translatePath({self._profile_root!r}) failed: {exc}"
            ) from exc
        if not isinstance(translated, str) or not translated:
            raise ConfigBackendError(
                f"translatePath({self._profile_root!r}) returned "
                f"{translated!r}, expected a path"
            )
        if "://" in translated:
            raise ConfigBackendError(
                f"profile root {self._profile_root!r} translated to the VFS URL "
                f"{translated!r}; Build Manager requires a local filesystem "
                f"path for verified atomic managed-file replacement"
            )
        self._translated_root = os.path.realpath(translated)
        return self._translated_root

    def _resolve(self, destination: str) -> str:
        """Translate and contain a profile-relative destination path.

        Containment is lexical against the already-realpath'ed profile root,
        plus an explicit refusal of any existing symlink component. Resolving
        symlinks instead would silently accept an in-profile alias pointing at
        an undeclared file.
        """
        try:
            relative = _normalize_relative_path(destination, label="destination")
        except ConfigPackageError as exc:
            raise ConfigBackendError(str(exc)) from exc
        root = self._profile_path()
        components = relative.split("/")
        target = os.path.normpath(os.path.join(root, *components))
        if not _is_within(target, root):
            raise ConfigBackendError(
                f"destination {destination!r} resolves outside the Kodi profile "
                f"root and will not be written"
            )
        self._reject_symlink_components(root, components, destination)
        return target

    @staticmethod
    def _reject_symlink_components(
        root: str, components: List[str], destination: str
    ) -> None:
        """Fail closed if any existing component beneath root is a symlink.

        Checked with lstat semantics, so a symlink is detected whether it
        points outside the profile, at a different file inside it, or nowhere.
        """
        current = root
        for component in components:
            current = os.path.join(current, component)
            if os.path.islink(current):
                raise ConfigBackendError(
                    f"destination {destination!r} traverses a symlink at "
                    f"{component!r}; a managed path must name that exact file, "
                    f"not an alias to another one"
                )

    def read_file(self, destination: str) -> Optional[bytes]:
        path = self._resolve(destination)
        if not os.path.exists(path):
            return None
        if not os.path.isfile(path):
            raise ConfigBackendError(
                f"destination {destination!r} exists but is not a regular file"
            )
        try:
            with open(path, "rb") as handle:
                return handle.read()
        except OSError as exc:
            raise ConfigBackendError(
                f"could not read {destination!r}: {exc}"
            ) from exc

    def write_file(self, destination: str, data: bytes) -> None:
        path = self._resolve(destination)
        root = self._profile_path()
        parent = os.path.dirname(path)

        if os.path.exists(path) and not os.path.isfile(path):
            raise ConfigBackendError(
                f"destination {destination!r} exists but is not a regular file"
            )

        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise ConfigBackendError(
                f"could not create parent directory for {destination!r}: {exc}"
            ) from exc
        # makedirs only ever creates real directories, but re-check so a
        # symlink that appeared meanwhile cannot capture the write.
        self._reject_symlink_components(
            root, _normalize_relative_path(
                destination, label="destination"
            ).split("/"), destination,
        )
        if os.path.realpath(parent) != parent:
            raise ConfigBackendError(
                f"parent directory of {destination!r} is not a real path"
            )

        staged = None
        try:
            handle_fd, staged = tempfile.mkstemp(
                dir=parent, prefix=_TMP_PREFIX, suffix=_TMP_SUFFIX
            )
            with os.fdopen(handle_fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, path)
            staged = None
        except OSError as exc:
            raise ConfigBackendError(
                f"could not write {destination!r}: {exc}"
            ) from exc
        finally:
            if staged is not None:
                _remove_quietly(staged)


def _remove_quietly(path: str) -> None:
    """Delete a staged temporary file, ignoring absence or removal failure."""
    try:
        os.remove(path)
    except OSError:
        pass
