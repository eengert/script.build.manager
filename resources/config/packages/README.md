# Configuration packages

Embedded Build Manager configuration packages live here, one directory per
package:

```
resources/config/packages/<package-id>/
    package.json
    files/
        ...
```

`<package-id>` must match `[a-z0-9][a-z0-9._-]*` (64 characters maximum) and is
never treated as a path.

Packages are selected by `config.packages` in the manifest and are applied in
resolved order (base → platform → device → optional groups); later packages
override earlier ones per target.

A package may only affect targets the manifest declares in
`config.managed_settings` and `config.managed_files`. See
[`docs/CONFIG_PACKAGES.md`](../../../docs/CONFIG_PACKAGES.md) for the descriptor
schema, ownership rules and safety model.

**Public packages must never contain credentials, tokens, passwords, OAuth
state, or any other secret.** Portable authentication state is the subject of
BM-017 and the private overlay, not of these packages.

BM-015 supports embedded/local packages only. Remote or versioned package
delivery is deliberately out of scope.

The production `af3-common` package is the initial reviewed AF3 policy. It
contains only typed `target: "skin"` bool/string settings for
`skin.arctic.fuse.3`, has no file overlays, and is selected by the manifest's
`skin.config_packages` declaration. Its exact ownership remains declared by
`config.managed_settings`; the package cannot broaden that boundary.
