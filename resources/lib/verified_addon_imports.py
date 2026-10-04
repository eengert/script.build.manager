"""Temporary imports from verified Kodi add-on package roots.

This is an internal import boundary for audited pre-activation declarations.
It accepts only verified installed-source descriptors, never manifest paths.
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import importlib.abc
import importlib.machinery
from pathlib import Path
import re
import sys
import sysconfig
import threading
from typing import Iterator, Mapping, Sequence

from resources.lib.installed_addon_source import (
    InstalledAddonSourceError,
    VerifiedInstalledAddonSource,
)


class VerifiedAddonImportError(ImportError):
    """A verified add-on package import could not be isolated safely."""

    def __init__(
        self,
        message: str = "verified add-on package import was rejected",
        *,
        import_failure_category: str = "",
        failing_module: str = "",
        expected_provider: str = "",
        actual_provider: str = "",
    ) -> None:
        self.import_failure_category = (
            import_failure_category
            if isinstance(import_failure_category, str)
            and _SAFE_FAILURE_CATEGORY.fullmatch(import_failure_category)
            else ""
        )
        self.failing_module = (
            failing_module
            if isinstance(failing_module, str)
            and _SAFE_MODULE_NAME.fullmatch(failing_module)
            else ""
        )
        self.expected_provider = (
            expected_provider
            if isinstance(expected_provider, str)
            and _SAFE_PROVIDER_ID.fullmatch(expected_provider)
            else ""
        )
        self.actual_provider = (
            actual_provider
            if isinstance(actual_provider, str)
            and _SAFE_PROVIDER_ID.fullmatch(actual_provider)
            else ""
        )
        super().__init__(message)


_IMPORT_CONTEXT_LOCK = threading.RLock()
_PYTHON_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_KODI_RUNTIME_MODULES = frozenset(("xbmc", "xbmcaddon", "xbmcgui", "xbmcplugin", "xbmcvfs"))
_STDLIB_MODULE_NAMES = getattr(sys, "stdlib_module_names", frozenset())
_SAFE_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_SAFE_MODULE_NAME = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,31}$"
)
_SAFE_FAILURE_CATEGORY = re.compile(r"^[A-Z0-9_]{1,80}$")
_REQUESTS_COMPATIBILITY_PROVIDERS = {
    "urllib3": "script.module.urllib3",
    "idna": "script.module.idna",
    "chardet": "script.module.chardet",
}
_REQUESTS_COMPATIBILITY_VERSION = "2.31.0"


def _root_modules(root: Path) -> dict[str, Path]:
    """Index importable top-level names in one already verified library root."""
    result = {}
    try:
        children = tuple(root.iterdir())
    except OSError as exc:
        raise VerifiedAddonImportError("verified Python library root is unavailable") from exc
    for child in children:
        if child.name == "__pycache__":
            continue
        name = child.stem if child.is_file() and child.suffix == ".py" else child.name
        if not _PYTHON_IDENTIFIER.fullmatch(name):
            continue
        if not child.is_file() and not child.is_dir():
            continue
        try:
            canonical = child.resolve(strict=True)
            canonical.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise VerifiedAddonImportError(
                "verified Python package entry escapes its library root"
            ) from exc
        result[name] = root
    return result


def _module_paths(module: object) -> tuple[Path, ...]:
    paths = []
    origin = getattr(module, "__file__", None)
    if origin:
        paths.append(Path(origin))
    else:
        spec = getattr(module, "__spec__", None)
        spec_origin = getattr(spec, "origin", None) if spec is not None else None
        if spec_origin and spec_origin not in {"built-in", "frozen"}:
            paths.append(Path(spec_origin))
    package_path = getattr(module, "__path__", None)
    if package_path is not None:
        try:
            paths.extend(Path(item) for item in tuple(package_path))
        except (TypeError, OSError, RuntimeError) as exc:
            raise VerifiedAddonImportError("verified package search path is invalid") from exc
    return tuple(paths)


def _module_provider(
    name: str,
    module: object,
    roots_by_provider: Mapping[str, Sequence[Path]],
    *,
    expected_provider: str = "",
) -> str:
    """Resolve a module object's provider from all canonical source locations."""
    try:
        paths = _module_paths(module)
    except VerifiedAddonImportError:
        raise VerifiedAddonImportError(
            "verified package module source could not be inspected",
            import_failure_category="MODULE_SOURCE_UNAVAILABLE",
            failing_module=name,
            expected_provider=expected_provider,
        ) from None
    if not paths:
        raise VerifiedAddonImportError(
            "verified package module has no inspectable source",
            import_failure_category="MODULE_SOURCE_UNAVAILABLE",
            failing_module=name,
            expected_provider=expected_provider,
        )

    observed_providers = set()
    for path in paths:
        try:
            canonical = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise VerifiedAddonImportError(
                "verified package module source is unavailable",
                import_failure_category="MODULE_SOURCE_MISMATCH",
                failing_module=name,
                expected_provider=expected_provider,
            ) from None
        matching = {
            provider
            for provider, roots in roots_by_provider.items()
            if any(
                canonical == root or canonical.is_relative_to(root)
                for root in roots
            )
        }
        if len(matching) > 1:
            raise VerifiedAddonImportError(
                "verified package module has ambiguous provider ownership",
                import_failure_category="MODULE_PROVIDER_AMBIGUOUS",
                failing_module=name,
                expected_provider=expected_provider,
            )
        if not matching:
            raise VerifiedAddonImportError(
                "verified package module source is outside verified providers",
                import_failure_category="MODULE_SOURCE_MISMATCH",
                failing_module=name,
                expected_provider=expected_provider,
            )
        observed_providers.update(matching)

    if len(observed_providers) != 1:
        raise VerifiedAddonImportError(
            "verified package module search paths have ambiguous providers",
            import_failure_category="MODULE_PROVIDER_AMBIGUOUS",
            failing_module=name,
            expected_provider=expected_provider,
        )
    return next(iter(observed_providers))


def _requests_alias_provider(name: str) -> str | None:
    prefix = "requests.packages."
    if not name.startswith(prefix):
        return None
    package = name[len(prefix):].split(".", 1)[0]
    return _REQUESTS_COMPATIBILITY_PROVIDERS.get(package)


def _assert_module_owned(
    name: str,
    module: object,
    providers_by_module_name: Mapping[str, str],
    versions_by_provider: Mapping[str, str],
    roots_by_provider: Mapping[str, Sequence[Path]],
) -> None:
    top_level = name.split(".", 1)[0]
    expected_provider = providers_by_module_name.get(top_level, "")
    alias_provider = _requests_alias_provider(name)
    if alias_provider is not None:
        expected_provider = alias_provider
        if alias_provider not in roots_by_provider:
            raise VerifiedAddonImportError(
                "Requests compatibility alias provider is outside the verified closure",
                import_failure_category="MODULE_PROVIDER_NOT_IN_CLOSURE",
                failing_module=name,
                expected_provider=alias_provider,
            )
        requests_provider = providers_by_module_name.get("requests", "")
        if (
            requests_provider != "script.module.requests"
            or versions_by_provider.get(requests_provider)
            != _REQUESTS_COMPATIBILITY_VERSION
        ):
            raise VerifiedAddonImportError(
                "Requests compatibility alias has no audited Requests provider",
                import_failure_category="MODULE_ALIAS_PROVIDER_UNVERIFIED",
                failing_module=name,
                expected_provider="script.module.requests",
                actual_provider=requests_provider,
            )

    if not expected_provider:
        return

    actual_provider = _module_provider(
        name,
        module,
        roots_by_provider,
        expected_provider=expected_provider,
    )
    if actual_provider != expected_provider:
        raise VerifiedAddonImportError(
            "verified package module source does not match its provider",
            import_failure_category="MODULE_SOURCE_MISMATCH",
            failing_module=name,
            expected_provider=expected_provider,
            actual_provider=actual_provider,
        )

    if alias_provider is None:
        return

    for parent_name in ("requests", "requests.packages"):
        parent = sys.modules.get(parent_name)
        if parent is None or _module_provider(
            parent_name,
            parent,
            roots_by_provider,
            expected_provider="script.module.requests",
        ) != "script.module.requests":
            raise VerifiedAddonImportError(
                "Requests compatibility alias is not rooted in verified Requests",
                import_failure_category="MODULE_ALIAS_PROVIDER_UNVERIFIED",
                failing_module=name,
                expected_provider="script.module.requests",
            )

    canonical_name = name[len("requests.packages."):]
    if sys.modules.get(canonical_name) is not module:
        raise VerifiedAddonImportError(
            "Requests compatibility alias is not the canonical module object",
            import_failure_category="MODULE_ALIAS_IDENTITY_MISMATCH",
            failing_module=name,
            expected_provider=expected_provider,
            actual_provider=actual_provider,
        )


def _stdlib_paths() -> tuple[Path, ...]:
    paths = []
    configured = sysconfig.get_paths()
    for key in ("stdlib", "platstdlib"):
        value = configured.get(key)
        if value:
            try:
                paths.append(Path(value).resolve(strict=True))
            except (OSError, RuntimeError):
                continue
    return tuple(dict.fromkeys(paths))


class _VerifiedTopLevelFinder(importlib.abc.MetaPathFinder):
    """Resolve known add-on module names only from their verified provider."""

    def __init__(self, roots_by_name: Mapping[str, tuple[Path, ...]]):
        self._roots_by_name = roots_by_name

    def find_spec(self, fullname, path=None, target=None):
        if "." in fullname:
            return None
        roots = self._roots_by_name.get(fullname)
        if roots is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(
            fullname, [str(root) for root in roots], target
        )
        if spec is None:
            raise ModuleNotFoundError(
                f"verified managed Python dependency does not provide {fullname}"
            )
        return spec


class _RejectUnverifiedTopLevelFinder(importlib.abc.MetaPathFinder):
    """Prevent the audited import chain from falling through to host packages."""

    def __init__(self, provided_names: set[str]):
        self._provided_names = provided_names

    def find_spec(self, fullname, path=None, target=None):
        if "." in fullname:
            return None
        if (
            fullname in self._provided_names
            or fullname in _STDLIB_MODULE_NAMES
            or fullname in _KODI_RUNTIME_MODULES
        ):
            return None
        raise ModuleNotFoundError(
            f"unverified top-level Python dependency {fullname} is blocked"
        )


@contextmanager
def verified_addon_import_context(
    owner_source: VerifiedInstalledAddonSource,
    dependency_sources: Sequence[VerifiedInstalledAddonSource] = (),
    *,
    required_module_providers: Mapping[str, str] | None = None,
) -> Iterator[object]:
    """Temporarily expose only module roots derived from verified sources.

    Dependency roots are listed before the owner's root. Known top-level
    package names are routed directly to the verified provider, so an absent
    managed dependency cannot be supplied accidentally by host ``site-packages``.
    """
    if not isinstance(owner_source, VerifiedInstalledAddonSource):
        raise VerifiedAddonImportError("verified owner source is unavailable")
    if not isinstance(dependency_sources, (tuple, list)):
        raise VerifiedAddonImportError("verified dependency sources are invalid")
    if required_module_providers is None:
        required_module_providers = {}
    if not isinstance(required_module_providers, Mapping):
        raise VerifiedAddonImportError("required module providers are invalid")

    with _IMPORT_CONTEXT_LOCK:
        try:
            owner = owner_source.revalidate()
            owner_roots = owner.python_module_roots()
            dependencies = []
            for source in dependency_sources:
                if not isinstance(source, VerifiedInstalledAddonSource):
                    raise VerifiedAddonImportError("verified dependency source is invalid")
                verified = source.revalidate()
                if (
                    verified.frozen_transaction_id != owner.frozen_transaction_id
                    or verified.manifest_fingerprint != owner.manifest_fingerprint
                ):
                    raise VerifiedAddonImportError(
                        "verified dependency belongs to another frozen transaction"
                    )
                dependencies.append((verified, verified.python_module_roots()))
            dependency_ids = {source.addon_id for source, _roots in dependencies}
            if len(dependency_ids) != len(dependencies):
                raise VerifiedAddonImportError("verified dependency sources contain duplicates")
            if owner.addon_id in dependency_ids:
                raise VerifiedAddonImportError("owner source is duplicated as a dependency")

            owner_names = {}
            for root in owner_roots:
                for name, provider_root in _root_modules(root).items():
                    if name in owner_names and owner_names[name] != provider_root:
                        raise VerifiedAddonImportError("owner Python module roots overlap")
                    owner_names[name] = provider_root
            dependency_names: dict[str, tuple[str, Path]] = {}
            for source, roots in dependencies:
                for root in roots:
                    for name, provider_root in _root_modules(root).items():
                        previous = dependency_names.get(name)
                        if previous is not None and previous != (source.addon_id, provider_root):
                            raise VerifiedAddonImportError(
                                "verified dependencies provide an ambiguous Python module"
                            )
                        dependency_names[name] = (source.addon_id, provider_root)
            if set(owner_names).intersection(dependency_names):
                raise VerifiedAddonImportError(
                    "owner and dependency Python module roots contain a collision"
                )

            providers_by_module_name = {
                name: owner.addon_id for name in owner_names
            }
            providers_by_module_name.update({
                name: addon_id for name, (addon_id, _root) in dependency_names.items()
            })
            providers_by_module_name["caches"] = owner.addon_id
            providers_by_module_name["modules"] = owner.addon_id
            versions_by_provider = {owner.addon_id: owner.version}
            versions_by_provider.update({
                source.addon_id: source.version for source, _roots in dependencies
            })
            roots_by_provider = {owner.addon_id: tuple(owner_roots)}
            roots_by_provider.update({
                source.addon_id: tuple(roots)
                for source, roots in dependencies
            })

            required = dict(required_module_providers)
            for module_name, addon_id in required.items():
                if (
                    not isinstance(module_name, str)
                    or not _PYTHON_IDENTIFIER.fullmatch(module_name)
                    or not isinstance(addon_id, str)
                    or not addon_id
                ):
                    raise VerifiedAddonImportError("required module provider identity is invalid")
                provider = dependency_names.get(module_name)
                if provider is None or provider[0] != addon_id:
                    raise VerifiedAddonImportError(
                        f"required managed Python dependency {addon_id} is unavailable"
                    )

            roots_by_name: dict[str, tuple[Path, ...]] = {
                name: (root,) for name, root in owner_names.items()
            }
            for name, (_addon_id, root) in dependency_names.items():
                roots_by_name[name] = (root,)
            roots_by_name["caches"] = tuple(root for root in owner_roots)
            roots_by_name["modules"] = tuple(root for root in owner_roots)

            controlled_roots = {
                name: roots
                for name, roots in roots_by_name.items()
            }
            controlled_names = set(controlled_roots)
            for loaded_name, loaded_module in tuple(sys.modules.items()):
                top_level = loaded_name.split(".", 1)[0]
                if top_level in controlled_roots:
                    _assert_module_owned(
                        loaded_name,
                        loaded_module,
                        providers_by_module_name,
                        versions_by_provider,
                        roots_by_provider,
                    )

            root_order = []
            for _source, roots in dependencies:
                root_order.extend(str(root) for root in roots)
            root_order.extend(str(root) for root in owner_roots)
            root_order = list(dict.fromkeys(root_order))
        except (InstalledAddonSourceError, VerifiedAddonImportError):
            raise
        except Exception as exc:
            raise VerifiedAddonImportError("verified Python import roots are unavailable") from exc

        old_path = list(sys.path)
        old_meta_path = list(sys.meta_path)
        stdlib_roots = _stdlib_paths()
        modules_before = dict(sys.modules)
        prefix_snapshot = {
            name: module
            for name, module in tuple(sys.modules.items())
            if name.split(".", 1)[0] in controlled_names
        }
        dict_snapshots = {
            name: dict(module.__dict__)
            for name, module in prefix_snapshot.items()
            if hasattr(module, "__dict__")
        }
        finder = _VerifiedTopLevelFinder(controlled_roots)
        reject_unverified = _RejectUnverifiedTopLevelFinder(controlled_names)
        try:
            sys.path[:] = root_order + [entry for entry in old_path if entry not in root_order]
            sys.meta_path.insert(0, finder)
            sys.meta_path.insert(1, reject_unverified)
            yield importlib.import_module
            for loaded_name, loaded_module in tuple(sys.modules.items()):
                top_level = loaded_name.split(".", 1)[0]
                if top_level in controlled_roots:
                    _assert_module_owned(
                        loaded_name,
                        loaded_module,
                        providers_by_module_name,
                        versions_by_provider,
                        roots_by_provider,
                    )
            for loaded_name, loaded_module in tuple(sys.modules.items()):
                if loaded_name in modules_before:
                    continue
                module_paths = _module_paths(loaded_module)
                if not module_paths:
                    if loaded_name.split(".", 1)[0] in _STDLIB_MODULE_NAMES | _KODI_RUNTIME_MODULES:
                        continue
                    continue
                accepted_roots = tuple(owner_roots) + tuple(
                    root for _source, roots in dependencies for root in roots
                ) + stdlib_roots
                for module_path in module_paths:
                    try:
                        canonical = module_path.resolve(strict=True)
                    except (OSError, RuntimeError):
                        raise VerifiedAddonImportError(
                            f"initializer imported unavailable Python module {loaded_name}"
                        ) from None
                    if any(canonical == root or canonical.is_relative_to(root) for root in accepted_roots):
                        continue
                    top_level = loaded_name.split(".", 1)[0]
                    if top_level in _KODI_RUNTIME_MODULES:
                        continue
                    if top_level in _STDLIB_MODULE_NAMES:
                        continue
                    raise VerifiedAddonImportError(
                        "initializer imported a Python module outside verified roots"
                    )
        finally:
            sys.path[:] = old_path
            sys.meta_path[:] = old_meta_path
            for name in tuple(sys.modules):
                top_level = name.split(".", 1)[0]
                if top_level not in controlled_names:
                    continue
                if name not in prefix_snapshot:
                    sys.modules.pop(name, None)
            for name, module in prefix_snapshot.items():
                sys.modules[name] = module
                namespace = getattr(module, "__dict__", None)
                previous = dict_snapshots.get(name)
                if namespace is not None and previous is not None:
                    namespace.clear()
                    namespace.update(previous)
