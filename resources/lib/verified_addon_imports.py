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


_IMPORT_CONTEXT_LOCK = threading.RLock()
_PYTHON_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OWNER_NAMESPACES = frozenset(("caches", "modules"))
_KODI_RUNTIME_MODULES = frozenset(("xbmc", "xbmcaddon", "xbmcgui", "xbmcplugin", "xbmcvfs"))
_STDLIB_MODULE_NAMES = getattr(sys, "stdlib_module_names", frozenset())


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


def _assert_module_owned(name: str, module: object, roots: Sequence[Path]) -> None:
    paths = _module_paths(module)
    if not paths:
        raise VerifiedAddonImportError("verified package module has no inspectable source path")
    for path in paths:
        try:
            canonical = path.resolve(strict=True)
            if not any(canonical == root or canonical.is_relative_to(root) for root in roots):
                raise ValueError
        except (OSError, RuntimeError, ValueError) as exc:
            raise VerifiedAddonImportError(
                f"preexisting {name.split('.', 1)[0]} package is outside verified roots"
            ) from exc


def _module_is_owned(module: object, roots: Sequence[Path]) -> bool:
    paths = _module_paths(module)
    if not paths:
        return False
    try:
        for path in paths:
            canonical = path.resolve(strict=True)
            if not any(
                canonical == root or canonical.is_relative_to(root)
                for root in roots
            ):
                return False
        return True
    except (OSError, RuntimeError, ValueError):
        return False


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
            if len({source.addon_id for source, _roots in dependencies}) != len(dependencies):
                raise VerifiedAddonImportError("verified dependency sources contain duplicates")

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
            dependency_names_by_top_level = set(dependency_names)
            for loaded_name, loaded_module in tuple(sys.modules.items()):
                top_level = loaded_name.split(".", 1)[0]
                roots = controlled_roots.get(top_level)
                if roots is not None:
                    _assert_module_owned(loaded_name, loaded_module, roots)

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
                roots = controlled_roots.get(top_level)
                if roots is not None:
                    _assert_module_owned(loaded_name, loaded_module, roots)
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
                original = prefix_snapshot.get(name)
                if original is not None:
                    sys.modules[name] = original
                    namespace = getattr(original, "__dict__", None)
                    previous = dict_snapshots.get(name)
                    if namespace is not None and previous is not None:
                        namespace.clear()
                        namespace.update(previous)
                elif top_level in _OWNER_NAMESPACES:
                    # These two package names are scoped to this owner's
                    # temporary import context. Clear every newly created
                    # entry, including namespace roots with no __file__.
                    sys.modules.pop(name, None)
                elif (
                    top_level in dependency_names_by_top_level
                    and _module_is_owned(
                        sys.modules[name],
                        controlled_roots[top_level],
                    )
                ):
                    # The context itself loaded this exact managed dependency
                    # package for declaration import. Remove only its newly
                    # created entries; preexisting shared modules are restored
                    # from the snapshot above.
                    sys.modules.pop(name, None)
            for name, module in prefix_snapshot.items():
                sys.modules[name] = module
