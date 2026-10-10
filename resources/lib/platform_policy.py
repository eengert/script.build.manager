"""D-028 preflight: platform software cannot be a mutation target."""

class PlatformMutationError(ValueError):
    code = "PLATFORM_SOFTWARE_IMMUTABLE"


def mutation_targets(desired, effective=None):
    targets = {item.addon_id for item in desired.addons}
    targets.update(item.addon_id for item in desired.repositories)
    if desired.skin is not None:
        targets.add(desired.skin.addon_id)
    config = desired.config
    if config is not None:
        targets.update(item.addon_id for item in config.managed_settings)
        targets.update(item.addon_id for item in config.private_settings)
        targets.update(item.owner_addon_id for item in config.structured_private_resources)
    files = list(config.managed_files if config is not None else ())
    if effective is not None:
        targets.update(item.addon_id for item in effective.settings)
        files.extend(item.destination for item in effective.files)
    for destination in files:
        parts = destination.replace('\\', '/').split('/')
        if len(parts) >= 2 and parts[0] in ('addon_data', 'addons'):
            targets.add(parts[1])
    return targets - {""}


def reject_platform_mutations(desired, platform_ids, effective=None):
    if platform_ids and mutation_targets(desired, effective).intersection(platform_ids):
        raise PlatformMutationError("configuration cannot target platform-provided software")


def reject_backend_platform_targets(backend, targets):
    """Application-origin software stays immutable even without a platform marker."""
    from resources.lib.frozen import InstalledOrigin
    for aid in targets:
        guard = getattr(backend, "assert_mutable_target", None)
        if callable(guard):
            guard(aid)
            continue
        reader = getattr(backend, "read_installed_metadata", None)
        metadata = reader(aid) if callable(reader) else None
        if metadata is not None and metadata.origin is InstalledOrigin.APPLICATION:
            raise PlatformMutationError("execution cannot target platform-provided software")
